"""The pilot's two real portfolios: ГК «Эталон» on 31.12.2023 and on 30.06.2024.

Assembled by hand from ``demo/pilot-etalon`` (the group's IFRS statements, MOEX quotes, the
project declaration of ЖК «Зелёная Река»). Each portfolio holds three positions: a corporate
loan to the group, the ETLN share and the escrow-backed project loan of the Omsk project.

Every figure the reporting gives carries the document and the section it came from
(``historical_estimate``); every figure the reporting does not give carries its author and
the date of the assumption (``expert_assumption``). Which figures are which, and how the
project inputs were calibrated, is written down in ``demo/pilot-etalon/catalog-notes.md``.

The records go the path of the demo catalog: the header into ``demo/portfolios``, the parts
of each plugin into its ``demo_data``, the snapshot header into ``demo/snapshots``.

    uv run --frozen python -m demo.build_etalon           # write the files
    uv run --frozen python -m demo.build_etalon --check   # compare them with the output
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import date
from hashlib import sha256
from pathlib import Path

from msa.api.portfolio_draft import DraftContext, PortfolioDraft
from msa.api.portfolio_draft import build as build_draft
from msa.contracts import DataSnapshot
from msa.db.repositories.portfolios import check_bundle
from msa.platform.registry import package_of
from msa.platform.registry import registry as current

CATALOG = Path(__file__).resolve().parent
REPOSITORY = CATALOG.parent
#: An estimated figure is the analyst's; it is dated when the pilot was assembled.
AUTHOR = "pilot-etalon:analyst"
ASSUMED_ON = date(2026, 10, 15)
ESTIMATE = "pilot-etalon:estimate"
HISTORY = "historical_estimate"
ASSUMPTION = "expert_assumption"

#: Portfolio id -> name, the snapshot it reads and what the portfolio is.
PORTFOLIOS = {
    "ETALON-DEC-2023": (
        "«Эталон» на 31.12.2023",
        "ETALON-2023-12-31",
        date(2023, 12, 31),
        "«Данные ГК «Эталон» на 31.12.2023»",
        "ГК «Эталон» перед ужесточением массовой льготной ипотеки 23.12.2023: "
        "корпоративный кредит группе, акция ETLN и проектное финансирование "
        "ЖК «Зелёная Река» (Омск)",
    ),
    "ETALON-JUN-2024": (
        "«Эталон» на 30.06.2024",
        "ETALON-2024-06-30",
        date(2024, 6, 30),
        "«Данные ГК «Эталон» на 30.06.2024»",
        "ГК «Эталон» в последний месяц массовой льготной ипотеки: корпоративный кредит "
        "группе, акция ETLN и проектное финансирование ЖК «Зелёная Река» (Омск)",
    ),
}

#: The parties. The group is a housing developer: its OKVED is the one the sector factor
#: reads, not the holding company's 64.20 (the draft explains the choice).
PARTIES = {
    "ETALON-GROUP": (
        "МКПАО «Эталон Груп»",
        "41.20",
        "Жилищное строительство; отчётная головная компания группы Etalon Group PLC "
        "(до редомициляции 2025 года)",
    ),
    "ETALON-OMSK": (
        "ООО «СЗ «Эталон-Омск»",
        "41.20",
        "Застройщик ЖК «Зелёная Река» (Омск); проектное финансирование Банка ДОМ.РФ "
        "и АО «Эталон-Финанс», счета эскроу в Банке ДОМ.РФ",
    ),
}

# Reported figures of the group, RUB million, and where each one is written.
#: ``IFRS-12M2023``  — МСФО за 12М2023 (etalongroup.com), ``IFRS-6M2024`` — МСФО за 6М2024,
#: ``IFRS-12M2024``  — МСФО за 12М2024 (пересчёт 12М2023), ``MOEX-ISS`` — котировки,
#: ``DECL-47652``    — проектная декларация № 55-000133, ``PILOT-ETALON`` — расчёты пилота.
GROUP_2023 = {
    "revenue": (90652.0, "IFRS-12M2024", "Прим. 2(f), 12М2023 в пересчёте: выручка"),
    "cogs": (60681.0, "IFRS-12M2024", "ОПиУ, 12М2023 в пересчёте: себестоимость продаж"),
    "opex": (12633.0, "IFRS-12M2024", "ОПиУ, 12М2023: ОХАР 7 475 + коммерческие 5 158"),
    "net_debt": (37039.0, "IFRS-6M2024", "Не-МСФО: чистый корпоративный долг"),
    "gross_debt": (118611.0, "IFRS-6M2024", "ОФП: кредиты и займы"),
    "cash": (9724.0, "IFRS-12M2023", "ОФП: денежные средства и их эквиваленты"),
    "borrowing_rate": (0.0873, "IFRS-12M2023", "Прим. 23: средневзвешенная ставка 8,73 %"),
    "capex": (2146.0, "IFRS-12M2023", "ОДДС: приобретение основных средств и НМА"),
    "dividend": (0.0, "IFRS-12M2023", "Прим. 21(c): дивиденды не объявлялись и не платились"),
}
GROUP_2024 = {
    "revenue": (114513.0, "IFRS-6M2024", "LTM на 30.06.2024: 90 652 + 57 360 − 33 499"),
    "cogs": (76220.0, "IFRS-6M2024", "LTM на 30.06.2024: 60 681 + 37 792 − 22 253"),
    "opex": (13693.0, "IFRS-6M2024", "LTM на 30.06.2024: 12 633 + 6 667 − 5 607"),
    "net_debt": (62546.0, "IFRS-6M2024", "Не-МСФО: чистый корпоративный долг"),
    "gross_debt": (142243.0, "IFRS-6M2024", "ОФП: кредиты и займы"),
    "cash": (6999.0, "IFRS-6M2024", "ОФП: денежные средства и их эквиваленты"),
    "borrowing_rate": (0.102, "IFRS-6M2024", "Прим. 16: средневзвешенная ставка 10,2 %"),
    "capex": (3280.0, ESTIMATE, "поддерживающий capex: 2 × 1 640 (6М2024), помесячных нет"),
    "dividend": (0.0, "IFRS-6M2024", "Прим. 15(a): дивиденды не объявлялись и не платились"),
}
#: The share of the group and the project. A regression beta to MOEXBMI and its residual
#: volatility come from the pilot's own computation (group-operations.md).
SHARE = {
    "2023": {
        "price": (83.22, "MOEX-ISS", "ETLN TQBR, закрытие 29.12.2023"),
        "beta_market": (1.33, "PILOT-ETALON", "бета к MOEXBMI за 2023 год (253 наблюдения)"),
        "residual_volatility": (0.331, "PILOT-ETALON", "σ 37,57 % при β 1,33 и σ индекса 13,42 %"),
    },
    "2024": {
        "price": (82.00, "MOEX-ISS", "ETLN TQBR, закрытие 28.06.2024"),
        "beta_market": (1.515, "PILOT-ETALON", "бета к MOEXBMI за 07.2023–06.2024 (253 наблюдения)"),
        "residual_volatility": (0.31, "PILOT-ETALON", "σ 36,73 % при β 1,515 и σ индекса 12,99 %"),
    },
}
#: The project: the declaration gives the limit, the cost, the schedule and the transfer
#: date; the monthly flows and the opening balances are calibrated to its state at the end
#: of 2025 (debt 3 919 and accumulated ДДУ 3 174 as of the declaration copy of 16.12.2025).
PROJECT = {
    "2023": {
        "equity": (200.0, ESTIMATE, "оценка: из 600 млн ₽ своих средств к 31.12.2023 вложено 400"),
        "debt": (1275.0, ESTIMATE, "калибровка: 17 месяцев × 95 − 400 вложенных своих средств + проценты"),
        "escrow": (1316.0, ESTIMATE, "калибровка: 17 месяцев продаж × 77,4"),
        "commissioning_month": (26.0, "DECL-47652", "раздел 17.2.2: передача 28.02.2026, это месяц 26"),
    },
    "2024": {
        "equity": (100.0, ESTIMATE, "оценка: из 600 млн ₽ своих средств к 30.06.2024 вложено 500"),
        "debt": (1900.0, ESTIMATE, "калибровка: 23 месяца × 95 − 500 вложенных своих средств + проценты"),
        "escrow": (1780.0, ESTIMATE, "калибровка: 23 месяца продаж × 77,4"),
        "commissioning_month": (20.0, "DECL-47652", "раздел 17.2.2: передача 28.02.2026, это месяц 20"),
    },
}


def _value(item):
    return {"value": item[0], "kind": HISTORY, "source": item[1], "locator": item[2]}


def _estimate(value, locator):
    return {"value": value, "kind": ASSUMPTION, "source": ESTIMATE, "locator": locator}


def loan_row(group):
    """The corporate loan to the group: the figures the IFRS statements give, and the rest."""
    values = {name: _value(item) for name, item in group.items()}
    values |= {
        "ead": _estimate(5000.0, "сумма под риском: позиция банка в группе, задаёт аналитик"),
        "lgd": _estimate(0.45, "потери при дефолте: оценка, в раскрытии её нет"),
        "ccf": _estimate(1.0, "коэффициент кредитной конверсии: значение по умолчанию"),
        "import_share": _estimate(0.0, "доля импорта в затратах: у застройщика не выделяется"),
        "tax_rate": _estimate(0.20, "ставка налога на прибыль: значение по умолчанию"),
        "demand_elasticity": _estimate(-1.0, "эластичность спроса: значение по умолчанию"),
        "pass_through": _estimate(0.0, "перенос затрат в цену: у застройщика не выделяется"),
        "dso": _estimate(45.0, "оборачиваемость дебиторки: не раскрыта, значение по умолчанию"),
        "dio": _estimate(30.0, "оборачиваемость запасов: не раскрыта, значение по умолчанию"),
        "dpo": _estimate(30.0, "оборачиваемость кредиторки: не раскрыта, значение по умолчанию"),
    }
    return {
        "position_id": "LOAN-ETALON",
        "name": f"Корпоративный кредит: {PARTIES['ETALON-GROUP'][0]}",
        "instrument_type": "corp_loan",
        "party": "ETALON-GROUP",
        "values": values,
    }


def share_row(share):
    values = {
        "quantity": _estimate(1_000_000.0, "количество акций в позиции: задаёт аналитик"),
        "ticker": _value(("ETLN", "MOEX-ISS", "карточка бумаги ETLN, ISIN RU000A10C1L6")),
        "market_index": _value(("MOEX", "PILOT-ETALON", "бета считалась к индексу MOEXBMI")),
        "sector": _estimate("real_estate", "отрасль модели: по ОКВЭД 41.20 застройщика"),
        "price": _value(share["price"]),
        "beta_market": _value(share["beta_market"]),
        "beta_sector": _estimate(
            1.0,
            "отраслевой фактор задан как доходность застройщиков сверх рынка; "
            "коэффициент 1,0 — допущение",
        ),
        "residual_volatility": _value(share["residual_volatility"]),
        "dividend": _estimate(0.0, "дивиденды за 2022–2025 годы не начислялись"),
    }
    return {
        "position_id": "SHARE-ETLN",
        "name": f"Акция ETLN: {PARTIES['ETALON-GROUP'][0]}",
        "instrument_type": "common_stock",
        "party": "ETALON-GROUP",
        "values": values,
    }


def project_row(project):
    values = {
        "ead": _value((4304.0, "DECL-47652", "раздел 19.6: сумма двух целевых кредитов")),
        "lgd": _estimate(0.35, "потери при дефолте проекта: оценка"),
        "ccf": _estimate(1.0, "коэффициент кредитной конверсии: значение по умолчанию"),
        "import_share": _estimate(0.0, "доля импорта в затратах: не выделяется"),
        "credit_limit": _value((4304.0, "DECL-47652", "раздел 19.6: 2 664 Банк ДОМ.РФ + 1 640 Эталон-Финанс")),
        "equity": _value(project["equity"]),
        "capex_month_1_12": _estimate(95.0, "смета 4 085 млн ₽ / 43 месяца строительства"),
        "capex_month_13_24": _estimate(95.0, "тот же месячный темп стройки"),
        "monthly_sales": _estimate(77.4, "калибровка: 3 174 млн ₽ накопленных ДДУ / 41 месяц"),
        "base_rate": _estimate(0.20, "ставка проектного финансирования без субсидии: оценка"),
        "subsidized_rate": _estimate(0.04, "льготная ставка при покрытии эскроу: 3,5–4,3 % в 2024 году"),
        "sales_start_month": _estimate(1.0, "продажи идут с 2022 года"),
        "debt": _value(project["debt"]),
        "escrow": _value(project["escrow"]),
        "commissioning_month": _value(project["commissioning_month"]),
    }
    return {
        "position_id": "PROJECT-ZELENAYA-REKA",
        "name": f"Проектное финансирование: {PARTIES['ETALON-OMSK'][0]}",
        "instrument_type": "pf_escrow",
        "party": "ETALON-OMSK",
        # The bank's commitment is the whole line: the project draws it, not the drawn debt.
        "flags": ["ead_is_credit_limit"],
        "values": values,
    }


def rows(portfolio_id):
    key = "2023" if portfolio_id == "ETALON-DEC-2023" else "2024"
    group = GROUP_2023 if key == "2023" else GROUP_2024
    return [loan_row(group), share_row(SHARE[key]), project_row(PROJECT[key])]


@dataclass
class PilotContext(DraftContext):
    """Names each field's source: the document the figure came from, or its author."""

    fields: dict = field(default_factory=dict)
    names: dict = field(default_factory=dict)

    def issuer_id(self, position_id) -> str:
        return self.names[position_id]

    def evidence(self, position_id, field, value) -> list[dict]:
        item = self.fields.get((position_id, field)) or _estimate(
            value, f"поле {field}: значение по умолчанию демо-каталога"
        )
        evidence = {
            "kind": item["kind"],
            "source_id": item["source"],
            "locator": item["locator"],
            "fragment_sha256": sha256(f"{item['source']}/{item['locator']}={value}".encode()).hexdigest(),
        }
        if item["kind"] == ASSUMPTION:
            evidence |= {"author": AUTHOR, "as_of": ASSUMED_ON.isoformat()}
        return [evidence]


def portfolio(portfolio_id, registry) -> tuple[dict, dict, list[dict]]:
    """``(header, bundle data, snapshot items)`` of one pilot portfolio."""
    name, snapshot_id, as_of, label, description = PORTFOLIOS[portfolio_id]
    found = rows(portfolio_id)
    draft = PortfolioDraft(
        name=name,
        positions=[
            {
                "position_id": row["position_id"],
                "name": row["name"],
                "instrument_type": row["instrument_type"],
                "okved": PARTIES[row["party"]][1],
                "currency": "RUB",
                "values": {field: item["value"] for field, item in row["values"].items()},
            }
            for row in found
        ],
    )
    context = PilotContext(
        author=AUTHOR,
        today=as_of,
        source_id=ESTIMATE,
        portfolio_id=portfolio_id,
        fields={
            (row["position_id"], field): item
            for row in found
            for field, item in row["values"].items()
        },
        names={row["position_id"]: row["party"] for row in found},
    )
    bundle, snapshot = build_draft(
        draft,
        author=AUTHOR,
        today=as_of,
        registry=registry,
        portfolio_id=portfolio_id,
        context=context,
    )
    data = bundle.model_dump(mode="json")
    flags = {row["position_id"]: row.get("flags", []) for row in found}
    for position in data["positions"]:
        if "flags" in position["params"]:
            position["params"]["flags"] = list(flags.get(position["position_id"], []))
    data["parties"] = [
        {
            "party_id": party_id,
            "name": PARTIES[party_id][0],
            "kind": "company",
            "okved": PARTIES[party_id][1],
            "description": PARTIES[party_id][2],
            "evidence": [
                {
                    "kind": ASSUMPTION,
                    "source_id": ESTIMATE,
                    "locator": f"карточка контрагента {party_id}",
                    "fragment_sha256": sha256(party_id.encode()).hexdigest(),
                    "author": AUTHOR,
                    "as_of": ASSUMED_ON.isoformat(),
                }
            ],
        }
        for party_id in {row["party"] for row in found}
    ]
    header = {
        "portfolio": {
            "portfolio_id": portfolio_id,
            "name": name,
            "base_currency": "RUB",
            "as_of": as_of.isoformat(),
            "snapshot_id": snapshot_id,
            "builtin": True,
            "metadata": {
                "source": "demo/pilot-etalon",
                "synthetic": False,
                "money_unit": "RUB_million",
                "description": description,
                "conventions": [
                    "Историческое событие: данные на дату снимка, факт следующего года — для сверки",
                    "Годовые потоки отчётности разложены по месяцам горизонтa равномерно (flag "
                    "annual_financials_spread_evenly)",
                    "На 30.06.2024 потоки взяты за 12 месяцев, закончившихся 30.06.2024 (LTM)",
                    "Отчётность опубликована позже даты снимка: 12М2023 — 25.03.2024, 6М2024 — "
                    "28.08.2024; это известное заглядывание вперёд, см. catalog-notes.md",
                    "Чистый долг модели — весь процентный долг минус деньги; эмитент раскрывает "
                    "чистый корпоративный долг без проектного финансирования, покрытого эскроу",
                    "Ковенанты не заданы: их уровни в открытых источниках не раскрыты",
                    "Поля проекта (свои средства, помесячные продажи и затраты, ставки) — "
                    "экспертные оценки, калиброванные по декларации; см. catalog-notes.md",
                ],
            },
        }
    }
    return header, data, snapshot.model_dump(mode="json")["items"]


def outputs(registry=None) -> dict[Path, str]:
    """Every file of the two pilot portfolios and its text."""
    registry = registry or current()
    files: dict[Path, str] = {}
    for portfolio_id in PORTFOLIOS:
        header, data, items = portfolio(portfolio_id, registry)
        _, snapshot_id, as_of, label, description = PORTFOLIOS[portfolio_id]
        problems = check_bundle(_bundle(header, data), registry)
        if problems:
            raise ValueError(f"{portfolio_id}: " + "; ".join(problems))
        files[CATALOG / "portfolios" / f"{portfolio_id}.json"] = _json(header)
        files[CATALOG / "snapshots" / f"{snapshot_id}.json"] = _json(
            {
                "snapshot_id": snapshot_id,
                "as_of": as_of.isoformat(),
                "label": label,
                "kind": "demo",
                "metadata": {
                    "source": "demo/pilot-etalon",
                    "synthetic": False,
                    "description": description,
                },
            }
        )
        owner = {
            item["instrument_id"]: registry.plugin_of(item["instrument_type"]).plugin_id
            for item in data["instruments"]
        }
        parts: dict[str, dict] = {}
        for position in data["positions"]:
            plugin_id = owner[position["instrument_id"]]
            part = parts.setdefault(
                plugin_id, {"parties": {}, "instruments": {}, "positions": {}}
            )
            instrument = next(
                i for i in data["instruments"] if i["instrument_id"] == position["instrument_id"]
            )
            party = next(p for p in data["parties"] if p["party_id"] == instrument["issuer_id"])
            _merge(part["parties"], [party], "party_id", portfolio_id)
            _merge(part["instruments"], [instrument], "instrument_id", portfolio_id)
            _merge(part["positions"], [position], "position_id", portfolio_id)
        for plugin_id, part in parts.items():
            folder = _demo_data(registry, plugin_id) / "portfolios"
            files[folder / f"{portfolio_id}.json"] = _json(
                {name: list(records.values()) for name, records in part.items()}
            )
        snapshot_parts: dict[str, dict] = {}
        for item in items:
            plugin_id = registry.plugin_of(item["kind"]).plugin_id
            snapshot_parts.setdefault(plugin_id, {})[item["item_id"]] = item
        for plugin_id, part in snapshot_parts.items():
            folder = _demo_data(registry, plugin_id) / "snapshots"
            files[folder / f"{snapshot_id}.json"] = _json(
                {"items": [part[key] for key in sorted(part)]}
            )
    return files


def _bundle(header, data):
    from msa.contracts import PortfolioBundle

    return PortfolioBundle.model_validate({**header, **data})


def _demo_data(registry, plugin_id) -> Path:
    from importlib.resources import files

    return Path(str(files(package_of(registry.plugins[plugin_id])))) / "demo_data"


def _merge(target: dict, records: list, key: str, where: str) -> None:
    for record in records:
        known = target.setdefault(record[key], record)
        if known != record:
            raise ValueError(f"{where}: two different records {record[key]}")


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="compare, do not write")
    args = parser.parse_args()
    stale = []
    for path, text in outputs().items():
        current_text = path.read_text("utf-8") if path.exists() else None
        if current_text == text:
            continue
        stale.append(path.relative_to(REPOSITORY))
        if not args.check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
    for path in stale:
        print(("stale " if args.check else "wrote ") + str(path))
    sys.exit(1 if args.check and stale else 0)


if __name__ == "__main__":
    main()
