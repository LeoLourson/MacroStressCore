"""Resolving a model's data requirements against a data snapshot, as of the valuation date.

For each requirement the latest item of its kind and subject dated no later than ``as_of``
is taken; an item dated after ``as_of`` is never used, and when only such items exist the
requirement is reported ``dated_after_as_of`` rather than silently missing. Peers are the
statements of other parties whose activity matches the party's OKVED branch, deepest match
first — the same ranking as before the platform, now bounded by the valuation date.
"""

from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import date

from msa.contracts.snapshot import SnapshotItem
from msa.plugin_sdk.model import DataRequirement, DataRequirements

from .okved import okved_depth

MISSING = "missing"
DATED_AFTER_AS_OF = "dated_after_as_of"


class SnapshotIndex:
    """Items of one snapshot by kind and subject."""

    def __init__(self, snapshot_id: str, items: Iterable[SnapshotItem]):
        self.snapshot_id = snapshot_id
        self._by_key: dict[tuple[str, str], list[SnapshotItem]] = defaultdict(list)
        self._by_kind: dict[str, set[str]] = defaultdict(set)
        for item in items:
            self._by_key[item.kind, item.subject].append(item)
            self._by_kind[item.kind].add(item.subject)

    def subjects(self, kind: str) -> set[str]:
        return set(self._by_kind.get(kind, ()))

    def candidates(self, kind: str, subject: str) -> list[SnapshotItem]:
        return list(self._by_key.get((kind, subject), ()))


def _rank(requirement: DataRequirement):
    order = {value: index for index, value in enumerate(requirement.prefer_order)}

    def key(item: SnapshotItem):
        preference = (0, "")
        if requirement.prefer_attribute is not None:
            value = str(item.attributes.get(requirement.prefer_attribute, ""))
            preference = (order.get(value, len(order)), value)
        # Latest date first; on the same date the preferred attribute value, then the id.
        return (-item.observed_on.toordinal(), preference, item.item_id)

    return key


def latest(index: SnapshotIndex, requirement: DataRequirement, subject: str, as_of: date):
    """The item to use, or ``(None, reason)``."""
    candidates = index.candidates(requirement.kind, subject)
    usable = [item for item in candidates if item.observed_on <= as_of]
    if not usable:
        return None, (DATED_AFTER_AS_OF if candidates else MISSING)
    return sorted(usable, key=_rank(requirement))[0], None


def resolve(
    requirements: DataRequirements,
    index: SnapshotIndex,
    *,
    as_of: date,
    sector_of: Callable[[str], str | None],
) -> tuple[dict, dict]:
    """``(data, missing)``: resolved items by requirement key, and why others are absent.

    ``missing`` names every unresolved requirement, required or not; the model decides what
    an absent optional input means, the platform only says why it is absent.
    """
    data: dict = {}
    missing: dict[str, str] = {}
    for requirement in requirements.data:
        if requirement.subject is not None:
            item, reason = latest(index, requirement, requirement.subject, as_of)
            data[requirement.key] = ([item] if item else []) if requirement.many else item
            if item is None:
                missing[requirement.key] = reason
            continue
        if requirement.subjects is not None:
            subjects = list(dict.fromkeys(requirement.subjects))
        else:
            subjects = peers(index, requirement, sector_of)
        found = []
        for subject in subjects:
            item, _ = latest(index, requirement, subject, as_of)
            if item is not None:
                found.append(item)
            if len(found) >= requirement.limit:
                break
        data[requirement.key] = found
        if not found:
            missing[requirement.key] = MISSING
    return data, missing


def peers(index: SnapshotIndex, requirement: DataRequirement, sector_of) -> list[str]:
    """Other parties of the same OKVED branch with items of the kind, deepest match first."""
    own = sector_of(requirement.peers_of)
    if not own:
        return []
    ranked = []
    for subject in index.subjects(requirement.kind):
        if subject == requirement.peers_of:
            continue
        sector = sector_of(subject)
        depth = okved_depth(sector, own) if sector else 0
        if depth:
            ranked.append((-depth, subject))
    return [subject for _, subject in sorted(ranked)]
