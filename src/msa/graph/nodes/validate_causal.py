def run(state, *, context):
    verdicts = context.validate("TransmissionGraph", state["graph"])
    return {"verdicts": verdicts}
