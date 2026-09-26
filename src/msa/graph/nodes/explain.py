def run(state, *, context):
    explanation = context.explainer.run({"run_id": state["run_id"], "question": state["question"]})
    return {"explanation": explanation.model_dump(mode="json"), "status": "completed"}
