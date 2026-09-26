from msa.agents.base import AgentFailure
from msa.contracts import Report


def run(state, *, context):
    report = context.call(
        "advisory",
        {
            "run_id": state["run_id"],
            "graph": state["graph"],
            "mode": state["mode"],
            "positions": state.get("positions", []),
            "results": state.get("sorted_results", []),
            "portfolio": state.get("portfolio_result"),
            "position_names": state.get("position_names", {}),
            "macro_parameters": state.get("macro_parameters", {}),
            "seed": state.get("seed"),
            "options": context.options,
        },
        Report,
    )
    if report.run_id != state["run_id"] or report.mode != state["mode"]:
        raise AgentFailure(["Report identity differs from run"])
    # Agents cannot grant approval; only human_approval owns these fields.
    data = report.model_dump()
    data.update(approved_by=None, approved_at=None)
    report = Report.model_validate(data)
    return {"report": report, "status": "awaiting_approval"}
