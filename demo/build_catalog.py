"""The generated part of the demo catalog: the themed portfolios and the mock answers.

The four themed portfolios hold loans, bonds and shares of synthetic companies. Each is
written below as editor rows and goes the path of a portfolio typed in the editor
(``msa.api.portfolio_draft.build``). The records then get their catalog names: a company is
one party and a security one instrument, shared by every portfolio that holds it, with
sources that name the company or the security. The parts are laid out as ``demo.catalog``
reads them: the headers in demo/, the positions and the snapshot items of each plugin in its
``demo_data``, one snapshot for all four portfolios.

The mock profile's answers (``src/msa/agents/mock_events.json``) are collected from the
analyst's prepared answer (``mock_answer``) of every library event and of the pilot event.

    uv run --frozen python -m demo.build_catalog           # write the files
    uv run --frozen python -m demo.build_catalog --check   # compare them with the output
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
AS_OF = date(2026, 9, 11)
AUTHOR = "demo:catalog"
SOURCE = "demo:companies"
SNAPSHOT_ID = "SYNTHETIC-THEMES-2026-09-11"
SNAPSHOT_LABEL = "Синтетические данные тематических портфелей на 11.09.2026"
MOCK_EVENTS = REPOSITORY / "src" / "msa" / "agents" / "mock_events.json"


@dataclass(frozen=True)
class Company:
    name: str
    okved: str
    description: str
    country: str = "RU"


COMPANIES = {
    "CAR-IMPORTER": Company(
        "Автодилер-импортёр", "45.11", "Импорт и продажа легковых автомобилей; закупки в валюте"
    ),
    "DRUG-DISTRIBUTOR": Company(
        "Дистрибьютор лекарств", "46.46", "Оптовая торговля импортными лекарствами"
    ),
    "ELECTRONICS-RETAILER": Company(
        "Сеть магазинов электроники", "47.41", "Розничная продажа импортной электроники"
    ),
    "STEEL-EXPORTER": Company(
        "Металлургический комбинат", "24.10", "Производство стали; большая часть выручки — экспорт"
    ),
    "POTASH-EXPORTER": Company(
        "Производитель калийных удобрений", "20.15", "Добыча и экспорт калийных удобрений"
    ),
    "US-PHARMA": Company(
        "Фармацевтическая компания (США)",
        "21.20",
        "Производство лекарств; акции обращаются на NYSE",
        country="US",
    ),
    "LEVERAGED-DEVELOPER": Company(
        "Девелопер с высоким долгом", "41.20", "Жилищное строительство на заёмные средства"
    ),
    "DISCOUNTER-CHAIN": Company("Сеть магазинов у дома", "47.11", "Продуктовые магазины у дома"),
    "WAREHOUSE-OPERATOR": Company(
        "Оператор складов", "52.10", "Складская логистика и аренда складов"
    ),
    "TELECOM-OPERATOR": Company("Оператор связи", "61.10", "Проводная связь и интернет"),
    "SUPERMARKET-CHAIN": Company("Сеть супермаркетов", "47.11", "Продуктовые супермаркеты"),
    "MEAT-PROCESSOR": Company("Мясокомбинат", "10.11", "Переработка и консервирование мяса"),
    "DAIRY-PRODUCER": Company("Молочный завод", "10.51", "Производство молочной продукции"),
    "RESTAURANT-CHAIN": Company("Сеть ресторанов", "56.10", "Рестораны и кафе"),
    "APPAREL-RETAILER": Company("Сеть магазинов одежды", "47.71", "Розничная продажа одежды"),
    "COMMERCIAL-BANK": Company("Коммерческий банк", "64.19", "Кредитование и расчётные услуги"),
    "OIL-MAJOR": Company("Нефтяная компания", "06.10", "Добыча нефти"),
    "IT-DEVELOPER": Company(
        "Разработчик программного обеспечения", "62.01", "Разработка корпоративных программ"
    ),
}

#: A company's reported year, RUB million, and how its prices and demand react.
STATEMENTS = {
    "CAR-IMPORTER": dict(
        revenue=30000.0,
        cogs=25500.0,
        opex=2700.0,
        net_debt=6000.0,
        cash=800.0,
        borrowing_rate=0.16,
        dso=20.0,
        dio=60.0,
        dpo=30.0,
        demand_elasticity=-1.2,
        pass_through=0.6,
    ),
    "DRUG-DISTRIBUTOR": dict(
        revenue=18000.0,
        cogs=15300.0,
        opex=1500.0,
        net_debt=3000.0,
        cash=400.0,
        borrowing_rate=0.15,
        dso=60.0,
        dio=45.0,
        dpo=50.0,
        demand_elasticity=-0.3,
        pass_through=0.7,
    ),
    "ELECTRONICS-RETAILER": dict(
        revenue=25000.0,
        cogs=20000.0,
        opex=3500.0,
        net_debt=4000.0,
        cash=1000.0,
        borrowing_rate=0.16,
        dso=5.0,
        dio=70.0,
        dpo=45.0,
        demand_elasticity=-1.5,
        pass_through=0.5,
    ),
    "STEEL-EXPORTER": dict(
        revenue=60000.0,
        cogs=42000.0,
        opex=6000.0,
        net_debt=18000.0,
        cash=3000.0,
        borrowing_rate=0.13,
        dso=30.0,
        dio=50.0,
        dpo=40.0,
        demand_elasticity=-0.8,
        pass_through=0.0,
    ),
    "POTASH-EXPORTER": dict(
        revenue=40000.0,
        cogs=22000.0,
        opex=6000.0,
        net_debt=20000.0,
        cash=2000.0,
        borrowing_rate=0.12,
        dso=45.0,
        dio=40.0,
        dpo=35.0,
        demand_elasticity=-0.6,
        pass_through=0.0,
    ),
    "LEVERAGED-DEVELOPER": dict(
        revenue=15000.0,
        cogs=10500.0,
        opex=2250.0,
        net_debt=11250.0,
        cash=750.0,
        borrowing_rate=0.17,
        dso=30.0,
        dio=180.0,
        dpo=60.0,
        demand_elasticity=-1.0,
        pass_through=0.0,
    ),
    "DISCOUNTER-CHAIN": dict(
        revenue=20000.0,
        cogs=15600.0,
        opex=3000.0,
        net_debt=2800.0,
        cash=600.0,
        borrowing_rate=0.15,
        dso=2.0,
        dio=25.0,
        dpo=40.0,
        demand_elasticity=-0.4,
        pass_through=0.8,
    ),
    "WAREHOUSE-OPERATOR": dict(
        revenue=6000.0,
        cogs=2400.0,
        opex=900.0,
        net_debt=10000.0,
        cash=500.0,
        borrowing_rate=0.15,
        dso=30.0,
        dio=0.0,
        dpo=30.0,
        demand_elasticity=-0.5,
        pass_through=0.3,
    ),
    "TELECOM-OPERATOR": dict(
        revenue=50000.0,
        cogs=25000.0,
        opex=10000.0,
        net_debt=30000.0,
        cash=4000.0,
        borrowing_rate=0.14,
        dso=40.0,
        dio=10.0,
        dpo=45.0,
        demand_elasticity=-0.3,
        pass_through=0.5,
    ),
    "SUPERMARKET-CHAIN": dict(
        revenue=40000.0,
        cogs=30400.0,
        opex=6000.0,
        net_debt=8000.0,
        cash=1500.0,
        borrowing_rate=0.15,
        dso=2.0,
        dio=30.0,
        dpo=45.0,
        demand_elasticity=-0.4,
        pass_through=0.8,
    ),
    "MEAT-PROCESSOR": dict(
        revenue=12000.0,
        cogs=9600.0,
        opex=1200.0,
        net_debt=3000.0,
        cash=300.0,
        borrowing_rate=0.15,
        dso=35.0,
        dio=25.0,
        dpo=30.0,
        demand_elasticity=-0.6,
        pass_through=0.6,
    ),
    "DAIRY-PRODUCER": dict(
        revenue=8000.0,
        cogs=6000.0,
        opex=1000.0,
        net_debt=2000.0,
        cash=200.0,
        borrowing_rate=0.15,
        dso=30.0,
        dio=15.0,
        dpo=30.0,
        demand_elasticity=-0.4,
        pass_through=0.6,
    ),
    "RESTAURANT-CHAIN": dict(
        revenue=5000.0,
        cogs=2000.0,
        opex=2250.0,
        net_debt=1500.0,
        cash=200.0,
        borrowing_rate=0.17,
        dso=1.0,
        dio=5.0,
        dpo=20.0,
        demand_elasticity=-1.3,
        pass_through=0.4,
    ),
    "APPAREL-RETAILER": dict(
        revenue=7000.0,
        cogs=3850.0,
        opex=2450.0,
        net_debt=1800.0,
        cash=300.0,
        borrowing_rate=0.17,
        dso=3.0,
        dio=120.0,
        dpo=60.0,
        demand_elasticity=-1.4,
        pass_through=0.3,
    ),
}
COMMON_STATEMENT = {"tax_rate": 0.2}
#: The share of a borrower's costs bought abroad, the part a currency shock moves.
IMPORT_SHARES = {
    "CAR-IMPORTER": 0.85,
    "DRUG-DISTRIBUTOR": 0.7,
    "ELECTRONICS-RETAILER": 0.9,
    "STEEL-EXPORTER": 0.1,
    "POTASH-EXPORTER": 0.05,
}


def loan(company, *, ead, lgd, kind="corp_loan", prefix="LOAN", **terms) -> dict:
    """A credit position in ``company``; its statement, import share and the terms."""
    return {
        "position_id": f"{prefix}-{company}",
        "party": company,
        "instrument_type": kind,
        "values": {
            "ead": ead,
            "lgd": lgd,
            "ccf": 1.0,
            "import_share": IMPORT_SHARES.get(company, 0.0),
            **COMMON_STATEMENT,
            **STATEMENTS[company],
            **terms,
        },
    }


def share(company, *, ticker, price, beta, sector, residual, dividend, quantity, **market):
    """A long position in ``company``'s ordinary shares."""
    return {
        "position_id": f"SHARE-{company}",
        "party": company,
        "instrument_type": "common_stock",
        "currency": market.pop("currency", "RUB"),
        "values": {
            "ticker": ticker,
            "market_index": market.pop("market_index", "MOEX"),
            "sector": sector,
            "quantity": quantity,
            "price": price,
            "beta_market": beta,
            "beta_sector": market.pop("beta_sector", 1.0),
            "residual_volatility": residual,
            "dividend": dividend,
            **market,
        },
    }


TELECOM_BOND = {"face_value": 1000.0, "maturity_months": 48.0, "risk_free_rate": 0.14}
SHARES = {
    "US-PHARMA": share(
        "US-PHARMA",
        ticker="USPH",
        price=150.0,
        beta=0.8,
        sector="healthcare",
        residual=0.25,
        dividend=3.0,
        quantity=50_000,
        currency="USD",
        market_index="SPX",
        fx_rate=92.5,
    ),
    "STEEL-EXPORTER": share(
        "STEEL-EXPORTER",
        ticker="STLX",
        price=120.0,
        beta=1.1,
        sector="materials",
        residual=0.3,
        dividend=5.0,
        quantity=2_000_000,
    ),
    "SUPERMARKET-CHAIN": share(
        "SUPERMARKET-CHAIN",
        ticker="SMKT",
        price=250.0,
        beta=0.9,
        sector="trade",
        residual=0.25,
        dividend=5.0,
        quantity=1_000_000,
    ),
    "COMMERCIAL-BANK": share(
        "COMMERCIAL-BANK",
        ticker="CBNK",
        price=300.0,
        beta=1.2,
        sector="financials",
        residual=0.25,
        dividend=15.0,
        quantity=1_000_000,
    ),
    "OIL-MAJOR": share(
        "OIL-MAJOR",
        ticker="OILM",
        price=500.0,
        beta=0.9,
        sector="oil_gas",
        residual=0.25,
        dividend=30.0,
        quantity=500_000,
    ),
    "IT-DEVELOPER": share(
        "IT-DEVELOPER",
        ticker="ITDV",
        price=400.0,
        beta=1.4,
        sector="technology",
        residual=0.35,
        dividend=0.0,
        quantity=300_000,
    ),
    "TELECOM-OPERATOR": share(
        "TELECOM-OPERATOR",
        ticker="TLCM",
        price=200.0,
        beta=0.7,
        sector="telecom",
        residual=0.2,
        dividend=10.0,
        quantity=1_000_000,
    ),
}

#: portfolio id -> (its name, what it shows, its editor rows)
PORTFOLIOS = {
    "CURRENCY-RISK": (
        "Валютный риск",
        "Импортёры и экспортёры, долларовая акция и акция экспортёра: курс рубля действует на "
        "них в разные стороны.",
        [
            loan("CAR-IMPORTER", ead=2000.0, lgd=0.45),
            loan("DRUG-DISTRIBUTOR", ead=1500.0, lgd=0.4),
            loan("ELECTRONICS-RETAILER", ead=1500.0, lgd=0.5),
            loan("STEEL-EXPORTER", ead=3000.0, lgd=0.4),
            loan("POTASH-EXPORTER", ead=2500.0, lgd=0.4),
            SHARES["US-PHARMA"],
            SHARES["STEEL-EXPORTER"],
        ],
    ),
    "RATE-RISK": (
        "Процентный риск",
        "Заёмщики с разной долговой нагрузкой и облигации одного эмитента с фиксированным и "
        "плавающим купоном.",
        [
            loan("LEVERAGED-DEVELOPER", ead=3000.0, lgd=0.5),
            loan("DISCOUNTER-CHAIN", ead=1500.0, lgd=0.4),
            loan("WAREHOUSE-OPERATOR", ead=2000.0, lgd=0.35),
            loan(
                "TELECOM-OPERATOR",
                ead=1000.0,
                lgd=0.6,
                kind="bond_fixed",
                prefix="BOND-FIXED",
                coupon_rate=0.15,
                coupon_frequency=2.0,
                **TELECOM_BOND,
            ),
            loan(
                "TELECOM-OPERATOR",
                ead=1000.0,
                lgd=0.6,
                kind="bond_floater",
                prefix="BOND-FLOATING",
                coupon_rate=0.155,
                coupon_frequency=4.0,
                **TELECOM_BOND,
            ),
        ],
    ),
    "CONSUMER-DEMAND": (
        "Потребительский спрос",
        "Продукты, общепит и одежда: спрос на них по-разному зависит от доходов населения.",
        [
            loan("SUPERMARKET-CHAIN", ead=2500.0, lgd=0.4),
            loan("MEAT-PROCESSOR", ead=1200.0, lgd=0.45),
            loan("DAIRY-PRODUCER", ead=1000.0, lgd=0.45),
            loan("RESTAURANT-CHAIN", ead=800.0, lgd=0.55),
            loan("APPAREL-RETAILER", ead=900.0, lgd=0.55),
            SHARES["SUPERMARKET-CHAIN"],
        ],
    ),
    "EQUITY-MARKET": (
        "Рынок акций",
        "Акции компаний разных отраслей на Московской бирже и одна американская акция.",
        [
            SHARES["COMMERCIAL-BANK"],
            SHARES["OIL-MAJOR"],
            SHARES["STEEL-EXPORTER"],
            SHARES["SUPERMARKET-CHAIN"],
            SHARES["IT-DEVELOPER"],
            SHARES["TELECOM-OPERATOR"],
            SHARES["US-PHARMA"],
        ],
    ),
}


# Building ------------------------------------------------------------------------------------


@dataclass
class CatalogContext(DraftContext):
    """Names a row's records after its company and security, not after the portfolio.

    Every typed figure is sourced to the company it describes, so two securities of one
    company state one financial statement.
    """

    companies: dict[str, str] = field(default_factory=dict)

    def issuer_id(self, position_id) -> str:
        return self.companies[position_id]

    def instrument_id(self, position_id) -> str:
        return self.instruments.get(position_id, position_id)

    def evidence(self, position_id, field, value) -> list[dict]:
        return [_evidence(f"{self.companies[position_id]}/{field}", value)]


def _evidence(locator, value) -> dict:
    return {
        "kind": "expert_assumption",
        "source_id": SOURCE,
        "locator": locator,
        "fragment_sha256": sha256(f"{locator}={value}".encode()).hexdigest(),
        "author": AUTHOR,
        "as_of": AS_OF.isoformat(),
    }


def _party(party_id) -> dict:
    company = COMPANIES[party_id]
    return {
        "party_id": party_id,
        "name": company.name,
        "kind": "company",
        "okved": company.okved,
        "country": company.country,
        "description": company.description,
        "evidence": [_evidence(party_id, company.name)],
    }


def portfolio(portfolio_id, registry) -> tuple[dict, list[dict]]:
    """The portfolio's parties, instruments and positions, and its snapshot items."""
    _, _, rows = PORTFOLIOS[portfolio_id]
    draft = PortfolioDraft(
        name=portfolio_id,
        positions=[
            {
                "position_id": row["position_id"],
                "name": f"{registry.instrument_type(row['instrument_type']).label}: "
                f"{COMPANIES[row['party']].name}",
                "instrument_type": row["instrument_type"],
                "okved": COMPANIES[row["party"]].okved,
                "currency": row.get("currency", "RUB"),
                "values": row["values"],
            }
            for row in rows
        ],
    )
    context = CatalogContext(
        author=AUTHOR,
        today=AS_OF,
        source_id=SOURCE,
        portfolio_id=portfolio_id,
        companies={row["position_id"]: row["party"] for row in rows},
    )
    bundle, snapshot = build_draft(
        draft,
        author=AUTHOR,
        today=AS_OF,
        registry=registry,
        portfolio_id=portfolio_id,
        context=context,
    )
    problems = check_bundle(bundle, registry)
    if problems:
        raise ValueError(f"{portfolio_id}: " + "; ".join(problems))
    data = bundle.model_dump(mode="json")
    # A company is described by the catalog, not by the row that first named it.
    data["parties"] = [_party(party["party_id"]) for party in data["parties"]]
    return data, snapshot.model_dump(mode="json")["items"]


def _merge(target: dict, records: list, key: str, where: str) -> None:
    for record in records:
        known = target.setdefault(record[key], record)
        if known != record:
            raise ValueError(f"{where}: two different records {record[key]}")


def outputs(registry=None) -> dict[Path, str]:
    """Every generated file and its text."""
    registry = registry or current()
    files: dict[Path, str] = {}
    parts: dict[str, dict[str, dict]] = {}
    items: dict[str, dict] = {}
    for portfolio_id, (name, description, _) in PORTFOLIOS.items():
        data, found = portfolio(portfolio_id, registry)
        header = {
            "portfolio": {
                "portfolio_id": portfolio_id,
                "name": name,
                "base_currency": "RUB",
                "as_of": AS_OF.isoformat(),
                "snapshot_id": SNAPSHOT_ID,
                "builtin": True,
                "metadata": {
                    "synthetic": True,
                    "description": description,
                    "generated_by": "demo/build_catalog.py",
                },
            }
        }
        files[CATALOG / "portfolios" / f"{portfolio_id}.json"] = _json(header)
        owner = {
            item["instrument_id"]: registry.plugin_of(item["instrument_type"]).plugin_id
            for item in data["instruments"]
        }
        by_plugin: dict[str, dict] = {}
        for position in data["positions"]:
            plugin_id = owner[position["instrument_id"]]
            part = by_plugin.setdefault(
                plugin_id, {"parties": {}, "instruments": {}, "positions": {}}
            )
            instrument = next(
                i for i in data["instruments"] if i["instrument_id"] == position["instrument_id"]
            )
            party = next(p for p in data["parties"] if p["party_id"] == instrument["issuer_id"])
            _merge(part["parties"], [party], "party_id", portfolio_id)
            _merge(part["instruments"], [instrument], "instrument_id", portfolio_id)
            _merge(part["positions"], [position], "position_id", portfolio_id)
        for plugin_id, part in by_plugin.items():
            folder = _demo_data(registry, plugin_id) / "portfolios"
            files[folder / f"{portfolio_id}.json"] = _json(
                {name: list(records.values()) for name, records in part.items()}
            )
        _merge(items, found, "item_id", portfolio_id)
    for item in items.values():
        parts.setdefault(registry.plugin_of(item["kind"]).plugin_id, {})[item["item_id"]] = item
    files[CATALOG / "snapshots" / f"{SNAPSHOT_ID}.json"] = _json(
        {
            "snapshot_id": SNAPSHOT_ID,
            "as_of": AS_OF.isoformat(),
            "label": SNAPSHOT_LABEL,
            "kind": "demo",
            "metadata": {"synthetic": True, "generated_by": "demo/build_catalog.py"},
        }
    )
    for plugin_id, found in parts.items():
        folder = _demo_data(registry, plugin_id) / "snapshots"
        files[folder / f"{SNAPSHOT_ID}.json"] = _json(
            {"items": [found[key] for key in sorted(found)]}
        )
    files[MOCK_EVENTS] = _json(mock_answers())
    return files


def mock_answers() -> dict:
    """The mock profile's answers: the prepared answer of each event, keyed by its text."""
    events = [
        json.loads(path.read_text("utf-8")) for path in sorted((CATALOG / "events").glob("*.json"))
    ]
    events.append(json.loads((CATALOG / "pilot" / "event.json").read_text("utf-8")))
    return {
        sha256(event["text"].encode("utf-8")).hexdigest(): event["mock_answer"]
        for event in sorted(events, key=lambda event: event["event_id"])
        if "mock_answer" in event
    }


def _demo_data(registry, plugin_id) -> Path:
    from importlib.resources import files

    return Path(str(files(package_of(registry.plugins[plugin_id])))) / "demo_data"


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
