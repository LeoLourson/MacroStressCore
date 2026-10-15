"""Портфель пилота АФК: публичные «дочки» АФК «Система» на 24.10.2024.

Собирается из данных ``demo/pilot-afk``: цены — закрытия MOEX ISS 24.10.2024, бета к индексу
и остаточная волатильность — регрессия за 24.10.2023–24.10.2024 (``compute_beta.py``,
``beta-computation.json``), число акций и дивиденды — задание пилота.

Каждое число несёт источник: котировка и бета — ``historical_estimate`` с датой окна,
оценка — ``expert_assumption`` с автором и датой сборки. Записи идут тем же путём, что у
пилота «Эталон»: шапка в ``demo/portfolios``, части плагинов в их ``demo_data``, шапка
снимка в ``demo/snapshots``.

    uv run --frozen python -m demo.build_pilot_afk           # записать файлы
    uv run --frozen python -m demo.build_pilot_afk --check   # сверить с записанными
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
from msa.db.repositories.portfolios import check_bundle
from msa.platform.registry import package_of
from msa.platform.registry import registry as current

CATALOG = Path(__file__).resolve().parent
REPOSITORY = CATALOG.parent
PILOT = CATALOG / "pilot-afk"
#: Оценка пилота — авторская; датируется днём сборки каталога.
AUTHOR = "pilot-afk:analyst"
ASSUMED_ON = date(2026, 10, 15)
ESTIMATE = "pilot-afk:estimate"
#: Источники значений снимка: биржа и расчёт пилота.
MOEX = "MOEX-ISS"
REGRESSION = "PILOT-AFK"
HISTORY = "historical_estimate"
ASSUMPTION = "expert_assumption"

PORTFOLIO_ID = "AFK-SYSTEMA-OCT-2024"
SNAPSHOT_ID = "AFK-SYSTEMA-2024-10-24"
AS_OF = date(2024, 10, 24)
NAME = "Публичные «дочки» АФК «Система» на 24.10.2024"

#: Бумаги портфеля: тикер -> (position_id, эмитент, ОКВЭД, отрасль, число акций,
#: дивиденды за горизонт на акцию).
SHARES = {
    "MTSS": ("SHARE-MTSS", "ПАО «МТС»", "61.10", "telecom", 839_320_000, 35.0),
    "OZON": ("SHARE-OZON", "ООО «Интернет Решения» (Ozon)", "47.91", "trade", 69_252_000, 0.0),
    "SGZH": ("SHARE-SGZH", "ПАО «Сегежа Групп»", "17.12", "materials", 9_759_180_000, 0.0),
    "ETLN": ("SHARE-ETLN", "МКПАО «Эталон Груп»", "41.20", "real_estate", 186_992_000, 0.0),
}
#: Оценки, которых нет в котировках и в регрессии: (где сказано, как называется источник).
ASSUMED = {
    "quantity": ("число акций в позиции: задание пилота", ESTIMATE),
    "beta_sector": (
        "отраслевой фактор задан как доходность отрасли сверх рынка; коэффициент 1,0 — "
        "допущение, как в пилоте «Эталон»",
        ESTIMATE,
    ),
    "sector": ("отрасль модели: по ОКВЭД эмитента", ESTIMATE),
}
#: Дивиденды за горизонт: у МТС объявленная выплата, у остальных — экспертная оценка нуля.
DIVIDENDS = {
    "MTSS": (
        HISTORY,
        "MTS-IR",
        "годовые дивиденды ПАО «МТС» за 2024 год, 35,00 ₽ на акцию, выплачены в июле 2025 года",
    ),
}
DIVIDEND_NONE = (ASSUMPTION, ESTIMATE, "дивиденды за горизонт не выплачивались")


def _market() -> dict:
    return json.loads((PILOT / "market-data.json").read_text(encoding="utf-8"))


def _beta() -> dict:
    return json.loads((PILOT / "beta-computation.json").read_text(encoding="utf-8"))


def _closes(ticker: str, sections: dict) -> dict[str, float]:
    section = sections["securities"][ticker]
    index = section["columns"].index("CLOSE")
    return {row[0]: float(row[index]) for row in section["data"] if row[index] is not None}


def rows():
    """Значения портфеля и происхождение каждого: (значение, вид, источник, где сказано)."""
    sections = _market()
    computed = _beta()
    result = {}
    for ticker, (position_id, issuer, okved, sector, quantity, dividend) in SHARES.items():
        price = _closes(ticker, sections)[AS_OF.isoformat()]
        sensitivity = computed["sensitivities"][ticker]
        window = computed["sensitivity_window"]
        regression = (
            f"бета к MOEXBMI за {window[0]}–{window[1]}: {sensitivity['observations']} наблюдений"
        )
        sigma = (
            f"остаточная σ {sensitivity['residual_volatility']:.4f} при β "
            f"{sensitivity['beta_market']:.4f} и β_отр 1"
        )
        dividend_kind, dividend_source, dividend_locator = DIVIDENDS.get(ticker, DIVIDEND_NONE)
        values = {
            "ticker": (ticker, HISTORY, MOEX, f"карточка бумаги {ticker} на MOEX"),
            "market_index": ("MOEX", HISTORY, MOEX, "бета считалась к индексу MOEXBMI"),
            "price": (price, HISTORY, MOEX, f"{ticker} TQBR, закрытие {AS_OF.isoformat()}"),
            "beta_market": (sensitivity["beta_market"], HISTORY, REGRESSION, regression),
            "residual_volatility": (sensitivity["residual_volatility"], HISTORY, REGRESSION, sigma),
            "dividend": (dividend, dividend_kind, dividend_source, dividend_locator),
        }
        # Поля, которых нет ни в котировках, ни в регрессии: у каждого свой автор.
        for name, (locator, source) in ASSUMED.items():
            stated = {"quantity": float(quantity), "sector": sector, "beta_sector": 1.0}[name]
            values[name] = (stated, ASSUMPTION, source, locator)
        result[position_id] = {
            "name": f"Акция {ticker}: {issuer}",
            "party": ticker,
            "party_name": issuer,
            "okved": okved,
            "values": values,
        }
    return result


@dataclass
class PilotContext(DraftContext):
    """Называет источник каждого поля: биржу, расчёт пилота или автора оценки."""

    fields: dict = field(default_factory=dict)
    names: dict = field(default_factory=dict)

    def issuer_id(self, position_id) -> str:
        return f"{self.portfolio_id}:{self.names[position_id]}"

    def evidence(self, position_id, field, value) -> list[dict]:
        item = self.fields.get((position_id, field)) or (
            value,
            ASSUMPTION,
            ESTIMATE,
            f"поле {field}: значение по умолчанию",
        )
        _, kind, source, locator = item
        evidence = {
            "kind": kind,
            "source_id": source,
            "locator": locator,
            "fragment_sha256": sha256(f"{source}/{locator}={value}".encode()).hexdigest(),
        }
        if kind == ASSUMPTION:
            evidence |= {"author": AUTHOR, "as_of": ASSUMED_ON.isoformat()}
        return [evidence]


def portfolio(registry) -> tuple[dict, dict, list[dict]]:
    found = rows()
    draft = PortfolioDraft(
        name=NAME,
        positions=[
            {
                "position_id": position_id,
                "name": row["name"],
                "instrument_type": "common_stock",
                "okved": row["okved"],
                "currency": "RUB",
                "values": {field: item[0] for field, item in row["values"].items()},
            }
            for position_id, row in found.items()
        ],
    )
    context = PilotContext(
        author=AUTHOR,
        today=AS_OF,
        source_id=ESTIMATE,
        portfolio_id=PORTFOLIO_ID,
        fields={
            (position_id, name): item
            for position_id, row in found.items()
            for name, item in row["values"].items()
        },
        names={position_id: row["party"] for position_id, row in found.items()},
    )
    bundle, snapshot = build_draft(
        draft,
        author=AUTHOR,
        today=AS_OF,
        registry=registry,
        portfolio_id=PORTFOLIO_ID,
        context=context,
    )
    data = bundle.model_dump(mode="json")
    # Черновик редактора даёт эмитенту идентификатор «портфель:позиция», а контрагент в
    # каталоге назван бумагой: у каждого эмитента одна акция в портфеле, так что связь
    # «инструмент → контрагент» ставится здесь же.
    for instrument in data["instruments"]:
        instrument["issuer_id"] = found[instrument["instrument_id"].split(":", 1)[1]]["party"]
    data["parties"] = [
        {
            "party_id": row["party"],
            "name": row["party_name"],
            "kind": "company",
            "okved": row["okved"],
            "country": "RU",
            "description": f"Эмитент акции {position_id}: {row['name']}",
            "evidence": [
                {
                    "kind": ASSUMPTION,
                    "source_id": ESTIMATE,
                    "locator": f"карточка контрагента {row['party']}",
                    "fragment_sha256": sha256(row["party"].encode()).hexdigest(),
                    "author": AUTHOR,
                    "as_of": ASSUMED_ON.isoformat(),
                }
            ],
        }
        for position_id, row in found.items()
    ]
    header = {
        "portfolio": {
            "portfolio_id": PORTFOLIO_ID,
            "name": NAME,
            "base_currency": "RUB",
            "as_of": AS_OF.isoformat(),
            "snapshot_id": SNAPSHOT_ID,
            "builtin": True,
            "metadata": {
                "source": "demo/pilot-afk",
                "synthetic": False,
                "money_unit": "RUB_million",
                "description": (
                    "Исторический пилот: четыре публичные компании, связанные с АФК «Система», "
                    "на 24.10.2024 — МТС, Ozon, Сегежа и Эталон. Горизонт 12 месяцев; факт "
                    "окна 24.10.2024–24.10.2025 — для сверки"
                ),
                "conventions": [
                    "Цены — закрытия режима TQBR Московской биржи 24.10.2024",
                    "Бета к индексу и остаточная волатильность — регрессия дневных "
                    "логарифмических доходностей за 24.10.2023–24.10.2024 к индексу MOEXBMI",
                    "Бета к отрасли равна 1,0: сценарий задаёт доходность отрасли сверх рынка",
                    "Дивиденды — объявленная сумма на акцию за горизонт: у МТС 35,00 ₽, "
                    "у остальных выплат не было",
                    "Число акций в позиции задано заданием пилота и не является долей "
                    "в капитале эмитента",
                    "Позиции — только акции: кредитного среза в этом портфеле нет",
                ],
            },
        }
    }
    return header, data, snapshot.model_dump(mode="json")["items"]


def outputs(registry=None) -> dict[Path, str]:
    registry = registry or current()
    header, data, items = portfolio(registry)
    problems = check_bundle(_bundle(header, data), registry)
    if problems:
        raise ValueError(f"{PORTFOLIO_ID}: " + "; ".join(problems))
    files = {
        CATALOG / "portfolios" / f"{PORTFOLIO_ID}.json": _json(header),
        CATALOG / "snapshots" / f"{SNAPSHOT_ID}.json": _json(
            {
                "snapshot_id": SNAPSHOT_ID,
                "as_of": AS_OF.isoformat(),
                "label": f"«Данные {NAME}»",
                "kind": "demo",
                "metadata": {
                    "source": "demo/pilot-afk",
                    "synthetic": False,
                    "description": (
                        "Котировки MOEX ISS, бета и остаточная волатильность из "
                        "demo/pilot-afk/beta-computation.json"
                    ),
                },
            }
        ),
    }
    parts: dict[str, dict] = {}
    for position in data["positions"]:
        instrument = next(
            i for i in data["instruments"] if i["instrument_id"] == position["instrument_id"]
        )
        plugin_id = registry.plugin_of(instrument["instrument_type"]).plugin_id
        part = parts.setdefault(plugin_id, {"parties": [], "instruments": [], "positions": []})
        party = next(p for p in data["parties"] if p["party_id"] == instrument["issuer_id"])
        part["parties"].append(party)
        part["instruments"].append(instrument)
        part["positions"].append(position)
    snapshot_parts: dict[str, dict] = {}
    for item in items:
        plugin_id = registry.plugin_of(item["kind"]).plugin_id
        snapshot_parts.setdefault(plugin_id, {})[item["item_id"]] = item
    for plugin_id, part in parts.items():
        folder = _demo_data(registry, plugin_id) / "portfolios"
        files[folder / f"{PORTFOLIO_ID}.json"] = _json(part)
    for plugin_id, part in snapshot_parts.items():
        folder = _demo_data(registry, plugin_id) / "snapshots"
        files[folder / f"{SNAPSHOT_ID}.json"] = _json(
            {"items": [part[key] for key in sorted(part)]}
        )
    return files


def _bundle(header, data):
    from msa.contracts import PortfolioBundle

    return PortfolioBundle.model_validate({**header, **data})


def _demo_data(registry, plugin_id) -> Path:
    from importlib.resources import files

    return Path(str(files(package_of(registry.plugins[plugin_id])))) / "demo_data"


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="сверить, не записывать")
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
