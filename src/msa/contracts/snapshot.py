"""A data snapshot: the quotes, exchange rates, statements and assumptions a run reads.

A snapshot is fixed: once imported, its items do not change, and its content hash says so.
Every item names what it describes (``subject``) and the date its values refer to
(``observed_on``); nothing dated after the snapshot's ``as_of`` may enter it, and a run
rejects items dated after its own valuation date.
"""

import json
from datetime import date
from hashlib import sha256

from pydantic import Field, JsonValue, model_validator

from .common import Contract, Identifier, Sha256
from .evidence import Evidence, Parameter


class SnapshotItem(Contract):
    item_id: Identifier
    kind: Identifier
    #: A party, instrument, currency pair (``USD/RUB``) or curve (``risk_free:RUB``).
    subject: Identifier
    observed_on: date
    values: dict[Identifier, Parameter] = Field(default_factory=dict)
    #: Non-numeric facts about the item: reporting standard, audit, method, author.
    attributes: dict[str, JsonValue] = Field(default_factory=dict)
    evidence: list[Evidence] = Field(default_factory=list)


class DataSnapshot(Contract):
    snapshot_id: Identifier
    as_of: date
    label: Identifier
    #: ``market`` (imported feeds), ``analyst`` (typed in the editor) or ``demo``.
    kind: Identifier = "market"
    items: list[SnapshotItem] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def dated_and_unique(self):
        ids = [item.item_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("snapshot item ids must be unique")
        late = [item.item_id for item in self.items if item.observed_on > self.as_of]
        if late:
            raise ValueError(f"items dated after the snapshot as_of: {', '.join(sorted(late))}")
        return self

    @property
    def sha256(self) -> Sha256:
        return content_hash(self)


def content_hash(snapshot: DataSnapshot) -> str:
    payload = snapshot.model_dump(mode="json", exclude={"metadata"})
    payload["items"] = sorted(payload["items"], key=lambda item: item["item_id"])
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(text.encode("utf-8")).hexdigest()
