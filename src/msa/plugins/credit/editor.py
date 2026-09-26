"""The portfolio editor's form of a credit type, and how a typed row becomes data.

Every number the analyst types becomes a sourced assumption with the analyst as author
(``DraftContext.evidence``). The borrower's figures go to a financial statement of the
analyst's snapshot, the contractual terms to the instrument, the exposure to the position.
A covenant is tested on a series the family declares, in that series' unit (audit finding
A3: the unit is no longer always ``ratio``).
"""

from dataclasses import replace

from msa.plugin_sdk import EditorField, EditorGroup

from .editor_help import FIELD_HINTS
from .families import family_for
from .schemas import FINANCIAL_STATEMENT, SCHEMA_VERSION


def _with_help(field):
    return replace(
        field,
        hint=field.hint or FIELD_HINTS.get(field.name, ""),
        columns=tuple(_with_help(column) for column in field.columns),
    )


POSITION_FIELDS = (
    EditorField(
        "ead", "Сумма под риском (EAD)", "position", unit="RUB_million", required=True, minimum=0.0
    ),
    EditorField("lgd", "Потери при дефолте (LGD)", "position", unit="fraction", required=True),
    EditorField(
        "ccf",
        "Коэффициент кредитной конверсии",
        "position",
        unit="fraction",
        default=1.0,
        advanced=True,
    ),
    EditorField(
        "import_share",
        "Доля импорта в затратах",
        "position",
        unit="fraction",
        default=0.0,
        advanced=True,
    ),
)


def _field(item, target) -> EditorField:
    return EditorField(
        name=item.name,
        label=item.label,
        target=target,
        unit=item.unit,
        required=item.required,
        default=item.default,
        assumption=item.assumption,
        hint=item.hint,
        advanced=item.advanced,
        minimum=item.bounds()[0],
        maximum=item.bounds()[1],
    )


def editor(family) -> tuple[EditorGroup, ...]:
    groups = [EditorGroup("position", "Позиция банка", POSITION_FIELDS)]
    statement = family.fields_from("statement")
    if statement:
        groups.append(
            EditorGroup(
                "statement",
                "Отчётность заёмщика",
                tuple(_field(item, f"snapshot:{FINANCIAL_STATEMENT}") for item in statement),
            )
        )
    terms = family.fields_from("terms")
    if terms:
        groups.append(
            EditorGroup("terms", "Условия инструмента", tuple(_field(i, "terms") for i in terms))
        )
    market = family.fields_from("market")
    if market:
        groups.append(
            EditorGroup(
                "market",
                "Рыночные данные на дату оценки",
                tuple(_field(item, f"snapshot:{item.market[0]}") for item in market),
            )
        )
    if family.covenant_metrics:
        groups.append(
            EditorGroup(
                "covenants",
                "Ковенанты",
                (
                    EditorField(
                        "covenants",
                        "Ковенанты",
                        "terms",
                        kind="table",
                        columns=(
                            EditorField(
                                "metric",
                                "Показатель",
                                "terms",
                                kind="enum",
                                required=True,
                                options=tuple((m.name, m.label) for m in family.covenant_metrics),
                            ),
                            EditorField(
                                "operator",
                                "Условие",
                                "terms",
                                kind="enum",
                                required=True,
                                options=(("ge", "не ниже"), ("le", "не выше")),
                            ),
                            EditorField("threshold", "Порог", "terms", required=True),
                            EditorField(
                                "test_dates", "Даты проверки", "terms", kind="dates", required=True
                            ),
                        ),
                        hint="по умолчанию — концы кварталов горизонта расчёта",
                    ),
                ),
            )
        )
    return tuple(
        replace(group, fields=tuple(_with_help(f) for f in group.fields)) for group in groups
    )


def from_draft(row: dict, ctx) -> dict:
    """``row``: position id, instrument type, typed ``values`` and ``tables``."""
    family = family_for(row["instrument_type"])
    position_id = row["position_id"]
    values = row.get("values") or {}
    declared = {item.name: item for item in family.fields}
    known = {*declared, *(f.name for f in POSITION_FIELDS)}
    unknown = sorted(set(values) - known)
    if unknown:
        raise ValueError(f"{position_id}: unknown fields {unknown}")

    def parameter(name, unit):
        value = values[name]
        return {"value": value, "unit": unit, "evidence": ctx.evidence(position_id, name, value)}

    params = {}
    for item in POSITION_FIELDS:
        value = values.get(item.name, item.default)
        if value is None:
            raise ValueError(f"{position_id}: {item.label} is required")
        values.setdefault(item.name, value)
        params[item.name] = parameter(item.name, item.unit)
    terms = {"covenants": [], "collateral": []}
    statement, market = {}, {}
    for name, item in declared.items():
        if name not in values or values[name] is None:
            continue
        if item.source == "terms":
            terms[name] = parameter(name, item.unit)
        elif item.source == "market":
            market[name] = (item, parameter(name, item.unit))
        else:
            statement[name] = parameter(name, item.unit)
    metrics = {metric.name for metric in family.covenant_metrics}
    for index, covenant in enumerate((row.get("tables") or {}).get("covenants") or []):
        if covenant["metric"] not in metrics:
            raise ValueError(
                f"{position_id}: a covenant on {covenant['metric']} is not tested for "
                f"{row['instrument_type']}"
            )
        terms["covenants"].append(
            {
                "covenant_id": f"{position_id}-{covenant['metric']}"
                + (f"-{index + 1}" if index else ""),
                "metric": covenant["metric"],
                "operator": covenant["operator"],
                "threshold": covenant["threshold"],
                "unit": family.unit(covenant["metric"]),
                "test_dates": sorted(covenant["test_dates"]),
                "evidence": ctx.evidence(
                    position_id, f"covenant/{covenant['metric']}", covenant["threshold"]
                ),
            }
        )
    items = []
    if statement:
        items.append(
            {
                "item_id": f"{FINANCIAL_STATEMENT}:{ctx.issuer_id(position_id)}",
                "kind": FINANCIAL_STATEMENT,
                "subject": ctx.issuer_id(position_id),
                "observed_on": ctx.today.isoformat(),
                "values": statement,
                "attributes": {"standard": "management", "entered_by": ctx.author},
                "evidence": [],
            }
        )
    for item, value in market.values():
        kind, subject, value_name = item.market
        subject = subject.format(currency=row.get("currency", "RUB"))
        items.append(
            {
                "item_id": f"{kind}:{subject}:{position_id}",
                "kind": kind,
                "subject": subject,
                "observed_on": ctx.today.isoformat(),
                "values": {value_name: value},
                "attributes": {"entered_by": ctx.author},
                "evidence": [],
            }
        )
    return {
        "terms": terms,
        "params": {
            **params,
            "driver_elasticity": {},
            "proxy_peer_ids": [],
            "status": "ok",
            "flags": [],
        },
        "items": items,
        "schema_version": SCHEMA_VERSION,
    }
