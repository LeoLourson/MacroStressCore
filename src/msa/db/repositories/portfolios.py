"""Portfolios with their parties, instruments and positions.

A bundle is checked before it is written: references resolve, every instrument type is
registered, and terms and position parameters satisfy their plugin's versioned schema.
"""

from datetime import date

from sqlalchemy import delete, or_, select

from msa.contracts.domain import (
    Instrument,
    Party,
    Portfolio,
    PortfolioBundle,
    Position,
    contexts,
)
from msa.db.base import utcnow
from msa.db.models import tables_for

from .common import upsert


class PortfolioProblem(ValueError):
    """The bundle does not satisfy its plugins' schemas; ``problems`` lists why."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("; ".join(problems))


def check_bundle(bundle: PortfolioBundle, registry) -> list[str]:
    from msa.engine.dispatch import schema_problems

    problems = []
    for context in contexts(bundle):
        for item in schema_problems(context, registry):
            problems.append(f"{context.position_id}{item.path}: {item.message or item.code}")
    return problems


class PortfoliosRepository:
    def __init__(self, session):
        self.session = session
        self.tables = tables_for(session)

    # Writing ---------------------------------------------------------------------------

    def save_bundle(self, bundle: PortfolioBundle, *, registry, owned=False, expires_at=None):
        """Write a portfolio and what it refers to; ``owned`` instruments go with it."""
        bundle = PortfolioBundle.model_validate(bundle)
        problems = check_bundle(bundle, registry)
        if problems:
            raise PortfolioProblem(problems)
        portfolio = bundle.portfolio
        for party in bundle.parties:
            upsert(self.session, self.tables["party"], party.model_dump(mode="json"))
        for instrument in bundle.instruments:
            values = instrument.model_dump(mode="json")
            values["owner_portfolio_id"] = portfolio.portfolio_id if owned else None
            upsert(self.session, self.tables["instrument"], values)
        upsert(
            self.session,
            self.tables["portfolio"],
            {
                **portfolio.model_dump(mode="json", exclude={"as_of"}),
                "as_of": portfolio.as_of,
                "expires_at": expires_at,
            },
        )
        table = self.tables["position"]
        self.session.execute(delete(table).where(table.c.portfolio_id == portfolio.portfolio_id))
        for position in bundle.positions:
            upsert(
                self.session,
                table,
                {**position.model_dump(mode="json"), "portfolio_id": portfolio.portfolio_id},
            )

    def delete_portfolio(self, portfolio_id):
        row = self._portfolio(portfolio_id, include_expired=True)
        if row["builtin"]:
            raise PermissionError("Built-in portfolios cannot be deleted")
        for name in ("position", "portfolio"):
            table = self.tables[name]
            self.session.execute(delete(table).where(table.c.portfolio_id == portfolio_id))
        instrument = self.tables["instrument"]
        owned = list(
            self.session.execute(
                select(instrument.c.instrument_id, instrument.c.issuer_id).where(
                    instrument.c.owner_portfolio_id == portfolio_id
                )
            ).all()
        )
        self.session.execute(
            delete(instrument).where(instrument.c.owner_portfolio_id == portfolio_id)
        )
        # Parties private to the upload go when no instrument refers to them any more.
        party = self.tables["party"]
        issuers = [issuer for _, issuer in owned if issuer]
        if issuers:
            self.session.execute(
                delete(party).where(
                    party.c.party_id.in_(issuers),
                    ~party.c.party_id.in_(
                        select(instrument.c.issuer_id).where(instrument.c.issuer_id.is_not(None))
                    ),
                )
            )

    # Reading ---------------------------------------------------------------------------

    def _portfolio(self, portfolio_id, *, include_expired=False):
        table = self.tables["portfolio"]
        row = (
            self.session.execute(select(table).where(table.c.portfolio_id == portfolio_id))
            .mappings()
            .first()
        )
        if row is None:
            raise KeyError(portfolio_id)
        expires_at = row["expires_at"]
        if expires_at is not None and not include_expired:
            from datetime import UTC

            expires_at = expires_at.replace(tzinfo=UTC) if expires_at.tzinfo is None else expires_at
            if expires_at <= utcnow():
                raise KeyError(portfolio_id)
        return row

    def exists(self, portfolio_id) -> bool:
        try:
            self._portfolio(portfolio_id)
        except KeyError:
            return False
        return True

    def list_portfolios(self, *, now=None):
        table = self.tables["portfolio"]
        position = self.tables["position"]
        rows = self.session.execute(
            select(table)
            .where(or_(table.c.expires_at.is_(None), table.c.expires_at > (now or utcnow())))
            .order_by(table.c.portfolio_id)
        ).mappings()
        result = []
        for row in rows:
            count = len(
                self.session.execute(
                    select(position.c.position_id).where(
                        position.c.portfolio_id == row["portfolio_id"]
                    )
                ).all()
            )
            result.append({**dict(row), "positions": count})
        return result

    def get_bundle(self, portfolio_id) -> PortfolioBundle:
        row = dict(self._portfolio(portfolio_id))
        portfolio = Portfolio.model_validate(
            {key: row[key] for key in Portfolio.model_fields if key in row}
        )
        position = self.tables["position"]
        positions = [
            Position.model_validate({k: v for k, v in dict(r).items() if k != "portfolio_id"})
            for r in self.session.execute(
                select(position)
                .where(position.c.portfolio_id == portfolio_id)
                .order_by(position.c.position_id)
            ).mappings()
        ]
        instrument = self.tables["instrument"]
        ids = sorted({p.instrument_id for p in positions})
        instruments = [
            Instrument.model_validate(
                {k: v for k, v in dict(r).items() if k != "owner_portfolio_id"}
            )
            for r in self.session.execute(
                select(instrument)
                .where(instrument.c.instrument_id.in_(ids))
                .order_by(instrument.c.instrument_id)
            ).mappings()
        ]
        issuers = sorted({i.issuer_id for i in instruments if i.issuer_id})
        party = self.tables["party"]
        parties = [
            Party.model_validate(dict(r))
            for r in self.session.execute(
                select(party).where(party.c.party_id.in_(issuers)).order_by(party.c.party_id)
            ).mappings()
        ]
        return PortfolioBundle(
            portfolio=portfolio, parties=parties, instruments=instruments, positions=positions
        )

    def valuation_date(self, portfolio_id) -> date | None:
        return self._portfolio(portfolio_id)["as_of"]

    def names(self, portfolio_id) -> dict[str, str]:
        """Position id -> what a person calls it: the issuer, else the instrument."""
        bundle = self.get_bundle(portfolio_id)
        names = {}
        for position in bundle.positions:
            instrument = bundle.instrument(position.instrument_id)
            issuer = bundle.party(instrument.issuer_id)
            names[position.position_id] = issuer.name if issuer else instrument.name
        return names

    def sectors(self) -> dict[str, str | None]:
        """Party id -> OKVED, for peer selection by the snapshot resolver."""
        table = self.tables["party"]
        return dict(self.session.execute(select(table.c.party_id, table.c.okved)).all())

    def save_parties(self, parties):
        for party in parties:
            upsert(
                self.session,
                self.tables["party"],
                Party.model_validate(party).model_dump(mode="json"),
            )
