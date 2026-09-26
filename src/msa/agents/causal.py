import json
from datetime import UTC, datetime
from functools import cache
from importlib.resources import files

from msa.contracts import SourceDocument, TransmissionGraph
from msa.contracts.evidence import Evidence
from msa.integrations.llm import LLMClient, MockLLM
from msa.prompts.registry import current_version, messages_for

from .base import AgentError
from .causal_output import CausalOutput


@cache
def _MOCK_EVENTS() -> dict:
    """The mock profile's answer for the library events: their channel, sector and driver."""
    return json.loads(files(__package__).joinpath("mock_events.json").read_text("utf-8"))


class CausalAgent:
    def __init__(self, llm=None, *, mock=False, estimate_scenario=False):
        self.llm = llm
        self.mock = mock
        self.estimate_scenario = estimate_scenario

    @staticmethod
    def _mock_response(document, scope, context):
        source = document.fragments[0]
        evidence = {
            "kind": "document",
            "source_id": document.doc_id,
            "locator": source.locator,
            "fragment_sha256": source.sha256,
        }
        fixture = _MOCK_EVENTS().get(document.doc_id, {})
        okved = fixture.get("okved", sorted(scope)[0] if scope else "46.63")
        channel = fixture.get("channel", "channel")
        driver = fixture.get("driver", "revenue")
        specs = {spec["factor_id"]: spec for spec in context.get("factors", [])}
        graph_specs = [spec for spec in specs.values() if spec["scope"] == "graph"]
        selected = next(
            (spec for spec in graph_specs if spec["factor_id"].endswith("." + driver)),
            graph_specs[0] if graph_specs else None,
        )
        factor = selected["factor_id"] if selected else None
        graph = {
            "event_id": "event",
            "nodes": [
                {"id": "event", "kind": "event", "label": "event"},
                {"id": "channel", "kind": "channel", "label": channel},
                {"id": "sector", "kind": "sector", "label": okved, "okved": okved},
                {"id": "factor", "kind": "factor", "label": driver, "factor": factor},
            ],
            "edges": [
                {
                    "src": a,
                    "dst": b,
                    "sign": 1,
                    "elasticity": {"family": "point", "value": 1.0},
                    "lag_months": 0,
                    "evidence": [evidence],
                }
                for a, b in (("event", "channel"), ("channel", "sector"), ("sector", "factor"))
            ],
            "factor_elasticity": {},
        }
        words = next((f for f in document.fragments if f.locator == "scenario"), source)
        # A fixed central shock with a spread around it: 45 days of delay, costs up or revenue
        # down by 10 %, from half to one and a half times that.
        days = selected is not None and selected["unit"] == "days"
        central = 45.0 if days else (-0.1 if driver == "revenue" else 0.1)
        low, high = sorted((0.5 * central, 1.5 * central))
        scenario = {
            "label": "Сила воздействия канала (тестовый ответ)",
            "kind": "triangular",
            "low": low,
            "mode": central,
            "high": high,
            "unit": selected["unit"] if selected else "fraction",
            "channel": "channel",
            "factor": factor,
            "evidence": [{**evidence, "locator": words.locator, "fragment_sha256": words.sha256}],
        }
        proposals = {"channel_shock": scenario} if selected else {}
        if not selected:
            graph["nodes"] = graph["nodes"][:2]
            graph["edges"] = graph["edges"][:1]
        direct = sorted(
            {
                (item["factor_id"], item["key"])
                for position in context.get("positions", [])
                for item in position["factors"]
                if specs[item["factor_id"]]["scope"] != "graph"
            }
        )
        for index, (factor_id, key) in enumerate(direct):
            spec = specs[factor_id]
            low, mode, high = (15, 30, 45) if spec["unit"] == "days" else (-0.15, -0.1, -0.05)
            name = f"direct_{index}"
            graph["nodes"].append(
                {
                    "id": name,
                    "kind": "factor",
                    "factor": factor_id,
                    "key": key,
                    "label": spec["label"],
                }
            )
            graph["edges"].append(
                {
                    **graph["edges"][0],
                    "src": "channel",
                    "dst": name,
                }
            )
            proposals[name] = {
                "label": f"{spec['label']}: {key} (тестовый ответ)",
                "kind": "triangular",
                "low": low,
                "mode": mode,
                "high": high,
                "unit": spec["unit"],
                "factor": factor_id,
                "key": key,
                "evidence": [
                    {**evidence, "locator": words.locator, "fragment_sha256": words.sha256}
                ],
            }
        return {
            "passport": {"event_type": fixture.get("event_type", "mock_event")},
            "parameters": {},
            "direct_okved": [okved] if selected else [],
            "inferred_okved": [],
            "graph": graph,
            "scenario": proposals,
            "prompt_version": current_version("causal"),
        }

    def run_structured(self, payload: dict) -> CausalOutput:
        document = SourceDocument.model_validate(payload["document"])
        if document.status != "parsed" or not document.fragments:
            raise AgentError("An addressable text version is required")
        scope = set(payload.get("okved_scope") or [])
        context = payload.get("portfolio_context")
        if context is None:
            raise AgentError("Causal analysis requires the portfolio's plugin model context")
        messages = messages_for(
            "causal",
            "\n".join(f"[{f.locator} sha256={f.sha256}] {f.text}" for f in document.fragments),
            violations=payload.get("violations") or (),
            doc_id=document.doc_id,
            okved_scope=scope,
            portfolio_context=context,
        )
        llm = self.llm or (
            MockLLM(self._mock_response(document, scope, context)) if self.mock else LLMClient()
        )
        estimate = self.estimate_scenario and not any(
            f.locator == "scenario" for f in document.fragments
        )
        if estimate:
            messages[0]["content"] += "\n\n" + (
                files("msa.prompts.templates").joinpath("demo-scenario-v2.txt").read_text("utf-8")
            )
        output = llm.complete(messages, CausalOutput, payload["seed"])
        if estimate:
            if not output.scenario:
                raise AgentError("Demo scenario requires proposed assumptions for analyst review")
            for parameter in output.scenario.values():
                if parameter.kind != "triangular" or not parameter.evidence:
                    raise AgentError(
                        "Demo assumptions require triangular bounds and source context"
                    )
                for evidence in parameter.evidence:
                    self._verify_document_evidence(document, evidence)
                # Attribution is server-owned; a model cannot present a guess as a sourced fact.
                parameter.evidence = [
                    Evidence.model_validate(
                        {
                            **e.model_dump(),
                            "kind": "expert_assumption",
                            "author": f"LLM:{getattr(llm, 'model', 'demo')} (демо, не утверждено)",
                            "as_of": datetime.now(UTC).date(),
                        }
                    )
                    for e in parameter.evidence
                ]
                parameter.label = "Демо-допущение: " + parameter.label
        if output.prompt_version != current_version("causal"):
            raise AgentError("Response prompt_version differs from requested version")
        self._verify_model_context(output, context)
        for parameter in output.parameters.values():
            for evidence in parameter.evidence:
                self._verify_document_evidence(document, evidence)
        for edge in output.graph.edges:
            for evidence in edge.evidence:
                if evidence.kind == "document":
                    self._verify_document_evidence(document, evidence)
        for parameter in output.scenario.values():
            for evidence in parameter.evidence:
                self._verify_document_evidence(document, evidence)
        return output

    @staticmethod
    def _verify_model_context(output, context):
        """An LLM cannot introduce factors, units or keys that no selected model reads."""
        specs = {spec["factor_id"]: spec for spec in context["factors"]}
        references = {
            (item["factor_id"], item["key"])
            for position in context["positions"]
            for item in position["factors"]
        }
        for node in output.graph.nodes:
            if node.kind != "factor":
                continue
            if (node.factor, node.key) not in references:
                raise AgentError(
                    f"Factor/key is not used by this portfolio: {node.factor}:{node.key}"
                )
            paths = output.graph.simple_paths(output.graph.event_id, node.id)
            if not paths:
                raise AgentError(f"Factor {node.id} has no path from the event")
            if specs[node.factor]["scope"] == "graph":
                kinds = {item.id: item.kind for item in output.graph.nodes}
                if any(
                    [kinds[edge.dst] for edge in path] != ["channel", "sector", "factor"]
                    for path in paths
                ):
                    raise AgentError(f"Graph factor {node.id} needs a channel and a sector")
        for parameter in output.scenario.values():
            if (parameter.factor, parameter.key) not in references:
                raise AgentError(
                    f"Scenario factor/key is not used by this portfolio: "
                    f"{parameter.factor}:{parameter.key}"
                )
            if parameter.unit != specs[parameter.factor]["unit"]:
                raise AgentError(f"Scenario unit does not match factor {parameter.factor}")

    @staticmethod
    def _verify_document_evidence(document, evidence):
        if evidence.source_id != document.doc_id:
            raise AgentError("Evidence refers to another document")
        try:
            fragment = document.by_locator(evidence.locator)
        except KeyError as exc:
            raise AgentError("Evidence locator is absent from the original") from exc
        if fragment.sha256 != evidence.fragment_sha256:
            raise AgentError("Evidence fragment hash differs from the original")

    def run(self, payload: dict) -> TransmissionGraph:
        return self.run_structured(payload).graph
