from pydantic import TypeAdapter

from msa.contracts import SourceDocument
from msa.contracts.common import McPoints, Seed


def run(state, *, context):
    seed = TypeAdapter(Seed).validate_python(state["seed"])
    mc_points = TypeAdapter(McPoints).validate_python(state["mc_points"])
    mode = state["mode"]
    if mode not in {"demo", "production"}:
        raise ValueError("mode must be demo or production")
    document = context.call("ingest", {"text": state["text"]}, SourceDocument)
    return {
        "document": document,
        "seed": seed,
        "mc_points": mc_points,
        "mode": mode,
        "attempts": 0,
        "graph_revision": 0,
        "published": False,
        "status": "needs_review" if document.status == "unparsed" else "running",
        "errors": ["Document is unparsed; upload a text version"]
        if document.status == "unparsed"
        else [],
    }
