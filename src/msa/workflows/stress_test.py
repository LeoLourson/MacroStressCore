"""The stress-test workflow: event -> graph and scenario -> positions -> slices -> report.

::

  ingest ─► [after_event_parsed] ─► causal_agent ─► validate_causal ─┬► causal_agent (retry)
                                                                     ├► [before_scenario_approval]
                                                                     │   ─► human_fix_graph
                                                                     │   ─► validate_causal
                                                                     └► exposure_profiler
  exposure_profiler ─► draw_macro
  draw_macro ─► quant_agent × positions ─► aggregate ─► [after_calculation] ─► advisory_agent
  advisory_agent ─► [before_report] ─► human_approval ─┬► publish
                                                       ├► [before_scenario_approval] (returned)
                                                       └► end (rejected)

Points in brackets are extension points: pass-through nodes plugin agents join. None of
them lies on a path that skips a human stop, and plugin agents write only to their own
namespace, so no plugin can change the confirmed scenario, the results or the report.
"""

from copy import deepcopy
from functools import partial
from typing import TypedDict

from langgraph.graph import END
from langgraph.types import Send

from msa.graph.nodes import (
    advisory,
    aggregate,
    causal,
    draw_macro,
    exposure,
    human_approval,
    human_fix_graph,
    ingest,
    publish,
    quant_asset,
    validate_causal,
)
from msa.graph.state import RunState
from msa.plugin_sdk.agent import (
    AgentPlugin,
    ExtensionPoint,
    NodeSpec,
    Route,
    StageSpec,
    WorkflowSpec,
)

WORKFLOW_ID = "stress_test"
VERSION = "2.0.0"
HORIZON = 12


class RunInput(TypedDict, total=False):
    run_id: str
    text: str
    seed: int
    mc_points: int
    horizon: int
    mode: str
    portfolio_id: str
    snapshot_id: str
    base_currency: str
    portfolio_positions: list[dict]
    position_names: dict[str, str]
    request_graph_review: bool
    as_of: str


def scenario_pending(state):
    """The analyst still has to confirm the proposed scenario, or set one that is required."""
    if state.get("scenario_confirmed"):
        return False
    return bool(state.get("macro_parameters")) or bool(state.get("scenario_required"))


def after_ingest(state):
    return END if state["status"] == "needs_review" else "after_event_parsed"


def after_validate(state):
    verdicts = state.get("verdicts", [])
    valid = bool(verdicts) and all(v["ok"] for v in verdicts)
    if valid:
        review = state.get("request_graph_review") or scenario_pending(state)
        return "before_scenario_approval" if review else "exposure_profiler"
    if state.get("graph_revision", 0) or state["attempts"] >= 3:
        return "before_scenario_approval"
    return "causal_agent"


def fan_out(state):
    if state.get("status") == "needs_review":
        return END
    # Send owns one isolated input per branch; only the branch results and trace are reduced.
    return [
        Send("quant_agent", {**deepcopy(state), "branch_position_id": position_id})
        for position_id in sorted(p["position"]["position_id"] for p in state["positions"])
    ] or "aggregate"


def stop_on_review(target):
    def route(state):
        return END if state["status"] == "needs_review" else target

    return route


def after_approval(state):
    # A returned report goes back to the analyst; a rejected one closes the run.
    return {"approved": "publish", "returned": "before_scenario_approval"}.get(state["status"], END)


def _core(agent_id, label, module, *, consumes=(), tools=(), version="2.0.0"):
    return AgentPlugin(
        agent_id=f"core.{agent_id}",
        version=version,
        label=label,
        build=lambda ctx, module=module: partial(module.run, context=ctx.services),
        consumes=consumes,
        tools=tools,
        core=True,
    )


CORE_AGENTS = (
    _core("ingest", "Разбор события", ingest, consumes=("text", "seed", "mc_points", "mode")),
    _core(
        "causal",
        "Граф влияния и сценарий",
        causal,
        consumes=("document", "attempts", "portfolio_positions"),
    ),
    _core("validate_causal", "Проверка графа", validate_causal, consumes=("graph",)),
    _core("human_fix_graph", "Проверка графа и сценария аналитиком", human_fix_graph),
    _core(
        "exposure",
        "Отбор позиций и данные",
        exposure,
        consumes=("graph", "macro_parameters", "portfolio_positions", "as_of", "snapshot_id"),
        tools=("portfolio.resolve_inputs",),
    ),
    _core(
        "draw_macro",
        "Совместные сценарии",
        draw_macro,
        consumes=("macro_parameters", "diagnostics", "seed", "mc_points", "graph"),
    ),
    _core(
        "quant",
        "Расчёт позиции",
        quant_asset,
        consumes=("scenario_set", "branch_position_id", "prepared", "diagnostics"),
        tools=("models.run_model",),
    ),
    _core(
        "aggregate",
        "Итоги по срезам портфеля",
        aggregate,
        consumes=("position_results", "scenario_set"),
    ),
    _core(
        "advisory",
        "Отчёт и рекомендации",
        advisory,
        consumes=("sorted_results", "portfolio_result", "macro_parameters", "graph"),
    ),
    _core("human_approval", "Решение риск-менеджера", human_approval),
    _core("publish", "Публикация", publish, consumes=("report",)),
)

CORE_KEYS = frozenset(RunState.__annotations__) - {"trace", "extensions"}

STRESS_TEST = WorkflowSpec(
    workflow_id=WORKFLOW_ID,
    version=VERSION,
    label="Стресс-тест портфеля по тексту события",
    description="Событие → граф влияния и сценарий → расчёт позиций → срезы портфеля → отчёт.",
    state_schema=RunState,
    input_schema=RunInput,
    nodes=(
        NodeSpec("ingest", "core.ingest", "event"),
        NodeSpec("after_event_parsed", None, "event"),
        NodeSpec("causal_agent", "core.causal", "event"),
        NodeSpec("validate_causal", "core.validate_causal", "event"),
        NodeSpec("before_scenario_approval", None, "scenario"),
        NodeSpec("human_fix_graph", "core.human_fix_graph", "scenario", human=True),
        NodeSpec("exposure_profiler", "core.exposure", "calculation"),
        NodeSpec("draw_macro", "core.draw_macro", "calculation"),
        NodeSpec("quant_agent", "core.quant", "calculation", branch="branch_position_id"),
        NodeSpec("aggregate", "core.aggregate", "portfolio"),
        NodeSpec("after_calculation", None, "portfolio"),
        NodeSpec("advisory_agent", "core.advisory", "report"),
        NodeSpec("before_report", None, "decision"),
        NodeSpec("human_approval", "core.human_approval", "decision", human=True),
        NodeSpec("publish", "core.publish", "decision"),
    ),
    edges=(
        ("__start__", "ingest"),
        ("after_event_parsed", "causal_agent"),
        ("causal_agent", "validate_causal"),
        ("before_scenario_approval", "human_fix_graph"),
        ("human_fix_graph", "validate_causal"),
        ("quant_agent", "aggregate"),
        ("after_calculation", "advisory_agent"),
        ("before_report", "human_approval"),
        ("publish", "__end__"),
    ),
    routes=(
        Route("ingest", after_ingest, ("__end__", "after_event_parsed")),
        Route(
            "validate_causal",
            after_validate,
            ("causal_agent", "before_scenario_approval", "exposure_profiler"),
        ),
        Route("exposure_profiler", stop_on_review("draw_macro"), ("__end__", "draw_macro")),
        Route("draw_macro", fan_out, ("quant_agent", "aggregate", "__end__")),
        Route("aggregate", stop_on_review("after_calculation"), ("__end__", "after_calculation")),
        Route("advisory_agent", stop_on_review("before_report"), ("__end__", "before_report")),
        Route(
            "human_approval",
            after_approval,
            ("publish", "before_scenario_approval", "__end__"),
        ),
    ),
    extension_points=(
        ExtensionPoint(
            "after_event_parsed",
            "После разбора события",
            available=("document", "text", "portfolio_positions", "position_names"),
        ),
        ExtensionPoint(
            "before_scenario_approval",
            "Перед подтверждением сценария",
            available=(
                "document",
                "graph",
                "macro_parameters",
                "event_passport",
                "portfolio_positions",
                "position_names",
                "verdicts",
            ),
        ),
        ExtensionPoint(
            "after_calculation",
            "После расчётов",
            available=(
                "graph",
                "macro_parameters",
                "positions",
                "sorted_results",
                "portfolio_result",
                "position_names",
                "scenario_id",
            ),
        ),
        ExtensionPoint(
            "before_report",
            "Перед решением по отчёту",
            available=("report", "sorted_results", "portfolio_result", "position_names"),
        ),
    ),
    stages=(
        StageSpec(
            "event",
            "Анализ события",
            ("ingest", "after_event_parsed", "causal_agent", "validate_causal"),
        ),
        StageSpec(
            "scenario", "Проверка графа и сценария", ("before_scenario_approval", "human_fix_graph")
        ),
        StageSpec(
            "calculation", "Расчёт по позициям", ("exposure_profiler", "draw_macro", "quant_agent")
        ),
        StageSpec("portfolio", "Итоги по портфелю", ("aggregate", "after_calculation")),
        # The numbers are ready before the report: writing it is a step of its own.
        StageSpec("report", "Написание отчёта", ("advisory_agent",)),
        StageSpec("decision", "Решение по отчёту", ("before_report", "human_approval", "publish")),
    ),
    core_keys=CORE_KEYS,
)
