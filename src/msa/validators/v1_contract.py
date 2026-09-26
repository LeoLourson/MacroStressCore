from pydantic import BaseModel, TypeAdapter, ValidationError

from .base import Verdict


def check(payload, model_cls) -> list[Verdict]:
    """Validate JSON values or model instances; paths use RFC 6901 escaping."""
    if isinstance(payload, BaseModel):
        payload = payload.model_dump(mode="python")
    try:
        TypeAdapter(model_cls).validate_python(payload)
    except ValidationError as exc:
        return [
            Verdict(
                ok=False,
                rule_id="V1",
                path="".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in e["loc"]),
                message=e["msg"],
            )
            for e in exc.errors(include_input=False, include_url=False, include_context=False)
        ]
    return [Verdict(ok=True, rule_id="V1", path="", message="Contract is valid")]
