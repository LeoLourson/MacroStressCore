"""A portfolio typed in by an analyst: parties, instruments, positions and their snapshot.

The editor sends plain values per position; every number becomes an ``expert_assumption``
with the analyst as author and today as its date (TZ 1.1, principle 3), so the report can
say whose figure it is. Which values a position takes, and where each one goes — the
instrument's terms, the position, a snapshot item — is declared by its instrument type's
plugin; the editor is built from the same declaration.
"""

import re
from dataclasses import dataclass, field
from datetime import date
from hashlib import sha256

from pydantic import Field, JsonValue

from msa.contracts.common import Contract, Identifier
from msa.contracts.domain import Instrument, Party, Portfolio, PortfolioBundle, Position
from msa.contracts.snapshot import DataSnapshot
from msa.contracts.units import Currency


class DraftPosition(Contract):
    position_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$")
    name: str = Field(min_length=1, max_length=120)
    instrument_type: Identifier
    okved: str | None = Field(default=None, pattern=r"^\d{2}(\.\d{1,2}){0,2}$")
    currency: Currency = "RUB"
    values: dict[str, JsonValue] = Field(default_factory=dict)
    tables: dict[str, list[dict[str, JsonValue]]] = Field(default_factory=dict)


class PortfolioDraft(Contract):
    name: str = Field(min_length=1, max_length=80)
    base_currency: Currency = "RUB"
    positions: list[DraftPosition] = Field(min_length=1, max_length=100)


@dataclass
class DraftContext:
    """What a plugin's ``from_draft`` needs: who typed the numbers, when, and the ids."""

    author: str
    today: date
    source_id: str
    portfolio_id: str
    base_currency: str = "RUB"
    #: Position id -> its instrument; rows naming one security share it (``identity``).
    instruments: dict[str, str] = field(default_factory=dict)

    def evidence(self, position_id, field, value) -> list[dict]:
        return [
            {
                "kind": "expert_assumption",
                "source_id": self.source_id,
                "locator": f"/positions/{position_id}/{field}",
                "fragment_sha256": sha256(f"{position_id}/{field}={value}".encode()).hexdigest(),
                "author": self.author,
                "as_of": self.today.isoformat(),
            }
        ]

    def issuer_id(self, position_id) -> str:
        return f"{self.portfolio_id}:{position_id}"

    def instrument_id(self, position_id) -> str:
        return self.instruments.get(position_id, f"{self.portfolio_id}:{position_id}")


def build(draft: PortfolioDraft, *, author, today, registry, portfolio_id, context=None):
    """``(bundle, snapshot)``: the portfolio and the snapshot of the numbers typed into it.

    ``context`` names the records and their sources differently from an analyst's draft
    (the demo catalog); several rows may then name one issuer.
    """
    ids = [item.position_id for item in draft.positions]
    if len(set(ids)) != len(ids):
        raise ValueError("Position IDs must be unique within the portfolio")
    source = "analyst-portfolio:" + (re.sub(r"[^\w-]+", "-", draft.name).strip("-") or "draft")
    ctx = context or DraftContext(
        author=author,
        today=today,
        source_id=source,
        portfolio_id=portfolio_id,
        base_currency=draft.base_currency,
    )
    snapshot_id = f"{portfolio_id}:inputs"
    parties, instruments, positions, items = [], [], [], {}
    #: (type, currency, identity) -> the first row of that security and what it states.
    securities: dict[tuple, tuple[str, tuple]] = {}
    for row in draft.positions:
        try:
            spec = registry.instrument_type(row.instrument_type)
        except KeyError as exc:
            raise ValueError(f"{row.position_id}: {exc.args[0]}") from None
        if spec.from_draft is None:
            raise ValueError(f"{row.position_id}: {spec.label} cannot be typed in the editor")
        _within_bounds(row, spec)
        identity = row.values.get(spec.identity) if spec.identity else None
        key = (row.instrument_type, row.currency, identity) if identity not in (None, "") else None
        first = securities[key][0] if key in securities else row.position_id
        ctx.instruments[row.position_id] = ctx.instrument_id(first)
        parts = spec.from_draft(row.model_dump(mode="json"), ctx)
        instrument_id = ctx.instrument_id(row.position_id)
        stated = (row.okved, _plain(parts["terms"]), _plain(parts.get("items", [])))
        if key in securities:
            # Another lot of a security already typed: one instrument, one issuer, one set
            # of quotes, so its terms and data must be those of the first lot.
            if stated != securities[key][1]:
                raise ValueError(
                    f"{row.position_id}: {identity} is typed with other terms or data "
                    f"than in {first}"
                )
            positions.append(
                Position(
                    position_id=row.position_id,
                    instrument_id=instrument_id,
                    params=parts["params"],
                    schema_version=parts.get("schema_version", spec.schema_version),
                )
            )
            continue
        if key is not None:
            securities[key] = (row.position_id, stated)
        issuer_id = None
        if spec.issuer_required or row.okved:
            if spec.issuer_required and not row.okved:
                raise ValueError(f"{row.position_id}: the issuer's OKVED is required")
            issuer_id = ctx.issuer_id(row.position_id)
        if issuer_id is not None and issuer_id not in {party.party_id for party in parties}:
            parties.append(
                Party(
                    party_id=issuer_id,
                    name=row.name,
                    okved=row.okved,
                    description=f"Позиция {row.position_id} портфеля аналитика",
                    evidence=ctx.evidence(row.position_id, "issuer", row.name),
                )
            )
        instruments.append(
            Instrument(
                instrument_id=instrument_id,
                instrument_type=row.instrument_type,
                name=row.name,
                currency=row.currency,
                issuer_id=issuer_id,
                terms=parts["terms"],
                schema_version=parts.get("schema_version", spec.schema_version),
            )
        )
        positions.append(
            Position(
                position_id=row.position_id,
                instrument_id=instrument_id,
                params=parts["params"],
                schema_version=parts.get("schema_version", spec.schema_version),
            )
        )
        for item in parts.get("items", []):
            known = items.get(item["item_id"])
            if known is not None and known != item:
                raise ValueError(f"{row.position_id}: conflicting data for {item['item_id']}")
            items[item["item_id"]] = item
    _consistent(items.values())
    bundle = PortfolioBundle(
        portfolio=Portfolio(
            portfolio_id=portfolio_id,
            name=draft.name,
            base_currency=draft.base_currency,
            as_of=today,
            snapshot_id=snapshot_id,
        ),
        parties=parties,
        instruments=instruments,
        positions=positions,
    )
    snapshot = DataSnapshot(
        snapshot_id=snapshot_id,
        as_of=today,
        label=f"Данные портфеля «{draft.name}»",
        kind="analyst",
        items=[items[key] for key in sorted(items)],
        metadata={"author": author},
    )
    return bundle, snapshot


def _within_bounds(row: DraftPosition, spec) -> None:
    """The editor's bounds hold on the server too: a request need not come from the form."""
    for group in spec.editor:
        for item in group.fields:
            if item.columns:
                cells = [
                    (f"{item.name}.{column.name}", line.get(column.name), column)
                    for line in row.tables.get(item.name, [])
                    for column in item.columns
                ]
            else:
                cells = [(item.name, row.values.get(item.name), item)]
            for name, value, declared in cells:
                if isinstance(value, bool) or not isinstance(value, int | float):
                    continue
                low, high = declared.minimum, declared.maximum
                if (low is not None and value < low) or (high is not None and value > high):
                    raise ValueError(f"{row.position_id}: {name} must lie within [{low}, {high}]")


def _plain(value):
    """What a row states, without the sources that name the row that typed it."""
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items() if k != "evidence"}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def _consistent(items) -> None:
    """Two positions may not state different values of the same quote on the same day."""
    seen = {}
    for item in items:
        key = (item["kind"], item["subject"], item["observed_on"])
        values = {k: v["value"] for k, v in item["values"].items()}
        previous = seen.get(key)
        if previous is not None:
            for name in set(previous) & set(values):
                if previous[name] != values[name]:
                    raise ValueError(
                        f"conflicting {item['kind']} of {item['subject']}: "
                        f"{previous[name]} and {values[name]}"
                    )
        seen[key] = {**(previous or {}), **values}
