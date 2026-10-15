"""Synthetic portfolios and events, written as compactly as the checks need them.

A portfolio is a list of editor rows: the same path an analyst takes in the portfolio
editor (``msa.api.portfolio_draft.build``), so every number becomes a sourced assumption and
the snapshot is built by the plugins' ``from_draft``. An event is its text, the economic
graph the analyst confirms (event -> channel -> sector -> factor, or channel -> direct
factor) and the scenario parameters.
"""

from dataclasses import dataclass, field
from datetime import date

from msa.api.portfolio_draft import PortfolioDraft
from msa.api.portfolio_draft import build as build_draft
from msa.contracts import DataSnapshot, PortfolioBundle
from msa.db.repositories.portfolios import check_bundle
from msa.platform.registry import registry

AS_OF = date(2026, 9, 11)
AUTHOR = "sanity:synthetic"

#: A healthy operating company, RUB million a year: EBITDA 1800 (15 % margin), net debt
#: 2.5x EBITDA, ICR about 2.6. Every working-capital and pricing input is stated, so the
#: model does not fall back to its own assumptions.
BORROWER = {
    "revenue": 12000.0,
    "cogs": 8400.0,
    "opex": 1800.0,
    "net_debt": 4500.0,
    "cash": 500.0,
    "borrowing_rate": 0.14,
    "dso": 45.0,
    "dio": 30.0,
    "dpo": 30.0,
    "tax_rate": 0.2,
    "demand_elasticity": -1.0,
    "pass_through": 0.0,
}
OPERATING = ("corp_loan", "bond_fixed", "bond_floater")


def loan(position_id, okved, *, ead=1000.0, lgd=0.45, kind="corp_loan", name=None, **values):
    """A credit position; operating companies start from ``BORROWER``, changed by ``values``."""
    figures = {**(BORROWER if kind in OPERATING else {}), **values}
    covenants = figures.pop("covenants", None)
    row = {
        "position_id": position_id,
        "name": name or f"Заёмщик {position_id}",
        "instrument_type": kind,
        "okved": okved,
        "currency": "RUB",
        "values": {"ead": ead, "lgd": lgd, **figures},
    }
    if covenants:
        row["tables"] = {"covenants": covenants}
    return row


def share(
    position_id,
    okved,
    *,
    quantity=1_000_000,
    price=100.0,
    beta_market=1.0,
    beta_sector=0.0,
    residual=0.0,
    dividend=0.0,
    currency="RUB",
    fx_rate=None,
    market_index="MOEX",
    sector=None,
    ticker=None,
    name=None,
):
    """An ordinary share; ``residual`` is the annual residual volatility as a fraction."""
    values = {
        "quantity": quantity,
        "ticker": ticker or position_id,
        "market_index": market_index,
        "price": price,
        "beta_market": beta_market,
        "beta_sector": beta_sector,
        "residual_volatility": residual,
        "dividend": dividend,
    }
    if sector is not None:
        values["sector"] = sector
    if fx_rate is not None:
        values["fx_rate"] = fx_rate
    return {
        "position_id": position_id,
        "name": name or f"Акция {position_id}",
        "instrument_type": "common_stock",
        "okved": okved,
        "currency": currency,
        "values": values,
    }


def portfolio(portfolio_id, rows) -> tuple[PortfolioBundle, DataSnapshot]:
    """The bundle and snapshot of the editor rows, refused as the API refuses to save them."""
    draft = PortfolioDraft(name=portfolio_id, base_currency="RUB", positions=rows)
    bundle, snapshot = build_draft(
        draft, author=AUTHOR, today=AS_OF, registry=registry(), portfolio_id=portfolio_id
    )
    problems = check_bundle(bundle, registry())
    if problems:
        raise ValueError("; ".join(problems))
    return bundle, snapshot


# Events ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Link:
    """A graph path channel -> sector (OKVED) -> factor of the ``graph`` scope.

    ``exposure`` is the channel -> sector share, ``elasticity`` the sector -> factor
    magnitude (a number, or a triangular ``(low, mode, high)``), ``sign`` its direction and
    ``lag`` its delay in months. ``shared_factor`` joins every sector of the factor into one
    factor node, instead of one node per (OKVED, factor) the causal prompt asks for.
    """

    channel: str
    okved: str
    factor: str
    sign: int = 1
    exposure: float = 1.0
    elasticity: float | tuple[float, float, float] = 1.0
    lag: int = 0
    shared_factor: bool = False


@dataclass(frozen=True)
class Direct:
    """A descriptive path channel -> direct factor with its key (index, pair, sector key)."""

    channel: str
    factor: str
    key: str


@dataclass
class Event:
    event_id: str
    text: str
    links: list[Link] = field(default_factory=list)
    direct: list[Direct] = field(default_factory=list)
    #: name -> scenario parameter (``ScenarioParameter`` without evidence).
    scenario: dict[str, dict] = field(default_factory=dict)
    event_type: str = "Синтетическое событие"

    def graph(self, evidence) -> dict:
        nodes = {"event": {"id": "event", "kind": "event", "label": "событие"}}
        edges = []

        def edge(src, dst, *, sign=1, elasticity=1.0, lag=0):
            if isinstance(elasticity, tuple):
                low, mode, high = elasticity
                spec = {"family": "triangular", "low": low, "mode": mode, "high": high}
            else:
                spec = {"family": "point", "value": elasticity}
            edges.append(
                {
                    "src": src,
                    "dst": dst,
                    "sign": sign,
                    "elasticity": spec,
                    "lag_months": lag,
                    "evidence": evidence,
                }
            )

        def channel(name):
            if name not in nodes:
                nodes[name] = {"id": name, "kind": "channel", "label": name}
                edge("event", name)

        for link in self.links:
            channel(link.channel)
            sector = f"{link.channel}__{link.okved.replace('.', '_')}"
            if sector not in nodes:
                nodes[sector] = {
                    "id": sector,
                    "kind": "sector",
                    "label": link.okved,
                    "okved": link.okved,
                }
                edge(link.channel, sector, elasticity=link.exposure)
            suffix = "" if link.shared_factor else "__" + link.okved.replace(".", "_")
            factor = link.factor.replace(".", "_") + suffix
            if factor not in nodes:
                nodes[factor] = {
                    "id": factor,
                    "kind": "factor",
                    "label": link.factor,
                    "factor": link.factor,
                }
            edge(sector, factor, sign=link.sign, elasticity=link.elasticity, lag=link.lag)
        for item in self.direct:
            channel(item.channel)
            name = f"{item.factor}__{item.key}".replace(".", "_").replace("/", "_")
            if name not in nodes:
                nodes[name] = {
                    "id": name,
                    "kind": "factor",
                    "label": item.factor,
                    "factor": item.factor,
                    "key": item.key,
                }
            edge(item.channel, name)
        return {
            "event_id": "event",
            "nodes": list(nodes.values()),
            "edges": edges,
            "factor_elasticity": {},
        }

    @property
    def okved(self) -> list[str]:
        return sorted({link.okved for link in self.links})


def shock(
    channel, factor, *, low=None, mode=None, high=None, value=None, unit="fraction", key=None
):
    """A scenario parameter: a point ``value`` or a triangular ``low``/``mode``/``high``."""
    spec = {"label": f"{factor} через {channel}", "unit": unit, "factor": factor}
    if channel is not None:
        spec["channel"] = channel
    if key is not None:
        spec["key"] = key
    if value is not None:
        spec.update(kind="point", value=value)
    else:
        spec.update(kind="triangular", low=low, mode=mode, high=high)
    return spec
