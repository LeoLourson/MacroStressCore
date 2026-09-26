from msa.contracts import Report


def run(state, *, context):
    report = Report.model_validate(state["report"])
    approval = context.repository.get_node_result(
        state["run_id"],
        "human_approval",
        state["graph_revision"] + 1,
    )
    if (
        state.get("status") != "approved"
        or not report.approved_by
        or not report.approved_at
        or not approval
        or approval.get("status") != "approved"
        or approval.get("report") != report.model_dump(mode="json")
    ):
        raise ValueError("Publication requires the persisted approval of this exact report")
    # The journal stores the publication atomically; external delivery belongs to D/G.
    if report.mode == "demo" and report.approved_by == "demo:auto":
        return {"published": False, "status": "completed", "report": report}
    return {"published": True, "status": "published", "report": report}
