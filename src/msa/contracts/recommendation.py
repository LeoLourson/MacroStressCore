from pydantic import Field

from .common import Contract, Identifier


class Recommendation(Contract):
    """An action a plugin's rule chose for a position, citing the number it fired on."""

    position_id: Identifier
    #: A registered action (``msa.plugin_sdk.ActionSpec``).
    action: Identifier
    #: A registered rule, e.g. ``credit.R1``.
    rule_id: Identifier
    metric_refs: list[Identifier] = Field(min_length=1)
    approved_by: Identifier | None = None
