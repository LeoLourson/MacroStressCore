import json
import re
from datetime import UTC, datetime
from functools import cache
from importlib.resources import files

from msa.contracts import SourceDocument, TransmissionGraph
from msa.contracts.evidence import Evidence
from msa.integrations.llm import LLMClient, MockLLM
from msa.prompts.registry import current_version, messages_for

from .base import AgentError
from .causal_output import CausalOutput
from .ingest import is_scenario


@cache
def _MOCK_EVENTS() -> dict:
    """The mock profile's answers: the analyst's prepared answer of each library event.

    Keyed by the sha256 of the event text; written by ``demo/build_catalog.py``.
    """
    return json.loads(files(__package__).joinpath("mock_events.json").read_text("utf-8"))


def _stems(text: str) -> set[str]:
    return {word[:5] for word in re.findall(r"\w{4,}", text.lower())}


def _cite(document, fragments, words: str) -> list[dict]:
    """The fragment sharing most word stems with ``words`` (the first on a tie), as evidence."""
    best = max(fragments, key=lambda f: len(_stems(f.text) & _stems(words)))
    return [
        {
            "kind": "document",
            "source_id": document.doc_id,
            "locator": best.locator,
            "fragment_sha256": best.sha256,
        }
    ]


def _prepared_response(document, answer, context) -> dict:
    """A library event's prepared answer as the causal step returns it.

    One sector node per (channel, OKVED), one factor node per (OKVED, factor) and one direct
    factor node per (factor, key). Only the factors the portfolio's models read enter the
    graph and the scenario, as an LLM's answer is held to them. An edge cites the sentence of
    the event nearest to its channel's words, a scenario parameter the sentence of the
    scenario nearest to its label.
    """
    event = [f for f in document.fragments if not is_scenario(f.locator)]
    scenario_words = [f for f in document.fragments if is_scenario(f.locator)] or event
    used = {
        (item["factor_id"], item["key"])
        for position in context.get("positions", [])
        for item in position["factors"]
    }
    specs = {spec["factor_id"]: spec for spec in context.get("factors", [])}
    nodes = {"event": {"id": "event", "kind": "event", "label": answer["event_type"]}}
    edges = []

    def edge(src, dst, channel, *, sign=1, elasticity=1.0, lag=0):
        if isinstance(elasticity, list):
            low, mode, high = elasticity
            spec = {"family": "triangular", "low": low, "mode": mode, "high": high}
        else:
            spec = {"family": "point", "value": elasticity}
        edges.append(
            {
                "src": src,
                "dst": dst,
                "sign": sign,
                "elasticity": spec,
                "lag_months": lag,
                "evidence": _cite(document, event, nodes[channel]["label"]),
            }
        )

    def channel(name):
        if name not in nodes:
            label = answer.get("channels", {}).get(name, name)
            nodes[name] = {"id": name, "kind": "channel", "label": label}
            edge("event", name, name)

    def factor_node(node_id, factor, key=None):
        nodes.setdefault(
            node_id,
            {"id": node_id, "kind": "factor", "label": specs[factor]["label"], "factor": factor}
            | ({"key": key} if key is not None else {}),
        )

    okveds = set()
    for link in answer.get("links", []):
        if (link["factor"], None) not in used:
            continue
        channel(link["channel"])
        code = link["okved"].replace(".", "_")
        sector = f"{link['channel']}__{code}"
        if sector not in nodes:
            nodes[sector] = {
                "id": sector,
                "kind": "sector",
                "label": link["okved"],
                "okved": link["okved"],
            }
            edge(link["channel"], sector, link["channel"], elasticity=link.get("exposure", 1.0))
        target = f"{link['factor'].replace('.', '_')}__{code}"
        factor_node(target, link["factor"])
        edge(
            sector,
            target,
            link["channel"],
            sign=link.get("sign", 1),
            elasticity=link.get("elasticity", 1.0),
            lag=link.get("lag", 0),
        )
        okveds.add(link["okved"])
    for item in answer.get("direct", []):
        if (item["factor"], item["key"]) not in used:
            continue
        channel(item["channel"])
        target = f"{item['factor']}__{item['key']}".replace(".", "_").replace("/", "_")
        factor_node(target, item["factor"], item["key"])
        edge(item["channel"], target, item["channel"])
    scenario = {
        name: {**spec, "evidence": _cite(document, scenario_words, spec["label"])}
        for name, spec in answer.get("scenario", {}).items()
        if (spec["factor"], spec.get("key")) in used and spec.get("channel") in nodes
    }
    return {
        "passport": {"event_type": answer["event_type"]},
        "parameters": {},
        "direct_okved": sorted(okveds),
        "inferred_okved": [],
        "graph": {
            "event_id": "event",
            "nodes": list(nodes.values()),
            "edges": edges,
            "factor_elasticity": {},
        },
        "scenario": scenario,
        "prompt_version": current_version("causal"),
    }


class CausalAgent:
    def __init__(self, llm=None, *, mock=False, estimate_scenario=False):
        self.llm = llm
        self.mock = mock
        self.estimate_scenario = estimate_scenario

    @staticmethod
    def _mock_response(document, scope, context):
        answer = _MOCK_EVENTS().get(document.doc_id)
        if answer is not None:
            return _prepared_response(document, answer, context)
        # Any other text: one channel to the first sector in scope, a spread around a fixed
        # central shock, and every direct factor of the portfolio left for the analyst.
        source = document.fragments[0]
        evidence = {
            "kind": "document",
            "source_id": document.doc_id,
            "locator": source.locator,
            "fragment_sha256": source.sha256,
        }
        okved = sorted(scope)[0] if scope else "46.63"
        channel, driver = "channel", "revenue"
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
        words = next((f for f in document.fragments if is_scenario(f.locator)), source)
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
        direct = sorted(
            {
                (item["factor_id"], item["key"])
                for position in context.get("positions", [])
                for item in position["factors"]
                if specs[item["factor_id"]]["scope"] != "graph"
            }
        )
        if not selected:
            # A channel that reaches no factor is rejected (V3): without any factor, the event.
            graph["nodes"] = graph["nodes"][: 2 if direct else 1]
            graph["edges"] = graph["edges"][: 1 if direct else 0]
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
            "passport": {"event_type": "mock_event"},
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
            is_scenario(f.locator) for f in document.fragments
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

        # The retry prompt carries this text: it names the keys the model may use instead.
        def unused(factor, key):
            keys = sorted(str(k) for f, k in references if f == factor and k is not None)
            known = f"its keys here: {', '.join(keys)}" if keys else "no position reads it"
            return f"{factor} with key {key} is not used by this portfolio; {known}"

        for node in output.graph.nodes:
            if node.kind != "factor":
                continue
            if (node.factor, node.key) not in references:
                raise AgentError(f"Factor node {node.id}: {unused(node.factor, node.key)}")
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
        for name, parameter in output.scenario.items():
            if parameter.factor is None:
                raise AgentError(
                    f"Scenario parameter {name} moves no factor: name a factor and key of "
                    "portfolio_context, or keep the magnitude in parameters only"
                )
            if (parameter.factor, parameter.key) not in references:
                raise AgentError(
                    f"Scenario parameter {name}: {unused(parameter.factor, parameter.key)}"
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
