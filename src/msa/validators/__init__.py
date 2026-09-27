"""Deterministic validators: V1 is the contract itself, the rest are domain rules.

The dispatcher runs V1 and the rules registered for an artifact; V9 (numbers of the report)
and V11 (one shared scenario matrix) are called directly where their inputs exist.
"""

from .base import Validator, Verdict
from .dispatcher import register, validate
from .v2_units import UnitsValidator
from .v3_reach import ReachValidator
from .v7_acyclic import AcyclicValidator
from .v8_evidence import EvidenceValidator

register("V2", UnitsValidator(), ["TransmissionGraph", "PortfolioBundle"])
register("V3", ReachValidator(), ["TransmissionGraph"])
register("V7", AcyclicValidator(), ["TransmissionGraph"])
register("V8", EvidenceValidator(), ["TransmissionGraph"])

__all__ = ["Validator", "Verdict", "register", "validate"]
