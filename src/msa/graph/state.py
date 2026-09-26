import operator
from typing import Annotated, TypedDict

from msa.contracts import Report, SourceDocument
from msa.contracts.common import Seed
from msa.contracts.graph import TransmissionGraph

from .reducers import collect_branch_results, merge_extensions


class RunState(TypedDict, total=False):
    """The core state of the stress-test workflow; JSON projections of the contracts.

    Plugin agents never add keys here: each writes to its own namespace of ``extensions``.
    """

    run_id: str
    text: str
    as_of: str
    seed: Seed
    mc_points: int
    horizon: int
    mode: str
    status: str
    errors: list[str]
    attempts: int
    graph_revision: int
    verdicts: list[dict]
    v11_verdicts: list[dict]
    #: What the run is fixed to.
    portfolio_id: str
    snapshot_id: str
    base_currency: str
    #: Every position of the portfolio, and those the approved scenario reaches.
    portfolio_positions: list[dict]
    positions: list[dict]
    #: Position id -> why the scenario reaches it.
    reach: dict
    #: Position id -> prepared inputs and the model's verdict on them.
    prepared: dict
    diagnostics: dict
    #: Position id -> what a person calls it.
    position_names: dict[str, str]
    #: The approved scenario set: its specification, identity and the shared matrix hash.
    scenario_set: dict
    scenario_id: str
    macro_draws_sha256: str
    branch_position_id: str
    sorted_results: list[dict]
    portfolio_result: dict | None
    request_graph_review: bool
    trace: Annotated[list[str], operator.add]
    document: SourceDocument | dict
    graph: TransmissionGraph | dict
    event_passport: dict
    event_parameters: dict
    # Proposed by the causal agent from the scenario words, then confirmed by the analyst.
    macro_parameters: dict
    scenario_confirmed: bool
    scenario_required: bool
    # Results of the position branches, and their realisations (never persisted).
    position_results: Annotated[list[dict], collect_branch_results]
    position_draws: Annotated[list[dict], collect_branch_results]
    report: Report | dict
    # The risk manager's negative decision: outcome, reason, author and time.
    decision: dict
    published: bool
    #: Agent plugins' own outputs, one namespace per agent id.
    extensions: Annotated[dict, merge_extensions]
