"""The portfolio editor's form of an ordinary share, and how a typed row becomes data.

The share's terms (ticker, market index, sector) go to the instrument, the number of
shares to the position; the price, the exchange rate, the sensitivities and the dividends
the analyst types become items of the analyst's snapshot with the analyst as author.
"""

from msa.contracts.units import unit_price
from msa.plugin_sdk import EditorField, EditorGroup
from msa.plugins.market.fx import pair
from msa.plugins.market.kinds import FX_RATE, PRICE

from .schemas import DIVIDEND, MAX_RESIDUAL_VOLATILITY, SCHEMA_VERSION, SENSITIVITY
from .sectors import OKVED_SECTORS, SECTORS, sector_for_okved

EDITOR = (
    EditorGroup(
        "position",
        "Позиция",
        (
            EditorField(
                "quantity",
                "Количество акций",
                "position",
                unit="shares",
                required=True,
                minimum=0.0,
                hint="Число акций в позиции, в штуках. Укажите акции, а не биржевые лоты.",
            ),
        ),
    ),
    EditorGroup(
        "instrument",
        "Акция",
        (
            EditorField(
                "ticker",
                "Тикер",
                "terms",
                kind="text",
                required=True,
                hint="Биржевое обозначение акции, например SBER или SGZH.",
            ),
            EditorField(
                "market_index",
                "Рыночный индекс",
                "terms",
                kind="text",
                required=True,
                default="MOEX",
                options=(
                    ("MOEX", "Индекс МосБиржи (MOEX)"),
                    ("RTS", "Индекс РТС (RTS)"),
                    ("NDX", "Nasdaq-100 (NDX)"),
                    ("SPX", "S&P 500 (SPX)"),
                ),
                hint="Индекс, относительно которого оценена бета к рынку. Для российского "
                "рынка обычно MOEX. Выберите индекс или введите обозначение из вашей "
                "оценки чувствительности; в сценарии используется тот же индекс.",
            ),
            EditorField(
                "sector",
                "Отрасль для расчёта",
                "terms",
                kind="enum",
                required=True,
                options=SECTORS,
                derive_from="okved",
                derived_values=OKVED_SECTORS,
                hint="Подбирается по ОКВЭД эмитента. Это группа факторной модели, "
                "а не официальный отраслевой индекс. Если ваша оценка беты относится "
                "к другой отрасли, выберите её вручную. Изменение отрасли в сценарии "
                "учитывается сверх общего движения рынка.",
            ),
        ),
    ),
    EditorGroup(
        "market",
        "Цена и курс на дату оценки",
        (
            EditorField(
                "price",
                "Цена акции",
                f"snapshot:{PRICE}",
                unit="instrument_price",
                required=True,
                minimum=0.0,
                hint="Стоимость одной акции в единицах валюты инструмента, не в миллионах. "
                "Например, для цены 250 рублей введите 250. Стоимость всей позиции "
                "модель рассчитает по количеству акций.",
            ),
            EditorField(
                "fx_rate",
                "Курс валюты акции к базовой",
                f"snapshot:{FX_RATE}",
                unit="fx_quote",
                minimum=0.0,
                hint="Сколько единиц базовой валюты стоит одна единица валюты акции. "
                "Например, при USD/RUB = 92,5 введите 92,5. При одинаковых валютах "
                "курс равен 1 и вводить его не нужно.",
            ),
        ),
    ),
    EditorGroup(
        "sensitivity",
        "Чувствительности (экспертная оценка)",
        (
            EditorField(
                "beta_market",
                "Бета к рынку",
                f"snapshot:{SENSITIVITY}",
                unit="ratio",
                required=True,
                hint="Чувствительность цены к выбранному рыночному индексу. "
                "1 — движение на уровне рынка; 1,2 — примерно на 20% сильнее. "
                "Введите коэффициент из вашей оценки.",
            ),
            EditorField(
                "beta_sector",
                "Бета к отрасли",
                f"snapshot:{SENSITIVITY}",
                unit="ratio",
                required=True,
                hint="Чувствительность к изменению выбранной отрасли сверх общего рынка. "
                "1 — пропорциональная реакция, 0 — отраслевое влияние не учитывается.",
            ),
            EditorField(
                "residual_volatility",
                "Остаточная волатильность за год",
                f"snapshot:{SENSITIVITY}",
                unit="fraction",
                required=True,
                minimum=0.0,
                maximum=MAX_RESIDUAL_VOLATILITY,
                hint="Годовая волатильность, не объяснённая рынком и отраслью, в процентах. "
                "Для 20% введите 20. Значение 0 явно исключает остаточный риск.",
            ),
        ),
    ),
    EditorGroup(
        "dividend",
        "Дивиденды на горизонт",
        (
            EditorField(
                "dividend",
                "Дивиденды на акцию за горизонт",
                f"snapshot:{DIVIDEND}",
                unit="instrument_price",
                required=True,
                minimum=0.0,
                hint="Ожидаемая сумма дивидендов на одну акцию за 12 месяцев, "
                "в единицах валюты акции, не в миллионах. Введите 0, если выплат не ожидается.",
            ),
        ),
    ),
)


def from_draft(row: dict, ctx) -> dict:
    position_id = row["position_id"]
    instrument_id = ctx.instrument_id(position_id)
    currency = row.get("currency", "RUB")
    values = dict(row.get("values") or {})
    if not values.get("sector"):
        values["sector"] = sector_for_okved(row.get("okved"))
    if not values.get("market_index"):
        values["market_index"] = "MOEX"
    declared = {field.name for group in EDITOR for field in group.fields}
    unknown = sorted(set(values) - declared)
    if unknown:
        raise ValueError(f"{position_id}: unknown fields {unknown}")
    required = [f.name for g in EDITOR for f in g.fields if f.required]
    missing = [name for name in required if values.get(name) in (None, "")]
    if missing:
        raise ValueError(f"{position_id}: required fields {missing}")

    def parameter(name, unit, value=None):
        value = values[name] if value is None else value
        return {"value": value, "unit": unit, "evidence": ctx.evidence(position_id, name, value)}

    today = ctx.today.isoformat()
    terms = {
        "ticker": values["ticker"],
        "market_index": values["market_index"],
        "sector": values["sector"],
    }
    items = [
        {
            "item_id": f"{PRICE}:{instrument_id}",
            "kind": PRICE,
            "subject": instrument_id,
            "observed_on": today,
            "values": {"price": parameter("price", unit_price(currency))},
            "attributes": {"entered_by": ctx.author},
            "evidence": [],
        },
        {
            "item_id": f"{SENSITIVITY}:{instrument_id}",
            "kind": SENSITIVITY,
            "subject": instrument_id,
            "observed_on": today,
            "values": {
                "beta_market": parameter("beta_market", "ratio"),
                "beta_sector": parameter("beta_sector", "ratio"),
                "residual_volatility": parameter("residual_volatility", "fraction"),
            },
            "attributes": {
                "method": "expert",
                "market_index": terms["market_index"],
                "sector": terms["sector"],
                "entered_by": ctx.author,
            },
            "evidence": [],
        },
        {
            "item_id": f"{DIVIDEND}:{instrument_id}",
            "kind": DIVIDEND,
            "subject": instrument_id,
            "observed_on": today,
            "values": {"amount": parameter("dividend", unit_price(currency))},
            "attributes": {"horizon_months": 12, "entered_by": ctx.author},
            "evidence": [],
        },
    ]
    if currency != ctx.base_currency:
        if values.get("fx_rate") in (None, ""):
            raise ValueError(f"{position_id}: the rate of {currency} to {ctx.base_currency}")
        subject = pair(currency, ctx.base_currency)
        items.append(
            {
                "item_id": f"{FX_RATE}:{subject}:{today}",
                "kind": FX_RATE,
                "subject": subject,
                "observed_on": today,
                "values": {"rate": parameter("fx_rate", unit_price(ctx.base_currency))},
                "attributes": {"entered_by": ctx.author},
                "evidence": [],
            }
        )
    return {
        "terms": terms,
        "params": {"quantity": parameter("quantity", "shares"), "direction": "long"},
        "items": items,
        "schema_version": SCHEMA_VERSION,
    }
