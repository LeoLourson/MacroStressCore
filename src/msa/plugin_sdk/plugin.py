"""The declaration a plugin module exports: everything it adds, in one object.

A plugin is a package under ``msa.plugins`` with a module-level ``plugin = Plugin(...)``.
The platform discovers it at start-up; a duplicate identifier, an incompatible SDK range or
an inconsistent declaration blocks start-up with a message that names the plugin.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .mcp import McpServerSpec
from .model import CalculationModel
from .specs import (
    ActionSpec,
    FactorSpec,
    InstrumentTypeSpec,
    MetricSpec,
    RecommendationRule,
    ReportSection,
    ResultView,
    SliceSpec,
    SnapshotKindSpec,
)

PLUGIN_ID = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class DemoCase:
    """A self-contained case the conformance check calculates: a bundle, its snapshot, a
    scenario and, for ``graph`` factors, an economic graph."""

    name: str
    bundle: Any
    snapshot: Any
    scenario: dict[str, dict]
    graph: dict | None = None
    #: Position ids the case must calculate to ``completed``.
    completes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Plugin:
    plugin_id: str
    version: str
    #: SDK versions the plugin works with, e.g. ``">=1.0,<2.0"``.
    sdk: str
    label: str
    description: str = ""
    instrument_types: tuple[InstrumentTypeSpec, ...] = ()
    models: tuple[CalculationModel, ...] = ()
    metrics: tuple[MetricSpec, ...] = ()
    factors: tuple[FactorSpec, ...] = ()
    slices: tuple[SliceSpec, ...] = ()
    snapshot_kinds: tuple[SnapshotKindSpec, ...] = ()
    views: tuple[ResultView, ...] = ()
    report_sections: tuple[ReportSection, ...] = ()
    #: observation name -> ``fn(result) -> (value, metric_path) | None``.
    observations: dict[str, Callable] = field(default_factory=dict)
    rules: tuple[RecommendationRule, ...] = ()
    actions: tuple[ActionSpec, ...] = ()
    #: Russian wording of the plugin's flags; a key ending in ``:`` covers a prefix and may
    #: hold ``{}`` for the part after it.
    flags: dict[str, str] = field(default_factory=dict)
    #: Flags that describe the data rather than a limitation of the calculation.
    informational_flags: frozenset[str] = frozenset()
    #: Russian words for the ``source_id`` of the evidence the plugin's data cites (its demo
    #: data, its reference documents), without digits (V9): the report and the screens say
    #: them instead of the identifier. Two plugins may word the same source only identically.
    sources: dict[str, str] = field(default_factory=dict)
    #: The same for the ``author`` of the evidence.
    authors: dict[str, str] = field(default_factory=dict)
    #: ``fn(result, context) -> dict``: the keyed view of a result's ``details`` the report
    #: cites (covenants by id, contributions by channel, derived values).
    tree: Callable | None = None
    #: ``fn(run_options) -> dict``: what the report states about the plugin's setting in
    #: force (the calibration a namespace calculates with).
    notes: Callable | None = None
    agents: tuple[Any, ...] = ()
    workflows: tuple[Any, ...] = ()
    #: Read-only MCP servers whose tools the plugin's agents call (``msa.plugin_sdk.mcp``).
    mcp_servers: tuple[McpServerSpec, ...] = ()
    #: Prompt name -> its version in force, e.g. ``{"brief": "v1"}``: the text is
    #: ``prompts/<name>-<version>.txt`` in the plugin's package, read with
    #: ``msa.prompts.registry.get("<plugin_id>.<name>")``.
    prompts: dict[str, str] = field(default_factory=dict)
    #: Options a run of each namespace passes to the plugin's models.
    run_options: Callable[[str], dict] | None = None
    demo: Callable[[], list[DemoCase]] | None = None
    #: Agent plugins that are not enabled by default join a workflow only when configured.
    enabled_by_default: bool = True

    def namespaced(self, identifier: str) -> bool:
        return identifier.startswith(self.plugin_id + ".")
