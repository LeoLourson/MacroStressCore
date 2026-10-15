"""The common-sense checks: synthetic portfolios, synthetic events and what must follow.

Each check builds its portfolios and events, runs the whole line on them and compares the
numbers with what an analyst would expect without looking at the code: a bigger shock
hurts more, an untouched sector stays untouched, a doubled exposure doubles the loss, a
diversified book loses less in the tail than the sum of its parts. ``known`` ties a check to
an open methodological finding already listed in a plugin's README.
"""

import json
import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from demo import catalog
from msa.agents.causal import CausalAgent
from msa.contracts.causal_answer import sector_effects
from msa.engine.scenario_set import ScenarioSet, scenario_set_from_parameters
from msa.prompts.registry import current_version, get

from .build import Direct, Event, Link, loan, portfolio, share, shock
from .lab import (
    Verdict,
    close,
    decreasing,
    delta_el,
    equity_loss,
    fmt,
    increasing,
    metric,
    pd_base,
    pd_stress,
    recommendations,
    result,
    revenue_change,
    slice_item,
    slice_q,
    why_not_calculated,
)
from .line import AnalystGraph, LibraryIngest, TextIngest, run

REV, COGS, LOGISTICS, WC, RATE, CAPEX, FX = (
    "credit." + name
    for name in ("revenue", "cogs", "logistics", "working_capital", "interest", "capex", "fx")
)
CONCRETE, CEMENT, BUILDER, IT, MEAT, FARM = "23.61", "23.51", "41.20", "62.01", "10.11", "01.11"

GROUPS = {
    "A": "Кредит: направление и сила реакции",
    "B": "Граф передачи шока",
    "C": "Портфель и срезы",
    "D": "Акции",
    "E": "Облигации",
    "F": "Проектное финансирование",
    "G": "Лизинг",
    "H": "Рекомендации отчёта",
    "I": "Проверка входных данных",
    "S": "Сценарии-истории на диверсифицированной книге",
    "M": "Демо-каталог: события на своих портфелях",
}


@dataclass(frozen=True)
class Check:
    check_id: str
    title: str
    expectation: str
    portfolio: str
    event: str
    fn: Callable[[], Verdict]
    known: str | None = None

    @property
    def group(self) -> str:
        return self.check_id[0]


CHECKS: list[Check] = []


def check(check_id, title, expectation, *, portfolio, event, known=None):
    def register(fn):
        CHECKS.append(Check(check_id, title, expectation, portfolio, event, fn, known))
        return fn

    return register


def credit_event(
    event_id,
    factor=REV,
    *,
    okved=CONCRETE,
    value=None,
    low=None,
    mode=None,
    high=None,
    sign=1,
    lag=0,
    exposure=1.0,
    elasticity=1.0,
):
    """One channel to one sector moving one credit factor."""
    unit = "days" if factor == WC else "fraction"
    return Event(
        event_id,
        f"Синтетическое событие {event_id}: канал меняет фактор {factor} отрасли {okved}.",
        links=[
            Link(
                "channel",
                okved,
                factor,
                sign=sign,
                lag=lag,
                exposure=exposure,
                elasticity=elasticity,
            )
        ],
        scenario={
            "shock": shock("channel", factor, value=value, low=low, mode=mode, high=high, unit=unit)
        },
    )


def market_event(event_id, *shocks):
    """Direct shocks ``(factor, key, value)`` of market factors, each a point value."""
    return Event(
        event_id,
        f"Синтетическое рыночное событие {event_id}.",
        direct=[Direct("market", factor, key) for factor, key, _ in shocks],
        scenario={
            f"s{index}": shock(
                "market",
                factor,
                value=value,
                unit="log_return",
                key=key,
            )
            for index, (factor, key, value) in enumerate(shocks)
        },
    )


def preview(event, okved=CONCRETE) -> float | None:
    """The shock the analyst sees for ``okved`` at the graph stop (``sector_effects``)."""
    document = TextIngest().run({"text": event.text})
    graph = AnalystGraph(event).run_structured({"document": document.model_dump(mode="json")})
    effects = sector_effects(graph.graph.model_dump(mode="json"), event.scenario)
    found = [e["shock"] for e in effects if e["okved"] == okved]
    if len(found) > 1:
        raise ValueError("the preview of one parameter is expected")
    return found[0] if found else None


def one(rows, event, portfolio_id="P", **kw):
    bundle, snapshot = portfolio(portfolio_id, rows)
    return run(bundle, snapshot, event, **kw)


def numbers(pairs):
    return {str(k): v for k, v in pairs}


# A. Credit: direction and size ----------------------------------------------------------


@check(
    "A1",
    "Нулевой шок",
    "Выручка меняется на 0 %: ΔEL = 0, ΔPD = 0",
    portfolio="1 заёмщик 23.61 (EBITDA 1800, чистый долг 2,5×EBITDA, EAD 1000, LGD 0,45)",
    event="выручка 23.61: точечно 0 %",
)
def a1():
    o = one([loan("L", CONCRETE)], credit_event("A1", value=0.0))
    d, dpd = delta_el(o, "L"), metric(o, "L", "credit.delta_pd")
    ok = close(d, 0.0) and close(dpd, 0.0, abs_=1e-12)
    return Verdict(
        ok, f"ΔEL P50 = {fmt(d)}; ΔPD P50 = {fmt(dpd)}", {"delta_el": d, "delta_pd": dpd}
    )


@check(
    "A2",
    "Знак реакции",
    "Падение выручки на 10 % увеличивает ожидаемые потери, рост на 10 % — уменьшает",
    portfolio="1 заёмщик 23.61",
    event="выручка 23.61: −10 % и +10 % (точечно)",
)
def a2():
    down = delta_el(one([loan("L", CONCRETE)], credit_event("A2d", value=-0.10)), "L")
    up = delta_el(one([loan("L", CONCRETE)], credit_event("A2u", value=0.10)), "L")
    ok = down is not None and up is not None and down > 0 > up
    return Verdict(
        ok, f"ΔEL при −10 %: {fmt(down)}; при +10 %: {fmt(up)}", {"down": down, "up": up}
    )


@check(
    "A3",
    "Монотонность по силе шока",
    "Чем сильнее падение выручки (5, 10, 20, 30, 45 %), тем выше ΔEL",
    portfolio="1 заёмщик 23.61",
    event="выручка 23.61: −5, −10, −20, −30, −45 % (5 прогонов)",
)
def a3():
    shocks = [-0.05, -0.10, -0.20, -0.30, -0.45]
    values = [
        delta_el(one([loan("L", CONCRETE)], credit_event(f"A3{i}", value=v)), "L")
        for i, v in enumerate(shocks)
    ]
    table = numbers(zip(shocks, values, strict=True))
    return Verdict(increasing(values), "ΔEL: " + ", ".join(fmt(v) for v in values), table)


@check(
    "A4",
    "Каждый неблагоприятный драйвер увеличивает потери",
    "Выручка −10 %, себестоимость +10 %, логистика +10 %, оборотный капитал +30 дней, "
    "ставка +3 п.п., capex +20 %, валютный курс +20 %: у каждого ΔEL > 0",
    portfolio="1 заёмщик 23.61 (поддерживающий capex 600 в год, половина затрат — импорт)",
    event="7 событий, по одному на драйвер",
)
def a4():
    drivers = {
        REV: -0.10,
        COGS: 0.10,
        LOGISTICS: 0.10,
        WC: 30.0,
        RATE: 0.03,
        CAPEX: 0.20,
        FX: 0.20,
    }
    values = {}
    for index, (factor, value) in enumerate(drivers.items()):
        borrower = loan("L", CONCRETE, capex=600.0, import_share=0.5)
        o = one([borrower], credit_event(f"A4{index}", factor, value=value))
        values[factor] = delta_el(o, "L")
    bad = [f for f, v in values.items() if v is None or v <= 0]
    observed = "; ".join(f"{f.split('.')[1]}: {fmt(v)}" for f, v in values.items())
    return Verdict(not bad, observed + (f". Не выросли: {bad}" if bad else ""), values)


@check(
    "A5",
    "Рост ставки сильнее бьёт по закредитованному",
    "Ставка +3 п.п.: ΔEL у заёмщика с долгом 4,5×EBITDA больше, чем у заёмщика с 0,5×EBITDA",
    portfolio="2 заёмщика 23.61: чистый долг 900 и 8100",
    event="ставка по долгу 23.61: +3 п.п.",
)
def a5():
    event = credit_event("A5", RATE, value=0.03)
    o = one([loan("LO", CONCRETE, net_debt=900.0), loan("HI", CONCRETE, net_debt=8100.0)], event)
    low, high = delta_el(o, "LO"), delta_el(o, "HI")
    ok = low is not None and high is not None and high > low > 0
    return Verdict(ok, f"ΔEL 0,5×: {fmt(low)}; 4,5×: {fmt(high)}", {"low": low, "high": high})


@check(
    "A6",
    "Лестница долговой нагрузки",
    "При одном шоке (выручка −10 %) базовая PD и ΔEL растут с долгом/EBITDA 0,5→4,5",
    portfolio="5 заёмщиков 23.61: чистый долг 0,5; 1,5; 2,5; 3,5; 4,5 × EBITDA",
    event="выручка 23.61: −10 %",
)
def a6():
    multiples = [0.5, 1.5, 2.5, 3.5, 4.5]
    rows = [loan(f"L{i}", CONCRETE, net_debt=1800.0 * m) for i, m in enumerate(multiples)]
    o = one(rows, credit_event("A6", value=-0.10))
    base = [pd_base(o, f"L{i}") for i in range(len(multiples))]
    dels = [delta_el(o, f"L{i}") for i in range(len(multiples))]
    ok = increasing(base) and increasing(dels)
    observed = (
        "PD база: "
        + ", ".join(fmt(v, 3) for v in base)
        + "; ΔEL: "
        + ", ".join(fmt(v, 3) for v in dels)
    )
    return Verdict(ok, observed, {"multiples": multiples, "pd_base": base, "delta_el": dels})


@check(
    "A7",
    "Операционный рычаг",
    "При равных ICR и долг/EBITDA компания с тонкой маржой теряет больше от падения выручки",
    portfolio="4 заёмщика 23.61, маржа EBITDA 5, 10, 15, 25 %; долг и денежные средства "
    "пропорциональны EBITDA (ICR ≈ 2,6, долг/EBITDA 2,5 у всех)",
    event="выручка 23.61: −10 %",
)
def a7():
    margins = [0.05, 0.10, 0.15, 0.25]
    rows = []
    for index, margin in enumerate(margins):
        ebitda = 12000.0 * margin
        rows.append(
            loan(
                f"L{index}",
                CONCRETE,
                opex=1200.0,
                cogs=12000.0 - 1200.0 - ebitda,
                net_debt=2.5 * ebitda,
                cash=0.25 * ebitda,
            )
        )
    o = one(rows, credit_event("A7", value=-0.10))
    base = [pd_base(o, f"L{i}") for i in range(len(margins))]
    dels = [delta_el(o, f"L{i}") for i in range(len(margins))]
    ok = decreasing(dels)
    observed = (
        "PD база: "
        + ", ".join(fmt(v, 3) for v in base)
        + "; ΔEL: "
        + ", ".join(fmt(v, 3) for v in dels)
    )
    return Verdict(ok, observed, {"margins": margins, "pd_base": base, "delta_el": dels})


@check(
    "A8",
    "Перенос затрат в цену смягчает удар",
    "Себестоимость +10 %: ΔEL убывает с долей переноса в цену 0 → 0,5 → 1",
    portfolio="3 заёмщика 23.61, pass-through 0; 0,5; 1 (эластичность спроса −1)",
    event="себестоимость 23.61: +10 %",
)
def a8():
    shares = [0.0, 0.5, 1.0]
    rows = [loan(f"L{i}", CONCRETE, pass_through=s) for i, s in enumerate(shares)]
    o = one(rows, credit_event("A8", COGS, value=0.10))
    dels = [delta_el(o, f"L{i}") for i in range(len(shares))]
    return Verdict(
        decreasing(dels),
        "ΔEL: " + ", ".join(fmt(v) for v in dels),
        numbers(zip(shares, dels, strict=True)),
    )


@check(
    "A9",
    "Эластичный спрос не даёт переложить затраты",
    "Себестоимость +10 % при полном переносе в цену: ΔEL растёт с |эластичностью| 0,5 → 1 → 2",
    portfolio="3 заёмщика 23.61, pass-through 1, эластичность −0,5; −1; −2",
    event="себестоимость 23.61: +10 %",
)
def a9():
    elasticities = [-0.5, -1.0, -2.0]
    rows = [
        loan(f"L{i}", CONCRETE, pass_through=1.0, demand_elasticity=e)
        for i, e in enumerate(elasticities)
    ]
    o = one(rows, credit_event("A9", COGS, value=0.10))
    dels = [delta_el(o, f"L{i}") for i in range(len(elasticities))]
    return Verdict(
        increasing(dels),
        "ΔEL: " + ", ".join(fmt(v) for v in dels),
        numbers(zip(elasticities, dels, strict=True)),
    )


@check(
    "A10",
    "Потери пропорциональны EAD",
    "EAD 500 / 1000 / 2000 при том же заёмщике: ΔEL в отношении 1 : 2 : 4",
    portfolio="3 одинаковых заёмщика 23.61 с EAD 500, 1000, 2000",
    event="выручка 23.61: −10 %",
)
def a10():
    eads = [500.0, 1000.0, 2000.0]
    o = one(
        [loan(f"L{i}", CONCRETE, ead=e) for i, e in enumerate(eads)],
        credit_event("A10", value=-0.10),
    )
    dels = [delta_el(o, f"L{i}") for i in range(3)]
    ok = (
        all(v is not None for v in dels)
        and close(dels[1], 2 * dels[0])
        and close(dels[2], 4 * dels[0])
    )
    return Verdict(
        ok, "ΔEL: " + ", ".join(fmt(v) for v in dels), numbers(zip(eads, dels, strict=True))
    )


@check(
    "A11",
    "Потери пропорциональны LGD",
    "LGD 0,2 / 0,4 / 0,8: ΔEL в отношении 1 : 2 : 4",
    portfolio="3 одинаковых заёмщика 23.61 с LGD 0,2; 0,4; 0,8",
    event="выручка 23.61: −10 %",
)
def a11():
    lgds = [0.2, 0.4, 0.8]
    o = one(
        [loan(f"L{i}", CONCRETE, lgd=g) for i, g in enumerate(lgds)],
        credit_event("A11", value=-0.10),
    )
    dels = [delta_el(o, f"L{i}") for i in range(3)]
    ok = (
        all(v is not None for v in dels)
        and close(dels[1], 2 * dels[0])
        and close(dels[2], 4 * dels[0])
    )
    return Verdict(
        ok, "ΔEL: " + ", ".join(fmt(v) for v in dels), numbers(zip(lgds, dels, strict=True))
    )


@check(
    "A12",
    "Независимость от масштаба заёмщика",
    "Заёмщик ×10 по всем денежным показателям при той же EAD: те же PD и ΔEL",
    portfolio="2 заёмщика 23.61: базовый и ×10 (выручка, затраты, долг, деньги)",
    event="выручка 23.61: −10 %",
)
def a12():
    big = {
        k: 10 * v
        for k, v in {
            "revenue": 12000.0,
            "cogs": 8400.0,
            "opex": 1800.0,
            "net_debt": 4500.0,
            "cash": 500.0,
        }.items()
    }
    o = one([loan("S", CONCRETE), loan("B", CONCRETE, **big)], credit_event("A12", value=-0.10))
    ps, pb = pd_stress(o, "S"), pd_stress(o, "B")
    ds, db = delta_el(o, "S"), delta_el(o, "B")
    ok = close(ps, pb, rel=1e-6) and close(ds, db, rel=1e-6)
    return Verdict(
        ok,
        f"PD: {fmt(ps)} и {fmt(pb)}; ΔEL: {fmt(ds)} и {fmt(db)}",
        {"pd": [ps, pb], "delta_el": [ds, db]},
    )


@check(
    "A13",
    "Коэффициент кредитной конверсии (CCF)",
    "CCF 0,5 против 1: ΔEL меньше, либо результат явно говорит, что CCF не используется",
    portfolio="2 одинаковых заёмщика 23.61 с CCF 1 и 0,5",
    event="выручка 23.61: −10 %",
)
def a13():
    o = one(
        [loan("C1", CONCRETE, ccf=1.0), loan("C05", CONCRETE, ccf=0.5)],
        credit_event("A13", value=-0.10),
    )
    full, half = delta_el(o, "C1"), delta_el(o, "C05")
    flags = (result(o, "C05") or {}).get("flags", [])
    disclosed = any("ccf" in f for f in flags)
    ok = (full is not None and half is not None and half < full) or disclosed
    return Verdict(
        ok,
        f"ΔEL при CCF 1: {fmt(full)}; при CCF 0,5: {fmt(half)}; "
        f"флаги о CCF: {'есть' if disclosed else 'нет'}",
        {"ccf1": full, "ccf05": half},
    )


@check(
    "A14",
    "Доля импорта и валютный шок",
    "Курс +20 %: импортёр (доля импорта 0,8) теряет больше, чем компания без импорта, "
    "либо результат явно говорит, что доля импорта не учитывается",
    portfolio="2 одинаковых заёмщика 23.61 с долей импорта в затратах 0 и 0,8",
    event="валютный курс (credit.fx) 23.61: +20 %",
)
def a14():
    o = one(
        [loan("DOM", CONCRETE, import_share=0.0), loan("IMP", CONCRETE, import_share=0.8)],
        credit_event("A14", FX, value=0.20),
    )
    dom, imp = delta_el(o, "DOM"), delta_el(o, "IMP")
    flags = (result(o, "DOM") or {}).get("flags", [])
    disclosed = "fx_without_import_share" in flags
    ok = (dom is not None and imp is not None and imp > dom) or disclosed
    return Verdict(
        ok,
        f"ΔEL без импорта: {fmt(dom)}; импортёр: {fmt(imp)}; "
        f"флаг «шок курса без доли импорта» у заёмщика без импорта: "
        f"{'есть' if disclosed else 'нет'}",
        {"domestic": dom, "importer": imp},
    )


@check(
    "A15",
    "Убыточный заёмщик под новым шоком",
    "EBITDA < 0; выручка −10 %: потери растут (ΔEL > 0) или результат помечен как вырожденный "
    "(pd_at_model_maximum) и уходит на проверку",
    portfolio="1 заёмщик 23.61 с EBITDA −500 (себестоимость 10000, опер. расходы 2500)",
    event="выручка 23.61: −10 %",
)
def a15():
    o = one([loan("L", CONCRETE, cogs=10000.0, opex=2500.0)], credit_event("A15", value=-0.10))
    d, pb, ps = delta_el(o, "L"), pd_base(o, "L"), pd_stress(o, "L")
    item = result(o, "L") or {}
    marked = "pd_at_model_maximum" in item.get("flags", []) and item.get("status") in (
        "needs_review",
        "invalid",
    )
    ok = (d is not None and d > 0) or marked
    return Verdict(
        ok,
        f"PD база {fmt(pb)}, PD стресс {fmt(ps)}, ΔEL {fmt(d)}, статус {item.get('status')}; "
        f"флаги: {', '.join(item.get('flags', []))}",
        {"pd_base": pb, "pd_stress": ps, "delta_el": d},
    )


@check(
    "A16",
    "Заёмщик без долга",
    "Компания без процентного долга (чистые деньги 500) не должна получать PD выше, чем та "
    "же компания с небольшим долгом",
    portfolio="2 заёмщика 23.61: валовый долг 0 (чистый долг −500, деньги 500) и валовый "
    "долг 1000 (чистый долг −2000, деньги 3000)",
    event="выручка 23.61: −10 %",
)
def a16():
    o = one(
        [
            loan("NODEBT", CONCRETE, net_debt=-500.0, cash=500.0),
            loan("SMALL", CONCRETE, net_debt=-2000.0, cash=3000.0),
        ],
        credit_event("A16", value=-0.10),
    )
    none_, small = pd_base(o, "NODEBT"), pd_base(o, "SMALL")
    ok = none_ is not None and small is not None and none_ <= small
    flags = ", ".join((result(o, "NODEBT") or {}).get("flags", []))
    return Verdict(
        ok,
        f"PD база без долга: {fmt(none_)}; с долгом 1000: {fmt(small)}; флаги без долга: {flags}",
        {"no_debt": none_, "small_debt": small},
    )


@check(
    "A17",
    "Симметричный сценарий у заёмщика с ковенантом",
    "Выручка ±5 % с центром 0 (треуг. −5 / 0 / +5 %) считается и у заёмщика с ковенантом "
    "ICR ≥ 2: P5 ΔEL < 0 < P95",
    portfolio="2 одинаковых заёмщика 23.61: без ковенанта и с ковенантом ICR ≥ 2",
    event="выручка 23.61: треуг. −5 / 0 / +5 %",
)
def a17():
    covenant = [{"metric": "icr", "operator": "ge", "threshold": 2.0, "test_dates": ["2027-09-30"]}]
    o = one(
        [loan("FREE", CONCRETE), loan("COV", CONCRETE, covenants=covenant)],
        credit_event("A17", low=-0.05, mode=0.0, high=0.05),
    )
    spans = {p: (delta_el(o, p, "p05"), delta_el(o, p, "p95")) for p in ("FREE", "COV")}
    ok = all(low is not None and low < 0 < high for low, high in spans.values())
    item = result(o, "COV") or {}
    message = next((d["message"] for d in item.get("diagnostics") or []), "")
    return Verdict(
        ok,
        "без ковенанта: P5/P95 ΔEL "
        + "/".join(fmt(v) for v in spans["FREE"])
        + f"; с ковенантом: {item.get('execution')}/{item.get('status')} "
        + ", ".join(item.get("flags") or [])
        + (f" ({message.splitlines()[0]}: {message.splitlines()[2].strip()})" if message else ""),
        {"spans": spans},
    )


@check(
    "A18",
    "Потери ограничены сверху",
    "Выручка −90 %: PD ≤ 1 и ΔEL не больше LGD × EAD за вычетом базовых потерь",
    portfolio="1 заёмщик 23.61 (EAD 1000, LGD 0,45)",
    event="выручка 23.61: −90 %",
)
def a18():
    o = one([loan("L", CONCRETE)], credit_event("A18", value=-0.90))
    d95, ps = delta_el(o, "L", "p95"), pd_stress(o, "L")
    credit = ((result(o, "L") or {}).get("details") or {}).get("credit") or {}
    base_el = credit["expected_loss"] - credit["delta_expected_loss"] if credit else None
    cap = None if base_el is None else 0.45 * 1000.0 - base_el
    ok = d95 is not None and ps is not None and cap is not None and ps <= 1.0 and d95 <= cap
    return Verdict(
        ok,
        f"PD стресс {fmt(ps)}; ΔEL P95 {fmt(d95)}; предел LGD·EAD − EL базы = 450 − "
        f"{fmt(base_el)} = {fmt(cap)}",
        {"pd": ps, "delta_el_p95": d95, "base_el": base_el, "cap": cap},
    )


# B. Transmission graph -------------------------------------------------------------------


@check(
    "B1",
    "Изоляция отраслей",
    "Событие по 23.61 достигает только заёмщика 23.61; строительство, ИТ и мясопереработка "
    "не рассчитываются",
    portfolio="4 заёмщика: 23.61, 41.20, 62.01, 10.11",
    event="выручка 23.61: −10 %",
)
def b1():
    rows = [loan("CONC", CONCRETE), loan("BUILD", BUILDER), loan("IT", IT), loan("MEAT", MEAT)]
    o = one(rows, credit_event("B1", value=-0.10))
    return Verdict(o.reached == ["CONC"], f"достигнуты: {o.reached}", {"reached": o.reached})


@check(
    "B2",
    "Соседние классы ОКВЭД",
    "Узел отрасли 23.61 (бетонные изделия) не достигает 23.51 (цемент) и 23.99 — другие "
    "классы; если достигает, то с явной пометкой",
    portfolio="3 заёмщика: 23.61, 23.51, 23.99",
    event="выручка 23.61: −10 %",
)
def b2():
    rows = [loan("C2361", CONCRETE), loan("C2351", CEMENT), loan("C2399", "23.99")]
    o = one(rows, credit_event("B2", value=-0.10))
    shocks = {pid: revenue_change(o, pid) for pid in o.reached}
    ok = o.reached == ["C2361"]
    return Verdict(
        ok,
        f"достигнуты: {o.reached}; изменение выручки: "
        + ", ".join(f"{k} {fmt(v, 3)}" for k, v in shocks.items()),
        {"reached": o.reached, "revenue_change": shocks},
    )


@check(
    "B3",
    "Узел раздела ОКВЭД покрывает его классы",
    "Узел отрасли «23» достигает 23.61 и 23.51, но не 41.20",
    portfolio="3 заёмщика: 23.61, 23.51, 41.20",
    event="выручка раздела 23: −10 %",
)
def b3():
    rows = [loan("C2361", CONCRETE), loan("C2351", CEMENT), loan("BUILD", BUILDER)]
    o = one(rows, credit_event("B3", okved="23", value=-0.10))
    return Verdict(
        o.reached == ["C2351", "C2361"], f"достигнуты: {o.reached}", {"reached": o.reached}
    )


@check(
    "B4",
    "Доля воздействия канала на отрасль",
    "Ребро канал→отрасль с долей 0,25 / 0,5 / 1: выручка меняется на 0,9^доля − 1, ΔEL растёт",
    portfolio="1 заёмщик 23.61",
    event="выручка 23.61: −10 %, доля канала 0,25; 0,5; 1 (3 прогона)",
)
def b4():
    shares = [0.25, 0.5, 1.0]
    outs = [
        one([loan("L", CONCRETE)], credit_event(f"B4{i}", value=-0.10, exposure=s))
        for i, s in enumerate(shares)
    ]
    changes = [revenue_change(o, "L") for o in outs]
    dels = [delta_el(o, "L") for o in outs]
    expected = [0.9**s - 1 for s in shares]
    ok = increasing(dels) and all(
        close(c, e, rel=1e-6) for c, e in zip(changes, expected, strict=True)
    )
    return Verdict(
        ok,
        "выручка: "
        + ", ".join(fmt(c, 4) for c in changes)
        + " (ожидалось "
        + ", ".join(fmt(e, 4) for e in expected)
        + "); ΔEL: "
        + ", ".join(fmt(v, 3) for v in dels),
        {"shares": shares, "revenue_change": changes, "delta_el": dels},
    )


@check(
    "B5",
    "Запаздывание эффекта",
    "Лаг 0 / 3 / 6 / 9 / 12 мес. при горизонте 12: ΔEL убывает; лаг 12 — эффекта в горизонте нет",
    portfolio="1 заёмщик 23.61",
    event="выручка 23.61: −20 % с лагом на ребре отрасль→фактор (5 прогонов)",
)
def b5():
    lags = [0, 3, 6, 9, 12]
    dels = [
        delta_el(one([loan("L", CONCRETE)], credit_event(f"B5{i}", value=-0.20, lag=g)), "L")
        for i, g in enumerate(lags)
    ]
    ok = (
        decreasing(dels[:-1])
        and dels[-1] is not None
        and dels[-2] > dels[-1]
        and close(dels[-1], 0.0)
    )
    return Verdict(
        ok, "ΔEL: " + ", ".join(fmt(v, 3) for v in dels), numbers(zip(lags, dels, strict=True))
    )


@check(
    "B6",
    "Два способа записать «продажи упадут на 35 %»",
    "Канал «продажи» −35 % со знаком +1 даёт падение выручки на 35 %. Запись «падение продаж» "
    "+35 % со знаком −1 означает обратную зависимость (1/1,35 − 1): предпросмотр аналитика "
    "показывает то же число, что расчёт, а промпт каузального агента требует первой записи",
    portfolio="1 заёмщик 23.61",
    event="(а) −0,35, знак +1; (б) +0,35, знак −1",
)
def b6():
    ea = credit_event("B6a", value=-0.35, sign=1)
    eb = credit_event("B6b", value=0.35, sign=-1)
    a, b = one([loan("L", CONCRETE)], ea), one([loan("L", CONCRETE)], eb)
    ra, rb = revenue_change(a, "L"), revenue_change(b, "L")
    da, db = delta_el(a, "L"), delta_el(b, "L")
    pa, pb = preview(ea), preview(eb)
    asks_for_a = "Never use sign -1 to express a fall" in get("causal")
    ok = (
        ra is not None
        and abs(ra + 0.35) < 0.005
        and close(pa, ra, rel=1e-6)
        and close(pb, rb, rel=1e-6)
        and asks_for_a
    )
    return Verdict(
        ok,
        f"выручка (а) {fmt(ra, 4)}, (б) {fmt(rb, 4)}; ΔEL (а) {fmt(da, 4)}, (б) {fmt(db, 4)}; "
        f"предпросмотр аналитика: (а) {fmt(pa, 4)}, (б) {fmt(pb, 4)}; промпт "
        f"{current_version('causal')} требует записи (а): {'да' if asks_for_a else 'нет'}",
        {"revenue_a": ra, "revenue_b": rb, "delta_el_a": da, "delta_el_b": db},
    )


@check(
    "B7",
    "Два канала складываются как один",
    "Два параметра по −5 % на разных каналах к одной отрасли = один параметр −9,75 % (0,95² − 1)",
    portfolio="1 заёмщик 23.61",
    event="(а) каналы c1 и c2 по −5 %; (б) один канал −9,75 %",
)
def b7():
    two = Event(
        "B7a",
        "Два независимых механизма снижают выручку производителей бетонных изделий.",
        links=[Link("c1", CONCRETE, REV), Link("c2", CONCRETE, REV)],
        scenario={"s1": shock("c1", REV, value=-0.05), "s2": shock("c2", REV, value=-0.05)},
    )
    a = one([loan("L", CONCRETE)], two)
    b = one([loan("L", CONCRETE)], credit_event("B7b", value=0.95**2 - 1))
    ra, rb = revenue_change(a, "L"), revenue_change(b, "L")
    da, db = delta_el(a, "L"), delta_el(b, "L")
    ok = close(ra, rb, rel=1e-9) and close(da, db, rel=1e-9)
    return Verdict(
        ok,
        f"выручка (а) {fmt(ra, 5)}, (б) {fmt(rb, 5)}; ΔEL (а) {fmt(da, 5)}, (б) {fmt(db, 5)}",
        {"revenue": [ra, rb], "delta_el": [da, db]},
    )


@check(
    "B8",
    "Лишние отрасли в графе не усиливают шок",
    "Один узел фактора «выручка», в который входят рёбра от 23.61, 41.20 и 46.63, даёт "
    "заёмщику 23.61 тот же шок −10 %, что и отдельные узлы по отраслям",
    portfolio="1 заёмщик 23.61",
    event="выручка −10 % на отрасли 23.61, 41.20, 46.63: (а) узел фактора на каждую отрасль; "
    "(б) общий узел фактора",
)
def b8():
    def event(event_id, shared):
        return Event(
            event_id,
            "Падение спроса на стройматериалы, строительство и оптовую торговлю техникой.",
            links=[
                Link("demand", code, REV, shared_factor=shared)
                for code in (CONCRETE, BUILDER, "46.63")
            ],
            scenario={"shock": shock("demand", REV, value=-0.10)},
        )

    ea, eb = event("B8a", False), event("B8b", True)
    a, b = one([loan("L", CONCRETE)], ea), one([loan("L", CONCRETE)], eb)
    ra, rb = revenue_change(a, "L"), revenue_change(b, "L")
    ok = close(ra, rb, rel=1e-6)
    return Verdict(
        ok,
        f"выручка 23.61: отдельные узлы {fmt(ra, 4)}, общий узел {fmt(rb, 4)}; "
        f"ΔEL {fmt(delta_el(a, 'L'), 4)} и {fmt(delta_el(b, 'L'), 4)}; "
        f"предпросмотр аналитика: {fmt(preview(ea), 4)} и {fmt(preview(eb), 4)}",
        {"separate": ra, "shared": rb},
    )


@check(
    "B9",
    "Событие мимо портфеля",
    "Событие по сельскому хозяйству (01.11) не затрагивает портфель: прогон завершается, "
    "позиций с расчётом нет, потерь в срезах нет",
    portfolio="2 заёмщика: 23.61, 62.01",
    event="выручка 01.11: −20 %",
)
def b9():
    o = one([loan("CONC", CONCRETE), loan("IT", IT)], credit_event("B9", okved=FARM, value=-0.20))
    losses = {k: v.get("loss_quantiles") for k, v in (o.portfolio or {}).get("slices", {}).items()}
    finished = o.error is None and not o.blocked
    ok = finished and not o.reached and not any(losses.values())
    stage = o.stage if finished else why_not_calculated(o, "CONC")
    return Verdict(
        ok, f"этап: {stage}; достигнуты: {o.reached}; срезы: {list(losses)}", {"reached": o.reached}
    )


@check(
    "B10",
    "Неопределённость эластичности ребра",
    "Эластичность отрасль→фактор задана треугольным распределением (0,5; 1; 1,5): разброс "
    "P5–P95 шире, чем при точечной эластичности 1",
    portfolio="1 заёмщик 23.61",
    event="выручка 23.61: точечно −10 %; эластичность ребра (а) 1, (б) треуг. 0,5–1–1,5",
)
def b10():
    a = one([loan("L", CONCRETE)], credit_event("B10a", value=-0.10, elasticity=1.0))
    b = one([loan("L", CONCRETE)], credit_event("B10b", value=-0.10, elasticity=(0.5, 1.0, 1.5)))
    wa = delta_el(a, "L", "p95") - delta_el(a, "L", "p05")
    wb = delta_el(b, "L", "p95") - delta_el(b, "L", "p05")
    return Verdict(
        wb > wa,
        f"ширина P5–P95 ΔEL: точечная {fmt(wa)}, треугольная {fmt(wb)}",
        {"point": wa, "triangular": wb},
    )


@check(
    "B11",
    "Шок −100 % и ниже",
    "Выручка −100 % или −150 % не считается молча: сценарий отклоняется на остановке "
    "аналитика или позиция не рассчитывается с понятной причиной",
    portfolio="1 заёмщик 23.61",
    event="выручка 23.61: точечно −100 % и −150 %",
)
def b11():
    observed, ok = [], True
    for value in (-1.0, -1.5):
        try:
            o = one([loan("L", CONCRETE)], credit_event(f"B11{value}", value=value))
        except Exception as exc:  # noqa: BLE001 - the reason is the observation
            observed.append(f"{value:+.0%}: исключение {type(exc).__name__}: {str(exc)[:120]}")
            ok = False
            continue
        calculated = result(o, "L") is not None and result(o, "L")["execution"] == "completed"
        if calculated:
            ok = False
        if calculated:
            observed.append(f"{value:+.0%}: рассчитано, ΔEL {fmt(delta_el(o, 'L'))}")
            continue
        item = result(o, "L") or {}
        message = next((d["message"] for d in item.get("diagnostics") or []), "")
        stop = "отклонён на остановке" if o.blocked else "принят на остановке аналитика"
        observed.append(f"{value:+.0%}: сценарий {stop}; {why_not_calculated(o, 'L')} ({message})")
    return Verdict(ok, "; ".join(observed))


@check(
    "B12",
    "Единица сценария не совпадает с фактором",
    "Шок выручки в днях вместо доли отклоняется на остановке аналитика",
    portfolio="1 заёмщик 23.61",
    event="выручка 23.61: 30 (unit=days)",
)
def b12():
    event = credit_event("B12", value=30.0)
    event.scenario["shock"]["unit"] = "days"
    o = one([loan("L", CONCRETE)], event)
    ok = bool(o.blocked) and result(o, "L") is None
    return Verdict(ok, why_not_calculated(o, "L"))


# C. Portfolio and slices ------------------------------------------------------------------


@check(
    "C1",
    "Один общий фактор — нет диверсификации",
    "Три одинаковых заёмщика под одним шоком: P50 и P95 среза равны сумме по позициям",
    portfolio="3 одинаковых заёмщика 23.61",
    event="выручка 23.61: треуг. −15 / −10 / −5 %",
)
def c1():
    o = one(
        [loan(f"L{i}", CONCRETE) for i in range(3)],
        credit_event("C1", low=-0.15, mode=-0.10, high=-0.05),
    )
    p95 = [delta_el(o, f"L{i}", "p95") for i in range(3)]
    p50 = [delta_el(o, f"L{i}", "p50") for i in range(3)]
    s95, s50 = slice_q(o, "credit.loss", "p95"), slice_q(o, "credit.loss", "p50")
    ok = close(s95, sum(p95), rel=1e-9) and close(s50, sum(p50), rel=1e-9)
    return Verdict(
        ok,
        f"P95 среза {fmt(s95, 6)} при сумме {fmt(sum(p95), 6)}; "
        f"P50 {fmt(s50, 6)} при сумме {fmt(sum(p50), 6)}",
        {"slice_p95": s95, "sum_p95": sum(p95)},
    )


@check(
    "C2",
    "Дробление позиции",
    "EAD 1000 одной позицией и двумя позициями 600 + 400 по одинаковым заёмщикам дают один срез",
    portfolio="(а) 1 заёмщик EAD 1000; (б) 2 одинаковых заёмщика EAD 600 и 400",
    event="выручка 23.61: треуг. −15 / −10 / −5 %",
)
def c2():
    event = credit_event("C2", low=-0.15, mode=-0.10, high=-0.05)
    a = one([loan("L", CONCRETE)], event, "C2a")
    b = one([loan("L1", CONCRETE, ead=600.0), loan("L2", CONCRETE, ead=400.0)], event, "C2b")
    qa = [slice_q(a, "credit.loss", q) for q in ("p05", "p50", "p95")]
    qb = [slice_q(b, "credit.loss", q) for q in ("p05", "p50", "p95")]
    ok = all(close(x, y, rel=1e-9) for x, y in zip(qa, qb, strict=True))
    return Verdict(
        ok,
        "P5/P50/P95: " + "/".join(fmt(v) for v in qa) + " и " + "/".join(fmt(v) for v in qb),
        {"one": qa, "split": qb},
    )


@check(
    "C3",
    "Незатронутая позиция не меняет потери",
    "Добавление заёмщика из ИТ к портфелю не меняет срез кредитных потерь",
    portfolio="(а) заёмщик 23.61; (б) тот же + заёмщик 62.01",
    event="выручка 23.61: треуг. −15 / −10 / −5 %",
)
def c3():
    event = credit_event("C3", low=-0.15, mode=-0.10, high=-0.05)
    a = one([loan("L", CONCRETE)], event, "C3a")
    b = one([loan("L", CONCRETE), loan("IT", IT)], event, "C3b")
    pa, pb = slice_q(a, "credit.loss"), slice_q(b, "credit.loss")
    return Verdict(close(pa, pb, rel=1e-12), f"P95: {fmt(pa, 8)} и {fmt(pb, 8)}", {"p95": [pa, pb]})


@check(
    "C4",
    "Концентрация и охват по всему портфелю",
    "В портфеле 5 равных заёмщиков, событие задевает одного: HHI описывает портфель (0,2), "
    "а срез говорит, что событие затронуло 20 % портфеля",
    portfolio="5 равных заёмщиков: 23.61, 41.20, 62.01, 10.11, 46.71",
    event="выручка 23.61: −10 %",
)
def c4():
    rows = [loan(f"L{i}", code) for i, code in enumerate((CONCRETE, BUILDER, IT, MEAT, "46.71"))]
    o = one(rows, credit_event("C4", value=-0.10))
    item = slice_item(o, "credit.loss") or {}
    coverage = item.get("coverage") or {}
    hhi, covered = item.get("herfindahl"), coverage.get("covered_share")
    share = coverage.get("portfolio_share")
    return Verdict(
        close(hhi, 0.2) and close(share, 0.2),
        f"HHI {fmt(hhi)}; охват расчётом {fmt(covered)}; доля затронутого портфеля {fmt(share)}; "
        f"достигнуты {o.reached}",
        {"herfindahl": hhi, "covered_share": covered, "portfolio_share": share},
    )


@check(
    "C5",
    "Воспроизводимость и порядок позиций",
    "Повторный прогон и перестановка позиций дают те же числа",
    portfolio="3 заёмщика 23.61 с разным долгом; во втором прогоне в обратном порядке",
    event="выручка 23.61: треуг. −15 / −10 / −5 %",
)
def c5():
    rows = [loan(f"L{i}", CONCRETE, net_debt=1800.0 * m) for i, m in enumerate((1.0, 2.5, 4.0))]
    event = credit_event("C5", low=-0.15, mode=-0.10, high=-0.05)
    a, b, c = one(rows, event, "C5"), one(rows, event, "C5"), one(list(reversed(rows)), event, "C5")
    values = [
        [delta_el(o, f"L{i}", "p95") for i in range(3)] + [slice_q(o, "credit.loss")]
        for o in (a, b, c)
    ]
    ok = values[0] == values[1] == values[2]
    return Verdict(
        ok,
        "P95 по позициям и срезу: "
        + " | ".join(", ".join(fmt(v, 8) for v in row) for row in values),
        {"runs": values},
    )


@check(
    "C6",
    "Устойчивость к зерну",
    "Зёрна 1, 101, 20260911: P95 среза отличается меньше чем на 1 %",
    portfolio="1 заёмщик 23.61",
    event="выручка 23.61: треуг. −30 / −10 / 0 %",
)
def c6():
    event = credit_event("C6", low=-0.30, mode=-0.10, high=0.0)
    seeds = (1, 101, 20260911)
    values = [
        slice_q(one([loan("L", CONCRETE)], event, seed=seed), "credit.loss") for seed in seeds
    ]
    spread = (max(values) - min(values)) / max(values)
    return Verdict(
        spread < 0.01,
        "P95: " + ", ".join(fmt(v, 6) for v in values) + f"; разброс {spread:.3%}",
        {"p95": values, "spread": spread},
    )


@check(
    "C7",
    "Выигравшие и проигравшие в одном срезе",
    "Шоки −10 % для 23.61 и +10 % для 10.11: P50 среза = сумма ΔEL (точечные шоки), "
    "отрицательный вклад не теряется",
    portfolio="2 заёмщика: 23.61, 10.11",
    event="два канала: выручка 23.61 −10 %, выручка 10.11 +10 %",
)
def c7():
    event = Event(
        "C7",
        "Спрос переключается с бетонных изделий на продукты питания.",
        links=[Link("down", CONCRETE, REV), Link("up", MEAT, REV)],
        scenario={"down": shock("down", REV, value=-0.10), "up": shock("up", REV, value=0.10)},
    )
    o = one([loan("CONC", CONCRETE), loan("MEAT", MEAT)], event)
    a, b = delta_el(o, "CONC"), delta_el(o, "MEAT")
    s = slice_q(o, "credit.loss", "p50")
    ok = a is not None and b is not None and a > 0 > b and close(s, a + b, rel=1e-9)
    return Verdict(
        ok,
        f"ΔEL 23.61 {fmt(a)}, 10.11 {fmt(b)}, P50 среза {fmt(s)}",
        {"conc": a, "meat": b, "slice": s},
    )


@check(
    "C8",
    "Соседние зёрна дают независимые выборки",
    "Прогоны с зерном s и s + 1 — два независимых повтора: их реплики Соболя не совпадают",
    portfolio="1 заёмщик 23.61 (для C8 прогон линии — зёрна 1 и 2; выборка — функцией ядра)",
    event="выручка 23.61: треуг. −30 / −10 / 0 %",
)
def c8():
    parameters = {"shock": credit_event("C8", low=-0.30, mode=-0.10, high=0.0).scenario["shock"]}
    scenario = scenario_set_from_parameters(parameters, points=1024, replicates=8)
    first, second = scenario.sample(1), scenario.sample(2)
    shared = sum(any((a == b).all() for b in second.replicates) for a in first.replicates)
    event = credit_event("C8", low=-0.30, mode=-0.10, high=0.0)
    p95 = [slice_q(one([loan("L", CONCRETE)], event, seed=seed), "credit.loss") for seed in (1, 2)]
    return Verdict(
        shared == 0,
        f"общих реплик у зёрен 1 и 2: {shared} из 8; "
        f"P95 среза: {fmt(p95[0], 10)} и {fmt(p95[1], 10)}",
        {"shared_replicates": shared, "p95": p95},
    )


@check(
    "C9",
    "Акция эмитента, которого задело событие",
    "Кредитное событие по 23.61 затрагивает и акцию эмитента 23.61; без заданного шока акции "
    "система не должна молча считать её убыток нулевым",
    portfolio="заёмщик 23.61 и акция эмитента 23.61",
    event="выручка 23.61: −10 % (шока рынка и отрасли для акций нет)",
)
def c9():
    o = one(
        [loan("L", CONCRETE), share("S", CONCRETE, beta_sector=1.0)],
        credit_event("C9", value=-0.10),
    )
    calculated = result(o, "S") is not None and result(o, "S")["execution"] == "completed"
    loss = equity_loss(o, "S")
    ok = not (calculated and close(loss, 0.0))
    observed = (
        why_not_calculated(o, "S")
        if not calculated
        else f"акция рассчитана, потеря {fmt(loss)}; флаги {result(o, 'S')['flags']}"
    )
    return Verdict(ok, observed)


# D. Equities ------------------------------------------------------------------------------

MOEX = ("equity.market", "MOEX")


@check(
    "D1",
    "Акция: нулевой шок",
    "Рынок 0, остаточный риск 0, дивидендов нет: потеря ровно 0",
    portfolio="1 акция (1 млн шт. по 100 ₽, β=1)",
    event="MOEX: 0",
)
def d1():
    o = one([share("S", CONCRETE)], market_event("D1", (*MOEX, 0.0)))
    loss = [equity_loss(o, "S", q) for q in ("p05", "p50", "p95")]
    return Verdict(
        all(close(v, 0.0) for v in loss), "потеря P5/P50/P95: " + "/".join(fmt(v) for v in loss)
    )


@check(
    "D2",
    "Лестница беты",
    "MOEX −10 %: потеря = 1 − 0,9^β от стоимости (β = 0; 0,5; 1; 2)",
    portfolio="4 акции по 100 млн ₽ с β 0; 0,5; 1; 2",
    event="MOEX: ln 0,9",
)
def d2():
    betas = [0.0, 0.5, 1.0, 2.0]
    rows = [share(f"S{i}", CONCRETE, beta_market=b) for i, b in enumerate(betas)]
    o = one(rows, market_event("D2", (*MOEX, math.log(0.9))))
    losses = [equity_loss(o, f"S{i}") for i in range(len(betas))]
    expected = [100.0 * (1 - 0.9**b) for b in betas]
    ok = all(close(x, y, rel=1e-9, abs_=1e-9) for x, y in zip(losses, expected, strict=True))
    return Verdict(
        ok,
        "потеря, млн ₽: "
        + ", ".join(fmt(v) for v in losses)
        + " (ожидалось "
        + ", ".join(fmt(v) for v in expected)
        + ")",
        numbers(zip(betas, losses, strict=True)),
    )


@check(
    "D3",
    "Изоляция рыночных индексов",
    "Шок S&P 500 не затрагивает акцию, бета которой оценена к MOEX",
    portfolio="акция MOEX (RUB) и акция SPX (USD, курс 92,5)",
    event="SPX: −20 %",
)
def d3():
    rows = [
        share("RU", CONCRETE),
        share(
            "US",
            IT,
            currency="USD",
            fx_rate=92.5,
            price=1.0,
            market_index="SPX",
            sector="technology",
        ),
    ]
    o = one(rows, market_event("D3", ("equity.market", "SPX", math.log(0.8))))
    ru = equity_loss(o, "RU")
    ok = "RU" not in o.reached or close(ru, 0.0)
    return Verdict(
        ok,
        f"достигнуты {o.reached}; потеря RU {fmt(ru)}, US {fmt(equity_loss(o, 'US'))}",
        {"reached": o.reached},
    )


@check(
    "D4",
    "Изоляция отраслевого фактора",
    "Шок отрасли «нефть и газ» задевает нефтяную акцию и не задевает ИТ-акцию",
    portfolio="акция 06.10 (oil_gas, β отрасли 1) и акция 62.01 (technology)",
    event="канал «акции нефтегаза» → отрасль 06.10 → фактор отрасли: −15 %",
)
def d4():
    rows = [share("OIL", "06.10", beta_sector=1.0), share("TECH", IT, beta_sector=1.0)]
    event = Event(
        "D4",
        "Синтетическое событие D4: акции нефтегазовых компаний дешевеют сильнее рынка.",
        links=[Link("oil_shares", "06.10", "equity.sector")],
        scenario={"oil": shock("oil_shares", "equity.sector", value=-0.15)},
    )
    o = one(rows, event)
    oil = equity_loss(o, "OIL")
    ok = close(oil, 15.0, rel=1e-9) and "TECH" not in o.reached
    return Verdict(
        ok,
        f"достигнуты {o.reached}; потеря OIL {fmt(oil)} млн ₽ (ожидалось 15)",
        {"reached": o.reached, "oil": oil},
    )


@check(
    "D5",
    "Потеря пропорциональна количеству",
    "2 млн акций теряют вдвое больше, чем 1 млн",
    portfolio="2 одинаковые акции по 1 и 2 млн шт.",
    event="MOEX: ln 0,9",
)
def d5():
    o = one(
        [share("A", CONCRETE, ticker="A1"), share("B", CONCRETE, ticker="B1", quantity=2_000_000)],
        market_event("D5", (*MOEX, math.log(0.9))),
    )
    a, b = equity_loss(o, "A"), equity_loss(o, "B")
    return Verdict(close(b, 2 * a), f"потеря {fmt(a)} и {fmt(b)}", {"one": a, "two": b})


@check(
    "D6",
    "Валютная переоценка",
    "Долларовая акция: USD/RUB +10 % при нулевом рынке даёт рублёвый доход 10 % стоимости; "
    "рублёвая акция не затронута",
    portfolio="акция SPX (USD, 1 млн шт. по 1 $, курс 92,5) и рублёвая акция MOEX",
    event="USD/RUB: ln 1,1",
)
def d6():
    rows = [
        share(
            "US",
            IT,
            currency="USD",
            fx_rate=92.5,
            price=1.0,
            market_index="SPX",
            sector="technology",
        ),
        share("RU", CONCRETE),
    ]
    o = one(rows, market_event("D6", ("market.fx", "USD/RUB", math.log(1.1))))
    value = metric(o, "US", "equity.value_current", "value")
    loss = equity_loss(o, "US")
    ok = close(value, 92.5, rel=1e-9) and close(loss, -9.25, rel=1e-9) and "RU" not in o.reached
    return Verdict(
        ok,
        f"стоимость US {fmt(value)} млн ₽, потеря {fmt(loss)} (ожидалось −9,25); "
        f"достигнуты {o.reached}",
        {"value": value, "loss": loss},
    )


@check(
    "D7",
    "Рынок и курс вместе",
    "SPX −10 % и USD/RUB +10 %: рублёвая стоимость долларовой акции (β=1) меняется на "
    "0,9·1,1 − 1 = −1 %",
    portfolio="акция SPX (USD, курс 92,5)",
    event="SPX: ln 0,9; USD/RUB: ln 1,1",
)
def d7():
    o = one(
        [
            share(
                "US",
                IT,
                currency="USD",
                fx_rate=92.5,
                price=1.0,
                market_index="SPX",
                sector="technology",
            )
        ],
        market_event(
            "D7", ("equity.market", "SPX", math.log(0.9)), ("market.fx", "USD/RUB", math.log(1.1))
        ),
    )
    loss = equity_loss(o, "US")
    return Verdict(
        close(loss, 0.925, rel=1e-9), f"потеря {fmt(loss)} млн ₽ (ожидалось 0,925)", {"loss": loss}
    )


@check(
    "D8",
    "Остаточный риск",
    "σ = 30 % в год при нулевых факторах: P95 потери ≈ 1 − e^(−1,645·0,3) ≈ 38,9 % стоимости",
    portfolio="1 акция на 100 млн ₽, σ = 0,3",
    event="MOEX: 0",
)
def d8():
    o = one([share("S", CONCRETE, residual=0.3)], market_event("D8", (*MOEX, 0.0)))
    p95 = equity_loss(o, "S", "p95")
    expected = 100.0 * (1 - math.exp(-1.6448536 * 0.3))
    return Verdict(
        p95 is not None and abs(p95 - expected) < 0.5,
        f"P95 потери {fmt(p95)} млн ₽ (ожидалось {fmt(expected)})",
        {"p95": p95, "expected": expected},
    )


@check(
    "D9",
    "Диверсификация остаточного риска",
    "Две разные акции с σ = 30 %: P95 среза заметно меньше суммы P95 (для нормальных "
    "независимых ≈ 1/√2)",
    portfolio="2 разные акции по 100 млн ₽, σ = 0,3",
    event="MOEX: 0",
)
def d9():
    rows = [
        share("A", CONCRETE, ticker="AAA", residual=0.3),
        share("B", MEAT, ticker="BBB", residual=0.3),
    ]
    o = one(rows, market_event("D9", (*MOEX, 0.0)))
    total = slice_q(o, "market.pnl")
    parts = [equity_loss(o, p, "p95") for p in ("A", "B")]
    ratio = total / sum(parts)
    return Verdict(
        ratio < 0.85,
        f"P95 среза {fmt(total)}; сумма P95 {fmt(sum(parts))}; отношение {ratio:.3f}",
        {"ratio": ratio},
    )


@check(
    "D10",
    "Одна и та же бумага двумя строками",
    "Две позиции одной акции (тикер AAA) должны двигаться вместе: P95 среза = сумма P95",
    portfolio="2 строки редактора с одним тикером AAA по 100 млн ₽, σ = 0,3",
    event="MOEX: 0",
)
def d10():
    rows = [
        share("A1", CONCRETE, ticker="AAA", residual=0.3),
        share("A2", CONCRETE, ticker="AAA", residual=0.3),
    ]
    o = one(rows, market_event("D10", (*MOEX, 0.0)))
    total = slice_q(o, "market.pnl")
    parts = [equity_loss(o, p, "p95") for p in ("A1", "A2")]
    ratio = total / sum(parts)
    return Verdict(
        ratio > 0.99,
        f"P95 среза {fmt(total)}; сумма P95 {fmt(sum(parts))}; отношение {ratio:.3f}",
        {"ratio": ratio},
    )


@check(
    "D11",
    "Дивиденды входят в результат",
    "Нулевой шок, дивиденд 5 ₽ на акцию ценой 100 ₽: доход 5 % стоимости (потеря −5 млн ₽)",
    portfolio="1 акция, 1 млн шт. по 100 ₽, дивиденд 5 ₽",
    event="MOEX: 0",
)
def d11():
    o = one([share("S", CONCRETE, dividend=5.0)], market_event("D11", (*MOEX, 0.0)))
    loss = equity_loss(o, "S")
    return Verdict(close(loss, -5.0), f"потеря {fmt(loss)} млн ₽", {"loss": loss})


def _per_replicate_corr(x, y, replicates=8) -> list[float]:
    x = np.asarray(x, dtype=float).reshape(replicates, -1)
    y = np.asarray(y, dtype=float).reshape(replicates, -1)
    return [float(np.corrcoef(x[r], y[r])[0, 1]) for r in range(replicates)]


@check(
    "D12",
    "Остаточные шоки разных акций независимы",
    "Две разные акции, только остаточный риск (σ = 30 %): корреляция их потерь в каждой из 8 "
    "реплик близка к нулю (|ρ| ≤ 0,15 при 1024 точках; случайный разброс ≈ 0,03)",
    portfolio="2 разные акции (AAA 23.61, BBB 10.11) по 100 млн ₽, σ = 0,3",
    event="MOEX: 0",
)
def d12():
    rows = [
        share("A", CONCRETE, ticker="AAA", residual=0.3),
        share("B", MEAT, ticker="BBB", residual=0.3),
    ]
    o = one(rows, market_event("D12", (*MOEX, 0.0)))
    corr = _per_replicate_corr(o.draws["A"]["market.pnl"], o.draws["B"]["market.pnl"])
    pooled = float(np.corrcoef(o.draws["A"]["market.pnl"], o.draws["B"]["market.pnl"])[0, 1])
    ok = max(abs(c) for c in corr) <= 0.15
    return Verdict(
        ok,
        "ρ по репликам: "
        + ", ".join(f"{c:+.2f}" for c in corr)
        + f"; по всем точкам {pooled:+.3f}",
        {"per_replicate": corr, "pooled": pooled},
    )


@check(
    "D13",
    "Остаточный шок не зависит от рынка",
    "Рынок MOEX случаен (треуг. ln 0,8 / 0 / ln 1,2), β = 1, σ = 30 %: остаток "
    "ε = ln(V_T/V_0) − β·f_m не коррелирует с f_m (|ρ| ≤ 0,15 в каждой реплике)",
    portfolio="1 акция 23.61 на 100 млн ₽, β = 1, σ = 0,3",
    event="MOEX: треуг. ln 0,8 / 0 / ln 1,2",
)
def d13():
    event = Event(
        "D13",
        "Рынок акций колеблется в пределах ±20 %.",
        direct=[Direct("market", "equity.market", "MOEX")],
        scenario={
            "moex": shock(
                "market",
                "equity.market",
                low=math.log(0.8),
                mode=0.0,
                high=math.log(1.2),
                unit="log_return",
                key="MOEX",
            )
        },
    )
    o = one([share("A", CONCRETE, ticker="AAA", residual=0.3)], event)
    loss = np.asarray(o.draws["A"]["market.pnl"], dtype=float)
    spec = o.scenario
    market = ScenarioSet.from_spec(spec["spec"]).sample(spec["seed"]).stacked("moex").reshape(-1)
    residual = np.log(1.0 - loss / 100.0) - market
    corr = _per_replicate_corr(market, residual)
    pooled = float(np.corrcoef(market, residual)[0, 1])
    ok = max(abs(c) for c in corr) <= 0.15
    return Verdict(
        ok,
        "ρ(f_m, ε) по репликам: "
        + ", ".join(f"{c:+.2f}" for c in corr)
        + f"; по всем точкам {pooled:+.3f}; σ(ε) = {residual.std():.4f}",
        {"per_replicate": corr, "pooled": pooled},
    )


# E. Bonds -----------------------------------------------------------------------------------

BOND = {"face_value": 1000.0, "coupon_rate": 0.16, "maturity_months": 36.0, "risk_free_rate": 0.14}


@check(
    "E1",
    "Облигация дешевеет при ухудшении эмитента",
    "Выручка эмитента −20 %: цена позиции падает (P50 изменения < 0), ΔEL > 0",
    portfolio="облигация с фикс. купоном 16 %, 3 года, номинал 1000, безрисковая 14 %",
    event="выручка 23.61: −20 %",
)
def e1():
    o = one([loan("B", CONCRETE, kind="bond_fixed", **BOND)], credit_event("E1", value=-0.20))
    price = metric(o, "B", "credit.position_price_change")
    d = delta_el(o, "B")
    ok = price is not None and price < 0 and d is not None and d > 0
    return Verdict(
        ok,
        f"изменение цены P50 {fmt(price)} млн ₽; ΔEL {fmt(d)}; "
        f"статус {(result(o, 'B') or {}).get('status')}",
        {"price_change": price, "delta_el": d},
    )


@check(
    "E2",
    "Процентный риск фиксированного купона",
    "Рост ставок на 3 п.п.: облигация с фиксированным купоном дешевеет сильнее флоатера",
    portfolio="фикс. купон и флоатер одного эмитента, те же условия",
    event="ставка по долгу 23.61: +3 п.п. (credit.interest; другого фактора ставки нет)",
)
def e2():
    rows = [
        loan("FIX", CONCRETE, kind="bond_fixed", **BOND),
        loan("FLT", CONCRETE, kind="bond_floater", **BOND),
    ]
    o = one(rows, credit_event("E2", RATE, value=0.03))
    fixed, floater = (metric(o, p, "credit.position_price_change") for p in ("FIX", "FLT"))
    ok = fixed is not None and floater is not None and fixed < floater
    return Verdict(
        ok,
        f"изменение цены P50: фикс {fmt(fixed)}, флоатер {fmt(floater)} млн ₽",
        {"fixed": fixed, "floater": floater},
    )


# F. Project finance -------------------------------------------------------------------------

PROJECT = {
    "credit_limit": 6000.0,
    "equity": 0.0,
    "capex_month_1_12": 100.0,
    "monthly_sales": 330.0,
    "base_rate": 0.2,
    "commissioning_month": 12.0,
    "debt": 3980.3715,
    "escrow": 1980.0,
    "sales_start_month": 1.0,
}


def project(position_id="PF", **values):
    return loan(
        position_id, BUILDER, kind="pf_escrow", ead=6000.0, lgd=0.35, **{**PROJECT, **values}
    )


@check(
    "F1",
    "Проект: падение продаж",
    "Продажи −10 / −20 / −30 %: ΔEL растёт, покрытие долга эскроу падает",
    portfolio="застройщик 41.20, стройка на 12-м месяце из 24, долг 3980, эскроу 1980",
    event="выручка (объём продаж) 41.20: −10, −20, −30 %",
)
def f1():
    shocks = [-0.10, -0.20, -0.30]
    outs = [
        one([project()], credit_event(f"F1{i}", okved=BUILDER, value=v))
        for i, v in enumerate(shocks)
    ]
    dels = [delta_el(o, "PF") for o in outs]
    cover = [metric(o, "PF", "credit.escrow_coverage") for o in outs]
    ok = increasing(dels) and decreasing(cover)
    return Verdict(
        ok,
        "ΔEL: "
        + ", ".join(fmt(v) for v in dels)
        + "; покрытие P50: "
        + ", ".join(fmt(v) for v in cover),
        {"delta_el": dels, "coverage": cover},
    )


@check(
    "F2",
    "Проект: перерасход и ставка",
    "Capex +20 % и ставка +3 п.п. по отдельности увеличивают ΔEL",
    portfolio="тот же застройщик 41.20",
    event="capex 41.20: +20 %; ставка 41.20: +3 п.п.",
)
def f2():
    capex = delta_el(one([project()], credit_event("F2c", CAPEX, okved=BUILDER, value=0.20)), "PF")
    rate = delta_el(one([project()], credit_event("F2r", RATE, okved=BUILDER, value=0.03)), "PF")
    ok = capex is not None and rate is not None and capex > 0 and rate > 0
    return Verdict(
        ok, f"ΔEL capex {fmt(capex)}; ставка {fmt(rate)}", {"capex": capex, "rate": rate}
    )


# G. Leasing ---------------------------------------------------------------------------------

LESSOR = {
    "net_investment_leases": 40000.0,
    "new_business": 18000.0,
    "debt": 33000.0,
    "equity": 8000.0,
    "portfolio_yield": 0.25,
    "amortization_rate": 0.35,
    "borrowing_rate": 0.18,
    "opex": 1200.0,
    "advance_rate": 0.2,
    "tax_rate": 0.25,
}


@check(
    "G1",
    "Лизинг: дорогое фондирование",
    "Ставка фондирования +3 п.п.: ΔEL > 0; результат с пометкой о непокрытых потерях "
    "лизингополучателей входит в срез по правилу включения",
    portfolio="лизинговая компания 64.91 (портфель 40000, долг 33000, капитал 8000)",
    event="ставка 64.91: +3 п.п.",
    known="credit README, находка 3 (ECL лизингополучателей не моделируется)",
)
def g1():
    o = one(
        [loan("LS", "64.91", kind="leasing", ead=2000.0, lgd=0.4, **LESSOR)],
        credit_event("G1", RATE, okved="64.91", value=0.03),
    )
    d = delta_el(o, "LS")
    item = slice_item(o, "credit.loss") or {}
    ok = d is not None and d > 0 and "LS" in item.get("included", [])
    return Verdict(
        ok,
        f"ΔEL {fmt(d)}; статус {(result(o, 'LS') or {}).get('status')}; "
        f"в срезе: {item.get('included')}; флаги среза: {item.get('flags')}",
        {"delta_el": d},
    )


@check(
    "G2",
    "Лизинг: рост операционных расходов",
    "Операционные расходы лизингодателя +20 % (фактор себестоимости): ΔEL > 0",
    portfolio="та же лизинговая компания",
    event="себестоимость 64.91: +20 %",
)
def g2():
    o = one(
        [loan("LS", "64.91", kind="leasing", ead=2000.0, lgd=0.4, **LESSOR)],
        credit_event("G2", COGS, okved="64.91", value=0.20),
    )
    d = delta_el(o, "LS")
    return Verdict(d is not None and d > 0, f"ΔEL {fmt(d)}", {"delta_el": d})


# H. Report recommendations ---------------------------------------------------------------


@check(
    "H1",
    "Нет шока — нет рекомендаций",
    "Нулевой шок: отчёт не предлагает действий",
    portfolio="1 заёмщик 23.61",
    event="выручка 23.61: 0 %",
)
def h1():
    o = one([loan("L", CONCRETE)], credit_event("H1", value=0.0))
    recs = recommendations(o)
    return Verdict(not recs and o.report is not None, f"рекомендации: {recs or 'нет'}")


@check(
    "H2",
    "Лёгкий шок — наблюдение",
    "Выручка −5 % у здорового заёмщика: только «список наблюдения» (R5)",
    portfolio="1 заёмщик 23.61 (долг 2,5×EBITDA)",
    event="выручка 23.61: −5 %",
)
def h2():
    recs = recommendations(one([loan("L", CONCRETE)], credit_event("H2", value=-0.05)))
    return Verdict(recs == ["credit.R5:watchlist"], f"рекомендации: {recs}")


@check(
    "H3",
    "Тяжёлый шок — жёсткие меры",
    "Выручка −40 % у заёмщика с долгом 4,5×EBITDA: реструктуризация (ICR < 1) и/или "
    "сокращение лимита (ΔPD ≥ 5 п.п.), а не только наблюдение",
    portfolio="1 заёмщик 23.61 (долг 4,5×EBITDA)",
    event="выручка 23.61: −40 %",
)
def h3():
    o = one([loan("L", CONCRETE, net_debt=8100.0)], credit_event("H3", value=-0.40))
    recs = recommendations(o)
    icr = metric(o, "L", "credit.icr")
    dpd = metric(o, "L", "credit.delta_pd")
    ok = any(r.endswith(("restructure", "limit_cut")) for r in recs)
    return Verdict(
        ok,
        f"рекомендации: {recs}; ICR P50 {fmt(icr)}; ΔPD P50 {fmt(dpd)}",
        {"icr": icr, "delta_pd": dpd},
    )


@check(
    "H4",
    "Улучшение — без мер",
    "Выручка +10 %: ни одной рекомендации",
    portfolio="1 заёмщик 23.61",
    event="выручка 23.61: +10 %",
)
def h4():
    recs = recommendations(one([loan("L", CONCRETE)], credit_event("H4", value=0.10)))
    return Verdict(not recs, f"рекомендации: {recs or 'нет'}")


@check(
    "H5",
    "Ковенант под шоком",
    "Ковенант ICR ≥ 2 в конце горизонта: при выручке −1 % вероятность нарушения 0; при "
    "−20 % она высокая и срабатывает R2 (нулевой шок здесь не берётся: см. A17)",
    portfolio="1 заёмщик 23.61 (ICR ≈ 2,6) с ковенантом ICR ≥ 2 на 2027-09-30",
    event="выручка 23.61: −1 % и треуг. −25 / −20 / −15 %",
)
def h5():
    covenant = [{"metric": "icr", "operator": "ge", "threshold": 2.0, "test_dates": ["2027-09-30"]}]
    calm = one([loan("L", CONCRETE, covenants=covenant)], credit_event("H5a", value=-0.01))
    hit = one(
        [loan("L", CONCRETE, covenants=covenant)],
        credit_event("H5b", low=-0.25, mode=-0.20, high=-0.15),
    )

    def breach(o):
        details = (result(o, "L") or {}).get("details") or {}
        return max((c["breach_probability"] for c in details.get("covenants", [])), default=None)

    b0, b1 = breach(calm), breach(hit)
    recs = recommendations(hit)
    ok = b0 == 0 and b1 is not None and b1 >= 0.5 and "credit.R2:covenant_talks" in recs
    return Verdict(
        ok,
        f"вероятность нарушения: {fmt(b0)} и {fmt(b1)}; рекомендации при шоке: {recs}",
        {"calm": b0, "hit": b1},
    )


# I. Input checks --------------------------------------------------------------------------


def _rejected(rows, event) -> tuple[bool, str]:
    """Whether the system refuses the input with a reason instead of calculating it."""
    try:
        o = one(rows, event)
    except Exception as exc:  # noqa: BLE001 - the refusal is the observation
        return True, f"отказ при вводе: {str(exc).splitlines()[0][:160]}"
    pid = rows[0]["position_id"]
    item = result(o, pid)
    if item is None or item["execution"] != "completed":
        return True, why_not_calculated(o, pid)
    return False, "рассчитано; флаги: " + (", ".join(item.get("flags") or []) or "нет")


@check(
    "I1",
    "LGD больше 1",
    "LGD = 1,5 отклоняется",
    portfolio="1 заёмщик 23.61 с LGD 1,5",
    event="выручка 23.61: −10 %",
)
def i1():
    ok, text = _rejected([loan("L", CONCRETE, lgd=1.5)], credit_event("I1", value=-0.10))
    return Verdict(ok, text)


@check(
    "I2",
    "Отрицательная EAD",
    "EAD = −100 отклоняется",
    portfolio="1 заёмщик 23.61 с EAD −100",
    event="выручка 23.61: −10 %",
)
def i2():
    ok, text = _rejected([loan("L", CONCRETE, ead=-100.0)], credit_event("I2", value=-0.10))
    return Verdict(ok, text)


@check(
    "I3",
    "Остаточная волатильность в процентах вместо доли",
    "σ = 20 (то есть 2000 % в год, типичная ошибка «20 вместо 0,2» при вызове API) "
    "отклоняется или помечается",
    portfolio="1 акция, residual_volatility = 20",
    event="MOEX: 0",
)
def i3():
    ok, text = _rejected([share("S", CONCRETE, residual=20.0)], market_event("I3", (*MOEX, 0.0)))
    if not ok:
        o = one([share("S", CONCRETE, residual=20.0)], market_event("I3b", (*MOEX, 0.0)))
        text += (
            f"; потеря P5 {fmt(equity_loss(o, 'S', 'p05'))}, P50 {fmt(equity_loss(o, 'S'))}, "
            f"P95 {fmt(equity_loss(o, 'S', 'p95'))} при стоимости 100 млн ₽"
        )
    return Verdict(ok, text)


@check(
    "I4",
    "Доля переноса затрат больше 1",
    "pass_through = 1,5 отклоняется или позиция не рассчитывается с причиной",
    portfolio="1 заёмщик 23.61 с pass_through 1,5",
    event="себестоимость 23.61: +10 %",
)
def i4():
    ok, text = _rejected(
        [loan("L", CONCRETE, pass_through=1.5)], credit_event("I4", COGS, value=0.10)
    )
    return Verdict(ok, text)


@check(
    "I5",
    "Положительная эластичность спроса",
    "demand_elasticity = +1 отклоняется или явно заменяется с пометкой",
    portfolio="1 заёмщик 23.61 с эластичностью +1",
    event="себестоимость 23.61: +10 %",
)
def i5():
    rows = [loan("L", CONCRETE, demand_elasticity=1.0, pass_through=0.5)]
    ok, text = _rejected(rows, credit_event("I5", COGS, value=0.10))
    if not ok and "demand_elasticity_missing_or_invalid" in text:
        ok = True
    return Verdict(ok, text)


# S. Story events on one diversified book -----------------------------------------------

#: Position id -> (label, what it is), for the tables of the report.
BOOK_LABELS = {
    "CONC": "бетонные изделия 23.61, кредит, долг 2,5×EBITDA",
    "CEM": "цемент 23.51, кредит, долг 1×EBITDA",
    "DEV": "застройщик 41.20, проектное финансирование с эскроу",
    "DIST": "дистрибьютор спецтехники 46.63, импорт 80 % затрат",
    "FERT": "экспортёр удобрений 20.15, кредит",
    "LEASE": "лизинговая компания 64.91",
    "ITC": "ИТ-компания 62.01, почти без долга",
    "BOND": "облигация производителя 23.61, фикс. купон 16 %",
    "S_BANK": "акция банка 64.19, β 1,1, σ 25 %",
    "S_OIL": "акция нефтяной компании 06.10, β 0,9, σ 30 %, дивиденд 8 %",
    "S_DEVS": "акция девелопера 41.20, β 1,3, β отрасли 1, σ 35 %",
    "S_US": "американская ИТ-акция (USD, SPX), β 1,2, σ 30 %",
}


def book():
    """A diversified synthetic bank book: eight credit positions and four shares."""
    return [
        loan("CONC", CONCRETE, ead=1000.0),
        loan("CEM", CEMENT, ead=800.0, net_debt=1800.0),
        project("DEV"),
        loan(
            "DIST",
            "46.63",
            ead=3000.0,
            import_share=0.8,
            revenue=20000.0,
            cogs=16000.0,
            opex=2000.0,
            net_debt=6000.0,
            cash=500.0,
            borrowing_rate=0.1333,
            dio=90.0,
            pass_through=0.8,
            demand_elasticity=-1.25,
        ),
        loan(
            "FERT",
            "20.15",
            ead=1500.0,
            revenue=30000.0,
            cogs=18000.0,
            opex=4000.0,
            net_debt=12000.0,
            cash=1000.0,
        ),
        loan("LEASE", "64.91", kind="leasing", ead=2000.0, lgd=0.4, **LESSOR),
        loan("ITC", IT, ead=300.0, revenue=5000.0, cogs=2000.0, opex=2000.0, net_debt=500.0),
        loan("BOND", CONCRETE, kind="bond_fixed", ead=1000.0, lgd=0.6, name="Эмитент B", **BOND),
        share("S_BANK", "64.19", ticker="BANK", beta_market=1.1, residual=0.25),
        share("S_OIL", "06.10", ticker="OIL", beta_market=0.9, residual=0.3, dividend=8.0),
        share("S_DEVS", BUILDER, ticker="DEVS", beta_market=1.3, beta_sector=1.0, residual=0.35),
        share(
            "S_US",
            IT,
            ticker="USTECH",
            currency="USD",
            fx_rate=92.5,
            price=1.0,
            market_index="SPX",
            sector="technology",
            beta_market=1.2,
            residual=0.3,
        ),
    ]


def table(o) -> dict:
    """Per position: reached, P50 ΔEL (and per unit of EAD) or P50 equity loss per value."""
    rows = {}
    for pid in BOOK_LABELS:
        item = result(o, pid)
        row = {"reached": pid in o.reached}
        if item is not None and item["execution"] == "completed":
            if pid.startswith("S_"):
                value = metric(o, pid, "equity.value_current", "value")
                loss = equity_loss(o, pid)
                row.update(loss_p50=loss, loss_share=None if not value else loss / value)
            else:
                ead = metric(o, pid, "credit.ead", "value")
                d = delta_el(o, pid)
                row.update(delta_el_p50=d, per_ead=None if d is None else d / ead)
        elif item is not None:
            row["not_calculated"] = why_not_calculated(o, pid)
        rows[pid] = row
    rows["_slices"] = {
        k: (v.get("loss_quantiles") or {}).get("p50")
        for k, v in (o.portfolio or {}).get("slices", {}).items()
    }
    return rows


def describe(rows) -> str:
    parts = []
    for pid, row in rows.items():
        if pid == "_slices":
            continue
        if not row["reached"]:
            continue
        if "per_ead" in row:
            parts.append(
                f"{pid} ΔEL {fmt(row['delta_el_p50'], 3)} ({fmt(100 * row['per_ead'], 3)} % EAD)"
            )
        elif "loss_share" in row:
            parts.append(f"{pid} потеря {fmt(100 * row['loss_share'], 3)} %")
        else:
            parts.append(f"{pid} не рассчитана")
    untouched = [pid for pid, row in rows.items() if pid != "_slices" and not row["reached"]]
    return "; ".join(parts) + f". Не достигнуты: {', '.join(untouched) or 'нет'}"


def story(event_id, text, links, direct, scenario):
    return Event(event_id, text, links=links, direct=direct, scenario=scenario)


CREDIT_SECTORS = (CONCRETE, CEMENT, BUILDER, "46.63", "20.15", "64.91", IT)


@check(
    "S1",
    "Ключевая ставка +5 п.п.",
    "Все кредитные позиции теряют (ΔEL ≥ 0); у бетонного производителя (2,5×) потери на "
    "единицу EAD выше, чем у цементного (1×); акции с β > 0 теряют; ИТ-компания почти без "
    "долга теряет меньше всех корпоративных заёмщиков",
    portfolio="диверсифицированная книга: 8 кредитных позиций и 4 акции",
    event="ставка +5 п.п. всем отраслям книги; MOEX −10 %; SPX 0 (аналитик задаёт явно)",
)
def s1():
    event = story(
        "S1",
        "Банк России повысил ключевую ставку на 5 п.п.; рынок акций снизился на 10 %.",
        [Link("rate", code, RATE) for code in CREDIT_SECTORS],
        [Direct("rate", "equity.market", "MOEX"), Direct("rate", "equity.market", "SPX")],
        {
            "rate": shock("rate", RATE, value=0.05),
            "moex": shock(
                "rate", "equity.market", value=math.log(0.9), unit="log_return", key="MOEX"
            ),
            "spx": shock("rate", "equity.market", value=0.0, unit="log_return", key="SPX"),
        },
    )
    o = one(book(), event, "S1")
    rows = table(o)
    credit = ("CONC", "CEM", "DIST", "FERT", "ITC", "BOND", "DEV", "LEASE")
    ok = (
        all((rows[p].get("delta_el_p50") or -1) >= 0 for p in credit)
        and rows["CONC"]["per_ead"] > rows["CEM"]["per_ead"]
        and all(rows[p]["loss_share"] > 0 for p in ("S_BANK", "S_OIL", "S_DEVS"))
        and rows["ITC"]["per_ead"]
        <= min(rows[p]["per_ead"] for p in ("CONC", "CEM", "DIST", "FERT"))
    )
    return Verdict(ok, describe(rows), rows)


@check(
    "S2",
    "Девальвация рубля на 25 %",
    "Импортёр теряет (ΔEL > 0), экспортёр выигрывает (ΔEL < 0), долларовая акция дорожает "
    "в рублях на 25 %; заёмщики вне графа не затронуты",
    portfolio="та же книга",
    event="канал «курс»: валютные затраты 46.63 +25 %, выручка 20.15 +25 %; USD/RUB +25 %; SPX 0",
)
def s2():
    event = story(
        "S2",
        "Рубль ослаб к доллару на 25 %: импорт дорожает, экспортная выручка растёт.",
        [Link("fx", "46.63", FX), Link("fx", "20.15", REV)],
        [Direct("fx", "market.fx", "USD/RUB"), Direct("fx", "equity.market", "SPX")],
        {
            "fx_costs": shock("fx", FX, value=0.25),
            "fx_revenue": shock("fx", REV, value=0.25),
            "usd": shock("fx", "market.fx", value=math.log(1.25), unit="log_return", key="USD/RUB"),
            "spx": shock("fx", "equity.market", value=0.0, unit="log_return", key="SPX"),
        },
    )
    o = one(book(), event, "S2")
    rows = table(o)
    value = metric(o, "S_US", "equity.value_current", "value")
    central = metric(o, "S_US", "equity.loss", "value")
    us = None if value is None or central is None else central / value
    ok = (
        (rows["DIST"].get("delta_el_p50") or 0) > 0
        and (rows["FERT"].get("delta_el_p50") or 0) < 0
        and close(us, -0.25, rel=1e-6)
        and not any(rows[p]["reached"] for p in ("CONC", "CEM", "DEV", "ITC", "LEASE", "BOND"))
    )
    return Verdict(ok, describe(rows) + f"; центральная потеря S_US {fmt(100 * us, 4)} %", rows)


@check(
    "S3",
    "Ужесточение ипотеки",
    "Застройщик (продажи −35 %) и производители стройматериалов теряют; бетон (эластичность "
    "0,3, долг 2,5×) теряет на единицу EAD больше цемента (0,15, долг 1×); акция девелопера "
    "падает; ИТ, дистрибьютор, экспортёр, лизинг не затронуты",
    portfolio="та же книга",
    event="канал «ипотека» −35 %: 41.20 эластичность 1, 23.61 — 0,3, 23.51 — 0,15; канал "
    "«акции девелоперов» → 41.20: −20 %",
)
def s3():
    event = story(
        "S3",
        "Требования к первоначальному взносу по льготной ипотеке ужесточены.",
        [
            Link("mortgage", BUILDER, REV),
            Link("mortgage", CONCRETE, REV, elasticity=0.3),
            Link("mortgage", CEMENT, REV, elasticity=0.15),
            Link("developer_shares", BUILDER, "equity.sector"),
        ],
        [],
        {
            "housing": shock("mortgage", REV, value=-0.35),
            "developers": shock("developer_shares", "equity.sector", value=-0.2),
        },
    )
    o = one(book(), event, "S3")
    rows = table(o)
    ok = (
        all((rows[p].get("delta_el_p50") or 0) > 0 for p in ("DEV", "CONC", "CEM"))
        and rows["CONC"]["per_ead"] > rows["CEM"]["per_ead"]
        and (rows["S_DEVS"].get("loss_share") or 0) > 0
        and not any(rows[p]["reached"] for p in ("ITC", "DIST", "FERT", "LEASE"))
    )
    return Verdict(ok, describe(rows), rows)


@check(
    "S4",
    "Утилизационный сбор на спецтехнику",
    "Дистрибьютор спецтехники (закупка +10 %, расчёты +45 дней) теряет; лизинг — по своей "
    "модели; строители, производители, экспортёр, ИТ и акции не затронуты, и аналитика не "
    "просят задавать для них шоки",
    portfolio="та же книга",
    event="канал «сбор»: себестоимость 46.63 +10 %; канал «расчёты»: оборотный капитал 46.63 "
    "+45 дней; канал «лизинг»: выручка (новый бизнес) 64.91 −8 %",
)
def s4():
    event = story(
        "S4",
        "Введён утилизационный сбор на спецтехнику; расчёты через посредников удлинились.",
        [
            Link("fee", "46.63", COGS),
            Link("payments", "46.63", WC),
            Link("leasing", "64.91", REV),
        ],
        [],
        {
            "fee": shock("fee", COGS, value=0.10),
            "delay": shock("payments", WC, value=45.0, unit="days"),
            "leasing": shock("leasing", REV, value=-0.08),
        },
    )
    first = one(book(), event, "S4")
    # The analyst answers the stop the only way the platform accepts: an explicit zero for
    # the factors of the position the graph points at, here the bank's sector.
    event.links.append(Link("leasing", "64.19", "equity.sector"))
    event.scenario["banks"] = shock("leasing", "equity.sector", value=0.0)
    o = one(book(), event, "S4")
    rows = table(o)
    untouched = ("CONC", "CEM", "DEV", "FERT", "ITC", "BOND", "S_OIL", "S_DEVS", "S_US")
    reached_extra = [p for p in untouched if rows[p]["reached"]]
    ok = (rows["DIST"].get("delta_el_p50") or 0) > 0 and not reached_extra and not first.blocked
    observed = (
        "первый прогон остановлен: " + why_not_calculated(first, "S_BANK") + " После нуля для "
        "отрасли банка: "
        if first.blocked
        else ""
    ) + describe(rows)
    return Verdict(ok, observed, rows)


@check(
    "S5",
    "Обвал рынка акций",
    "MOEX −25 %, SPX −20 %, USD/RUB +10 %: рублёвые акции теряют тем больше, чем выше β "
    "(девелопер 1,3 > банк 1,1 > нефть 0,9); долларовая: 1 − 0,8^1,2·1,1 ≈ 15,8 %; кредитные "
    "позиции не рассчитываются, среза кредитных потерь нет",
    portfolio="та же книга",
    event="MOEX ln 0,75; SPX ln 0,8; USD/RUB ln 1,1 (без кредитных каналов)",
)
def s5():
    event = story(
        "S5",
        "Распродажа на рынках акций.",
        [],
        [
            Direct("markets", "equity.market", "MOEX"),
            Direct("markets", "equity.market", "SPX"),
            Direct("markets", "market.fx", "USD/RUB"),
        ],
        {
            "moex": shock(
                "markets", "equity.market", value=math.log(0.75), unit="log_return", key="MOEX"
            ),
            "spx": shock(
                "markets", "equity.market", value=math.log(0.8), unit="log_return", key="SPX"
            ),
            "usd": shock(
                "markets", "market.fx", value=math.log(1.1), unit="log_return", key="USD/RUB"
            ),
        },
    )
    o = one(book(), event, "S5")
    rows = table(o)
    central = {
        pid: metric(o, pid, "equity.loss", "value")
        / metric(o, pid, "equity.value_current", "value")
        for pid in ("S_DEVS", "S_BANK", "S_OIL", "S_US")
        if result(o, pid) is not None
    }
    ok = (
        len(central) == 4
        and central["S_DEVS"] > central["S_BANK"] > central["S_OIL"]
        and close(central["S_US"], 1 - 0.8**1.2 * 1.1, rel=1e-6)
        and "credit.loss" not in (o.portfolio or {}).get("slices", {})
    )
    observed = (
        describe(rows)
        + "; центральные потери: "
        + ", ".join(f"{k} {fmt(100 * v, 3)} %" for k, v in central.items())
    )
    return Verdict(ok, observed, {**rows, "central": central})


# M. The demo catalog ------------------------------------------------------------------------
#
# Each library event runs on the portfolio it was prepared for, through the demo stand's own
# mock profile: the causal step answers with the event's prepared graph and scenario
# (``mock_answer``), held to the portfolio's factors as an LLM's answer is. What must follow
# is written in the event's ``expect``: who loses, who gains, who is reached with a sign
# common sense cannot tell, who is not reached at all.

EXPECTED = {
    "loses": "теряют",
    "gains": "выигрывают",
    "reached": "затронуты",
    "unaffected": "не затронуты",
}


def position_loss(outcome, position_id):
    """The median loss of a position over the run's realisations; positive is a loss."""
    draws = outcome.draws.get(position_id) or {}
    return float(sum(np.median(series) for series in draws.values())) if draws else None


def library_check(event):
    expect, portfolio_id = event["expect"], event["metadata"]["portfolio_id"]

    def fn():
        bundle = catalog.bundle(portfolio_id)
        o = run(
            bundle,
            catalog.snapshot(bundle.portfolio.snapshot_id),
            Event(event["event_id"], event["text"]),
            ingest=LibraryIngest(),
            causal=CausalAgent(mock=True),
        )
        if o.error or o.blocked:
            return Verdict(None, why_not_calculated(o, ""))
        losses = {pid: position_loss(o, pid) for pid in o.reached}
        problems = []
        for pid in expect.get("loses", []):
            if not (losses.get(pid) is not None and losses[pid] > 0):
                problems.append(f"{pid} не теряет ({why(o, pid, losses)})")
        for pid in expect.get("gains", []):
            if not (losses.get(pid) is not None and losses[pid] < 0):
                problems.append(f"{pid} не выигрывает ({why(o, pid, losses)})")
        for pid in expect.get("reached", []):
            if losses.get(pid) is None:
                problems.append(f"{pid} не рассчитана ({why(o, pid, losses)})")
        for pid in expect.get("unaffected", []):
            if pid in o.reached:
                problems.append(f"{pid} затронута")
        shown = ", ".join(f"{pid} {fmt(value)}" for pid, value in sorted(losses.items()))
        observed = ("; ".join(problems) + ". " if problems else "") + "Медиана потерь: " + shown
        return Verdict(not problems, observed, {"losses": losses})

    return fn


def why(outcome, position_id, losses):
    if losses.get(position_id) is not None:
        return fmt(losses[position_id])
    return why_not_calculated(outcome, position_id)


for index, path in enumerate(sorted((catalog.CATALOG / "events").glob("*.json")), 1):
    library_event = json.loads(path.read_text("utf-8"))
    check(
        f"M{index}",
        library_event["title"],
        "; ".join(
            f"{EXPECTED[key]}: {', '.join(ids)}"
            for key, ids in library_event["expect"].items()
            if ids
        ),
        portfolio=library_event["metadata"]["portfolio_id"],
        event=library_event["event_id"],
    )(library_check(library_event))
