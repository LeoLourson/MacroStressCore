"""Calculation capabilities of the platform a plugin's model may use.

The functions live in the core (``msa.engine``) and are the same ones the platform runs
with; the SDK only hands them out. A plugin imports them from here, never from
``msa.engine``: this module is the stable surface, the engine's layout is not. A capability
a plugin needs and does not find here is a request to extend the SDK.

- Scenario: ``ScenarioSet`` (the joint realisations of a run), ``edge_elasticities`` (the
  realisations of the graph's uncertain edge elasticities, drawn with the run seed),
  ``estimate`` and ``DEFAULT_TOLERANCES`` (a quantity's mean and error interval across
  replicates).
- The economic graph: ``factor_signal`` (a scenario parameter through the event's graph to
  a factor node of the position's sector, month by month), ``factor_change`` (the signal as
  the factor's relative change) and ``NO_PATH_FLAG`` (the parameter does not reach it).
- Domains: ``check_domain`` and ``NON_NEGATIVE_DAYS`` (a flag, not a silent clip, when a
  shocked quantity leaves its domain).
- Statistics: ``expected_shortfall``; attribution: ``shapley_exact`` (exact Shapley values of
  a few players) and ``shapley_contributions`` (exact or by permutations, with half-widths).
- The result: ``data_quality_level`` (a score to the platform's levels), ``worst`` (the
  weakest of result statuses) and ``code_sha256`` (the hash of the running code).
"""

from msa.engine.dispatch import data_quality_level
from msa.engine.graph_adapter import NO_PATH_FLAG
from msa.engine.graph_signal import factor_change, factor_signal
from msa.engine.portfolio import expected_shortfall
from msa.engine.scenario_set import ScenarioSet, edge_elasticities
from msa.engine.scenarios import DEFAULT_TOLERANCES, estimate
from msa.engine.shapley import contributions as shapley_contributions
from msa.engine.shapley import exact as shapley_exact
from msa.engine.status import worst
from msa.engine.transmission import NON_NEGATIVE_DAYS, check_domain
from msa.version import code_sha256

__all__ = [
    "DEFAULT_TOLERANCES",
    "NON_NEGATIVE_DAYS",
    "NO_PATH_FLAG",
    "ScenarioSet",
    "check_domain",
    "code_sha256",
    "data_quality_level",
    "edge_elasticities",
    "estimate",
    "expected_shortfall",
    "factor_change",
    "factor_signal",
    "shapley_contributions",
    "shapley_exact",
    "worst",
]
