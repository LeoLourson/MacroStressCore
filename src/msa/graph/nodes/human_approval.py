from datetime import UTC, datetime

from langgraph.types import interrupt

from msa.contracts import Report


def run(state, *, context):
    if context.auto_approve_demo and state.get("mode") == "demo":
        report = Report.model_validate(
            {**state["report"], "approved_by": "demo:auto", "approved_at": datetime.now(UTC)}
        )
        return {"report": report, "status": "approved"}
    error = None
    while True:
        answer = interrupt(
            {
                "kind": "human_approval",
                "run_id": state["run_id"],
                "report": state["report"],
                "error": error,
            }
        )
        answer = answer if isinstance(answer, dict) else {}
        author = answer.get("approved_by")
        if answer.get("approved") is False:
            reason = answer.get("reason")
            reason = reason.strip() if isinstance(reason, str) else ""
            if not reason:
                # A negative decision without its reason leaves nothing to review or rework.
                error = "A negative decision requires a nonempty reason"
                continue
            decision = {
                "outcome": "returned" if answer.get("returned") else "rejected",
                "reason": reason,
                "by": author,
                "at": datetime.now(UTC).isoformat(),
            }
            return {"status": decision["outcome"], "published": False, "decision": decision}
        if (
            answer.get("approved") is True
            and isinstance(author, str)
            and author.strip()
            and author.strip() != "demo:auto"
        ):
            report = dict(state["report"])
            report.update(approved_by=author.strip(), approved_at=datetime.now(UTC))
            return {"report": Report.model_validate(report), "status": "approved"}
        error = "Approval requires approved=true and a nonempty human approved_by"
