"""New asset types reach causal analysis and calculation without core special cases."""

from copy import deepcopy
from dataclasses import replace
from datetime import date
from importlib import import_module

import pytest

from msa.agents.advisory import AdvisoryAgent
from msa.agents.aggregate import AggregateAgent
from msa.agents.base import AgentError
from msa.agents.causal import CausalAgent
from msa.agents.draw_macro import DrawMacroAgent
from msa.agents.exposure import ExposureAgent, LocalResolver
from msa.agents.quant import QuantAgent
from msa.contracts import SourceDocument, TransmissionGraph
from msa.contracts.common import Contract
from msa.contracts.domain import PositionContext
from msa.engine.causal_context import portfolio_context
from msa.engine.exposure import missing_direct_scenario, reasons
from msa.graph.interrupts import start_run
from msa.platform.registry import build, registry
from msa.plugin_sdk import (
    CalculationModel,
    DataRequirements,
    Diagnostics,
    FactorRequirement,
    FactorSpec,
    InstrumentTypeSpec,
    MetricSpec,
    Plugin,
    RunOptions,
)
from msa.plugin_sdk.results import envelope, scalar
from msa.prompts.registry import current_version
from msa.validators import validate
from msa.workflows import plugin as core_plugin
from tests.support import agents, confirm, positions, run_input, snapshot, stop


class Terms(Contract):
    region: str


class Holding(Contract):
    value: float


class PropertyModel(CalculationModel):
    model_id = "property.value.v1"
    version = "1.0.0"
    label = "Стоимость недвижимости"
    description = "Стоимость объекта изменяется пропорционально региональной цене."
    instrument_types = ("property_holding",)
    factors = ("property.regional_price",)
    metrics = required_metrics = ("property.value",)

    def requirements(self, position, options):
        return DataRequirements(
            factors=[
                FactorRequirement(
                    factor_id=self.factors[0], key=position.instrument.terms["region"]
                )
            ]
        )

    def validate(self, prepared):
        return Diagnostics()

    def calculate(self, prepared, context):
        names = context.scenario.parameters_for(
            self.factors[0], prepared.context.instrument.terms["region"]
        )
        shock = sum(context.scenario.central(name) for name in names)
        value = prepared.context.position.params["value"] * (1 + shock)
        return envelope(
            prepared,
            context,
            self,
            plugin_id="property",
            plugin_version="1.0.0",
            status="ok",
            metrics={"property.value": scalar("property.value", "RUB_million", value)},
        )


def property_registry():
    return build(
        [
            core_plugin,
            Plugin(
                plugin_id="property",
                version="1.0.0",
                sdk=">=1.0,<2.0",
                label="Недвижимость",
                instrument_types=(
                    InstrumentTypeSpec(
                        type_id="property_holding",
                        label="Объект недвижимости",
                        terms_schema=Terms,
                        position_schema=Holding,
                        default_model=PropertyModel.model_id,
                        issuer_required=False,
                    ),
                ),
                models=(PropertyModel(),),
                factors=(
                    FactorSpec(
                        "property.regional_price",
                        "Цена недвижимости в регионе",
                        "fraction",
                        "global",
                        "relative",
                        "relative_change",
                        key_label="Регион",
                        description="Относительное изменение цены.",
                    ),
                ),
                metrics=(MetricSpec("property.value", "Стоимость", "RUB_million", kind="value"),),
            ),
        ]
    )


def property_position():
    return PositionContext.model_validate(
        {
            "portfolio_id": "PROPERTY-PORTFOLIO",
            "position": {
                "position_id": "PROPERTY",
                "instrument_id": "OBJECT",
                "params": {"value": 100},
            },
            "instrument": {
                "instrument_id": "OBJECT",
                "instrument_type": "property_holding",
                "name": "Объект",
                "terms": {"region": "north"},
            },
            "base_currency": "RUB",
        }
    )


OPTIONS = RunOptions(as_of=date(2026, 9, 11), horizon=6)


def payload_for(raw, reg):
    doc = agents().ingest.run({"text": "Региональная цена снизится на 10%."})
    return {
        "document": doc.model_dump(mode="json"),
        "seed": 42,
        "portfolio_context": portfolio_context(raw, OPTIONS, reg),
    }


class CapturingLLM:
    def __init__(self, response):
        self.response = response
        self.messages = []

    def complete(self, messages, schema, seed):
        self.messages = messages
        return schema.model_validate(deepcopy(self.response))


def test_only_selected_model_factors_and_their_units_reach_the_llm():
    raw = [p for p in positions() if p["instrument"]["instrument_type"] == "common_stock"]
    payload = payload_for(raw, registry())
    context = payload["portfolio_context"]
    assert context["horizon_months"] == 6
    assert not any(f["factor_id"].startswith("credit.") for f in context["factors"])
    assert all(f["unit"] == "log_return" for f in context["factors"])
    response = CausalAgent._mock_response(
        SourceDocument.model_validate(payload["document"]), set(), context
    )
    llm = CapturingLLM(response)
    output = CausalAgent(llm=llm).run_structured(payload)
    assert output.prompt_version == current_version("causal") == "v3"
    assert "portfolio_context" in llm.messages[1]["content"]
    assert "bank portfolio" not in llm.messages[0]["content"]
    assert all(n.key for n in output.graph.nodes if n.kind == "factor")


@pytest.mark.parametrize("corruption", ["foreign_factor", "wrong_key", "wrong_unit"])
def test_llm_cannot_escape_the_selected_plugin_contract(corruption):
    payload = payload_for([property_position()], property_registry())
    response = CausalAgent._mock_response(
        SourceDocument.model_validate(payload["document"]), set(), payload["portfolio_context"]
    )
    if corruption == "foreign_factor":
        response["graph"]["nodes"][-1]["factor"] = "credit.revenue"
    elif corruption == "wrong_key":
        response["scenario"]["direct_0"]["key"] = "south"
    else:
        response["scenario"]["direct_0"]["unit"] = "log_return"
    with pytest.raises(AgentError):
        CausalAgent(llm=CapturingLLM(response)).run_structured(payload)


def test_new_issuerless_nonlogarithmic_asset_runs_to_report_without_credit_plugins(
    graph_factory, monkeypatch
):
    reg = property_registry()
    configured = agents()
    monkeypatch.setattr(import_module("msa.platform.registry"), "_CURRENT", reg)
    configured = replace(
        configured,
        causal=CausalAgent(mock=True),
        exposure=ExposureAgent(registry=reg, resolver=LocalResolver(snapshot(), lambda _: None)),
        quant=QuantAgent(registry=reg),
        draw_macro=DrawMacroAgent(registry=reg),
        aggregate=AggregateAgent(registry=reg),
        advisory=AdvisoryAgent(
            registry=reg,
            thresholds_repository=type("Thresholds", (), {"current": lambda self: {}})(),
        ),
    )
    graph, _ = graph_factory(agents=configured, registry_=reg)
    start_run(
        graph,
        run_input(
            "new-plugin",
            portfolio_positions=[property_position().model_dump(mode="json")],
            horizon=6,
        ),
    )
    pending = stop(graph, "new-plugin")
    assert pending["kind"] == "human_fix_graph"
    assert all(v["ok"] for v in pending["violations"])
    assert not any(n["kind"] == "sector" for n in pending["graph"]["nodes"])
    assert pending["macro_parameters"]["direct_0"]["unit"] == "fraction"
    state = confirm(graph, "new-plugin")
    assert stop(graph, "new-plugin")["kind"] == "human_approval"
    result = state["sorted_results"][0]
    assert result["execution"] == "completed"
    assert result["metrics"]["property.value"]["value"] == pytest.approx(90)
    assert state["report"]


def test_unquantified_direct_factor_keeps_an_issuerless_position_for_review():
    reg, position = property_registry(), property_position()
    payload = payload_for([position], reg)
    response = CausalAgent._mock_response(
        SourceDocument.model_validate(payload["document"]), set(), payload["portfolio_context"]
    )
    graph = TransmissionGraph.model_validate(response["graph"])
    needs = reg.model_for(position).requirements(position, OPTIONS)
    assert missing_direct_scenario(position, needs, graph, {}, reg) == [
        "Цена недвижимости в регионе: north"
    ]


def test_one_provided_factor_does_not_hide_another_missing_factor():
    raw = next(p for p in positions() if p["instrument"]["instrument_type"] == "common_stock")
    payload = payload_for([raw], registry())
    output = CausalAgent(mock=True).run_structured(payload)
    position = PositionContext.model_validate(raw)
    needs = registry().model_for(position).requirements(position, OPTIONS)
    one = next(iter(output.scenario.items()))
    assert reasons(position, needs, output.graph, {one[0]: one[1]}, registry())
    assert missing_direct_scenario(position, needs, output.graph, {one[0]: one[1]}, registry())


def test_direct_node_is_valid_but_requires_a_key(monkeypatch):
    reg = property_registry()
    monkeypatch.setattr(import_module("msa.platform.registry"), "_CURRENT", reg)
    payload = payload_for([property_position()], reg)
    output = CausalAgent(mock=True).run_structured(payload)
    assert all(v.ok for v in validate("TransmissionGraph", output.graph))
    raw = output.graph.model_dump(mode="json")
    raw["nodes"][-1]["key"] = None
    assert any(not v.ok and v.rule_id == "V2" for v in validate("TransmissionGraph", raw))


def test_stock_portfolio_runs_with_only_its_own_factor_graph(graph_factory):
    raw = [p for p in positions() if p["instrument"]["instrument_type"] == "common_stock"]
    graph, _ = graph_factory(agents=agents(calculate=True, causal=CausalAgent(mock=True)))
    start_run(graph, run_input("stock-factors", portfolio_positions=raw))
    pending = stop(graph, "stock-factors")
    assert all(v["ok"] for v in pending["violations"])
    assert all(
        not n.get("factor", "").startswith("credit.")
        for n in pending["graph"]["nodes"]
        if n.get("factor")
    )
    state = confirm(graph, "stock-factors")
    assert stop(graph, "stock-factors")["kind"] == "human_approval"
    assert all(r["execution"] == "completed" for r in state["sorted_results"])
    assert "market.pnl" in state["portfolio_result"]["slices"]
    assert "credit.loss" not in state["portfolio_result"]["slices"]
