"""An example agent plugin: research notes on where a portfolio's tail loss concentrates.

It shows the agent SDK end to end and is off by default (enable it per run with
``"agents": ["research.concentration", "research.brief"]`` or for the process with
``MSA_AGENT_PLUGINS``):

- ``research.concentration`` is a LangGraph subgraph with its own state: its input adapter
  turns the run's view into a list of slices, a bounded cycle reads one slice per step and
  its output adapter returns only the notes;
- ``research.brief`` runs after it at the same extension point and reads its notes through
  ``ext:research.concentration/notes``;
- ``research.digest`` calls the plugin's own read-only MCP tool
  ``research.notes.slice_digest`` through ``AgentContext.tools``: the gateway lets it call
  only the tools it declared, and every call is audited under its node of the run (the
  screen «Вызовы LLM и MCP»);
- all three join ``after_calculation`` of the stress test, write only to their own
  namespaces (``extensions["research.concentration"]``, ...), and the run still stops for
  the risk manager: no extension point lies on a path around a human decision.

Nothing here calls an LLM or the network. The UI plugin ``ui/web/src/plugins/research``
draws the outputs of ``research.concentration`` and ``research.digest``.
"""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from msa.plugin_sdk import CallContext, McpServerSpec, Plugin
from msa.plugin_sdk.agent import AgentPlugin

PLUGIN_ID = "research"
POINT = "after_calculation"
#: A position whose share of the slice's ES95 is at least this is named in the notes.
MATERIAL_SHARE = 0.25


class Note(BaseModel):
    slice_id: str
    position_id: str
    name: str
    share_of_es95: float


class ConcentrationOutput(BaseModel):
    notes: list[Note]


class BriefOutput(BaseModel):
    brief: list[str]


class SliceDigest(BaseModel):
    slice_id: str
    positions: int
    top_share: float
    herfindahl: float


class DigestOutput(BaseModel):
    digest: list[SliceDigest]


class ResearchState(TypedDict, total=False):
    slices: list[dict]
    names: dict
    step: int
    notes: list[dict]


def _read_slice(state: ResearchState) -> ResearchState:
    item = state["slices"][state["step"]]
    total = sum(max(c["expected_shortfall_contribution"], 0.0) for c in item["contributions"])
    notes = list(state.get("notes") or [])
    if total > 0:
        for c in sorted(item["contributions"], key=lambda c: -c["expected_shortfall_contribution"]):
            share = c["expected_shortfall_contribution"] / total
            if share >= MATERIAL_SHARE:
                notes.append(
                    {
                        "slice_id": item["slice_id"],
                        "position_id": c["position_id"],
                        "name": state["names"].get(c["position_id"], ""),
                        "share_of_es95": round(share, 4),
                    }
                )
    return {"notes": notes, "step": state["step"] + 1}


def _more(state: ResearchState):
    return "read_slice" if state["step"] < len(state["slices"]) else END


def build_concentration(context):
    graph = StateGraph(ResearchState)
    graph.add_node("read_slice", _read_slice)
    graph.add_conditional_edges(START, _more, ["read_slice", END])
    graph.add_conditional_edges("read_slice", _more, ["read_slice", END])
    return graph.compile()


def concentration_input(view: dict) -> ResearchState:
    """The run's view -> the subgraph's own state."""
    portfolio = view.get("portfolio_result") or {}
    slices = [
        {"slice_id": slice_id, "contributions": item.get("contributions") or []}
        for slice_id, item in sorted((portfolio.get("slices") or {}).items())
    ]
    return {"slices": slices, "names": view.get("position_names") or {}, "step": 0, "notes": []}


def concentration_output(state: ResearchState) -> dict:
    """The subgraph's state -> what the agent publishes in its namespace."""
    return {"notes": state.get("notes") or []}


def build_brief(context):
    def run(view: dict) -> dict:
        notes = view.get("ext:research.concentration/notes") or []
        brief = [
            f"{note['position_id']} {note['name']}".strip()
            + f": {note['share_of_es95'] * 100:.0f} % ES95 среза {note['slice_id']}"
            for note in notes
        ]
        return {"brief": brief or ["Существенной концентрации хвостового риска не найдено."]}

    return run


def register_notes(tool, services):
    """``mcp-research.notes``: arithmetic over the slices an agent passes in; no data access."""

    @tool
    def slice_digest(slices: list[dict], audit: CallContext) -> list[dict]:
        """How concentrated each slice's tail loss is: its contributors, the largest share
        of ES95 and the Herfindahl index of the shares (positive contributions only)."""
        rows = []
        for item in slices:
            positive = [
                max(c["expected_shortfall_contribution"], 0.0) for c in item["contributions"]
            ]
            total = sum(positive)
            shares = [value / total for value in positive] if total > 0 else []
            rows.append(
                {
                    "slice_id": item["slice_id"],
                    "positions": len(item["contributions"]),
                    "top_share": round(max(shares, default=0.0), 4),
                    "herfindahl": round(sum(share * share for share in shares), 4),
                }
            )
        return rows


def build_digest(context):
    def run(view: dict) -> dict:
        slices = concentration_input(view)["slices"]
        return {"digest": context.tools.call(DIGEST_TOOL, slices=slices)}

    return run


DIGEST_TOOL = "research.notes.slice_digest"

plugin = Plugin(
    plugin_id=PLUGIN_ID,
    version="1.1.0",
    sdk=">=1.1,<2.0",
    label="Исследование концентрации (пример)",
    description="Пример агентного плагина: подграф с собственным состоянием, агент, "
    "читающий его результат, и агент со своим MCP-инструментом. Выключен по умолчанию.",
    agents=(
        AgentPlugin(
            agent_id="research.concentration",
            version="1.0.0",
            label="Концентрация хвостового риска",
            build=build_concentration,
            extends={"stress_test": POINT},
            consumes=("portfolio_result", "position_names"),
            produces=("notes",),
            output_schema=ConcentrationOutput,
            subgraph_input=concentration_input,
            subgraph_output=concentration_output,
            max_iterations=4,
            timeout_s=30.0,
            enabled_by_default=False,
            description="Позиции с долей не меньше 25 % в ES95 своего среза.",
        ),
        AgentPlugin(
            agent_id="research.brief",
            version="1.0.0",
            label="Краткая справка по концентрации",
            build=build_brief,
            extends={"stress_test": POINT},
            consumes=("ext:research.concentration/notes",),
            produces=("brief",),
            output_schema=BriefOutput,
            after=("research.concentration",),
            timeout_s=10.0,
            enabled_by_default=False,
        ),
        AgentPlugin(
            agent_id="research.digest",
            version="1.0.0",
            label="Сводка концентрации по срезам",
            build=build_digest,
            extends={"stress_test": POINT},
            consumes=("portfolio_result",),
            produces=("digest",),
            tools=(DIGEST_TOOL,),
            output_schema=DigestOutput,
            timeout_s=30.0,
            enabled_by_default=False,
            description="Для каждого среза: число позиций, наибольшая доля в ES95 и индекс "
            "Херфиндаля — через собственный MCP-инструмент плагина.",
        ),
    ),
    mcp_servers=(
        McpServerSpec(
            "research.notes",
            register_notes,
            label="Заметки исследования",
            description="Арифметика концентрации по срезам, переданным агентом; без доступа к "
            "данным.",
        ),
    ),
)
