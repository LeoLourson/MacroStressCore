"""V2: data are what their declarations say.

- Every factor node names a registered factor; direct factors identify their key.
- Every instrument's terms and position's parameters satisfy their plugin's versioned
  schema, and every instrument type is registered.

The names, units and bounds come from the plugins' declarations (``msa.platform``); this
validator holds no list of its own.
"""

from pydantic import BaseModel

from .base import Verdict


def _pointer(*parts):
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts)


def check_graph(data) -> list[Verdict]:
    from msa.platform.registry import registry

    factors = registry().factors
    errors = []
    for index, node in enumerate(data.get("nodes") or []):
        if not isinstance(node, dict) or node.get("kind") != "factor":
            continue
        spec = factors.get(node.get("factor"))
        if spec is None:
            errors.append(
                Verdict(
                    ok=False,
                    rule_id="V2",
                    path=_pointer("nodes", index, "factor"),
                    message=f"Неизвестный фактор {node.get('factor')!r}",
                )
            )
        elif (spec.scope == "graph" and node.get("key") is not None) or (
            spec.scope != "graph" and not node.get("key")
        ):
            errors.append(
                Verdict(
                    ok=False,
                    rule_id="V2",
                    path=_pointer("nodes", index, "factor"),
                    message=f"Фактор {spec.factor_id}: "
                    + (
                        "фактор графа не имеет ключа"
                        if spec.scope == "graph"
                        else "для прямого фактора нужен ключ"
                    ),
                )
            )
    return errors


def check_bundle(data) -> list[Verdict]:
    from msa.contracts.domain import PortfolioBundle
    from msa.db.repositories.portfolios import check_bundle as problems
    from msa.platform.registry import registry

    bundle = PortfolioBundle.model_validate(data)
    return [
        Verdict(ok=False, rule_id="V2", path="/" + message.split(":", 1)[0], message=message)
        for message in problems(bundle, registry())
    ]


def check(payload) -> list[Verdict]:
    data = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
    data = data if isinstance(data, dict) else {}
    if "portfolio" in data and "positions" in data:
        errors = check_bundle(data)
    else:
        errors = check_graph(data)
    return errors or [Verdict(ok=True, rule_id="V2", path="", message="Declarations are met")]


class UnitsValidator:
    def check(self, payload):
        return check(payload)
