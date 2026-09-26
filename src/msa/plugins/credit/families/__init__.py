"""The credit families and the instrument types each of them serves."""

from ..family import CreditFamily
from .bond import Bond
from .corporate import CorporateLoan
from .leasing import LeasingCompany
from .project_finance import ProjectFinance

FAMILIES: tuple[CreditFamily, ...] = (CorporateLoan(), Bond(), ProjectFinance(), LeasingCompany())

_BY_TYPE: dict[str, CreditFamily] = {}
for _family in FAMILIES:
    for _type in _family.types:
        if _type in _BY_TYPE:
            raise ValueError(f"credit type {_type!r} is served by two families")
        _BY_TYPE[_type] = _family
    for _name in (*_family.decision_metrics, *(item.name for item in _family.covenant_metrics)):
        if _name not in {item.name for item in _family.series}:
            raise ValueError(f"{type(_family).__name__} reports {_name!r} but declares no series")


def family_for(asset_type: str) -> CreditFamily:
    try:
        return _BY_TYPE[asset_type]
    except KeyError:
        raise KeyError(f"no credit family serves {asset_type!r}") from None


def asset_types() -> tuple[str, ...]:
    return tuple(_BY_TYPE)


__all__ = ["FAMILIES", "asset_types", "family_for"]
