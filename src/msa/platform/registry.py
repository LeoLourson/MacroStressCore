"""Discovery and validation of plugins, and the catalogs everything else reads.

At start-up the built-in ``core`` declaration (``msa.workflows``) and every package under
``msa.plugins`` are imported and their ``plugin`` declarations checked. The checks are
all-or-nothing: the process does not start with a partial set of plugins, and the error
lists every problem with the plugin that caused it.

Nothing outside ``msa.plugins`` branches on an instrument type: the dispatcher, the
aggregator, the report, the API and the screens find what they need here.
"""

import importlib
import inspect
import pkgutil
import sys
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import RLock

from msa.contracts.domain import PositionContext
from msa.contracts.units import is_unit
from msa.plugin_sdk.mcp import McpServerSpec
from msa.plugin_sdk.model import CalculationModel
from msa.plugin_sdk.plugin import PLUGIN_ID, Plugin
from msa.plugin_sdk.specs import (
    BASE_MONEY,
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
from msa.plugin_sdk.version import SDK_VERSION, compatible, parse

PACKAGE = "msa.plugins"
#: The platform's own workflows and core agents: declared like a plugin, part of the core.
BUILT_IN = "msa.workflows"
CORE = "core"


class PluginError(RuntimeError):
    """The declared plugins are inconsistent; the message lists every problem."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("Plugins cannot be loaded:\n- " + "\n- ".join(problems))


class UnknownInstrumentType(KeyError):
    pass


class UnknownModel(KeyError):
    pass


@dataclass
class Registry:
    plugins: dict[str, Plugin] = field(default_factory=dict)
    instrument_types: dict[str, InstrumentTypeSpec] = field(default_factory=dict)
    models: dict[str, CalculationModel] = field(default_factory=dict)
    metrics: dict[str, MetricSpec] = field(default_factory=dict)
    factors: dict[str, FactorSpec] = field(default_factory=dict)
    slices: dict[str, SliceSpec] = field(default_factory=dict)
    snapshot_kinds: dict[str, SnapshotKindSpec] = field(default_factory=dict)
    views: dict[str, ResultView] = field(default_factory=dict)
    report_sections: dict[str, ReportSection] = field(default_factory=dict)
    rules: dict[str, RecommendationRule] = field(default_factory=dict)
    actions: dict[str, ActionSpec] = field(default_factory=dict)
    observations: dict[str, object] = field(default_factory=dict)
    agents: dict[str, object] = field(default_factory=dict)
    workflows: dict[str, object] = field(default_factory=dict)
    mcp_servers: dict[str, McpServerSpec] = field(default_factory=dict)
    #: Server name -> its tools by name, as ``register`` defines them.
    mcp_tools: dict[str, dict[str, Callable]] = field(default_factory=dict)
    #: Which plugin declared each identifier, for messages and the catalog.
    owner: dict[str, str] = field(default_factory=dict)

    # Lookups -------------------------------------------------------------------------

    def instrument_type(self, type_id: str) -> InstrumentTypeSpec:
        try:
            return self.instrument_types[type_id]
        except KeyError:
            raise UnknownInstrumentType(
                f"no plugin declares instrument type {type_id!r}; "
                f"registered: {', '.join(sorted(self.instrument_types)) or 'none'}"
            ) from None

    def model(self, model_id: str) -> CalculationModel:
        try:
            return self.models[model_id]
        except KeyError:
            raise UnknownModel(f"no plugin declares model {model_id!r}") from None

    def model_for(self, context: PositionContext) -> CalculationModel:
        """The position's explicitly chosen model, otherwise its type's default."""
        spec = self.instrument_type(context.instrument.instrument_type)
        model = self.model(context.position.model_id or spec.default_model)
        if spec.type_id not in model.instrument_types:
            raise UnknownModel(f"model {model.model_id} does not calculate {spec.type_id}")
        return model

    def plugin_of(self, identifier: str) -> Plugin:
        return self.plugins[self.owner[identifier]]

    def models_for_type(self, type_id: str) -> list[CalculationModel]:
        return [m for m in self.models.values() if type_id in m.instrument_types]

    def view_for(self, type_id: str) -> ResultView | None:
        return next((v for v in self.views.values() if type_id in v.instrument_types), None)

    def flag_wording(self) -> dict[str, str]:
        wording: dict[str, str] = {}
        for plugin in self.plugins.values():
            wording.update(plugin.flags)
        return wording

    def source_wording(self) -> dict[str, str]:
        """Evidence ``source_id`` -> its words, as the plugins declare them."""
        return {key: text for p in self.plugins.values() for key, text in p.sources.items()}

    def author_wording(self) -> dict[str, str]:
        """Evidence ``author`` -> its words, as the plugins declare them."""
        return {key: text for p in self.plugins.values() for key, text in p.authors.items()}

    def review_flags(self) -> frozenset[str]:
        return frozenset().union(*(m.review_flags for m in self.models.values()))

    def run_options(self, scope: str) -> dict:
        options: dict = {}
        for plugin in self.plugins.values():
            if plugin.run_options is not None:
                options.update(plugin.run_options(scope))
        return options

    def versions(self) -> dict[str, str]:
        """Plugin id -> version: what a run records about the code it ran on."""
        return {"sdk": SDK_VERSION} | {
            plugin_id: plugin.version for plugin_id, plugin in sorted(self.plugins.items())
        }


def build(plugins: Iterable[Plugin]) -> Registry:
    """Check the declarations together and index them; raise ``PluginError`` on any problem."""
    registry = Registry()
    problems: list[str] = []
    plugins = list(plugins)

    def claim(kind: str, identifier: str, plugin: Plugin, index: dict, value, *, spaced=True):
        where = f"{plugin.plugin_id}: {kind} {identifier!r}"
        if spaced and not plugin.namespaced(identifier):
            problems.append(f"{where} must start with {plugin.plugin_id + '.'!r}")
        if identifier in index:
            problems.append(
                f"{where} is already declared by {registry.owner[kind + ':' + identifier]}"
            )
            return
        index[identifier] = value
        registry.owner[kind + ":" + identifier] = plugin.plugin_id
        registry.owner[identifier] = plugin.plugin_id

    for plugin in plugins:
        if not PLUGIN_ID.match(plugin.plugin_id):
            problems.append(f"plugin id {plugin.plugin_id!r} must be lower_snake_case")
        if plugin.plugin_id in registry.plugins:
            problems.append(f"plugin {plugin.plugin_id!r} is declared twice")
            continue
        try:
            parse(plugin.version)
        except ValueError:
            problems.append(f"{plugin.plugin_id}: version {plugin.version!r} is not x.y.z")
        try:
            if not compatible(plugin.sdk):
                problems.append(
                    f"{plugin.plugin_id}: requires SDK {plugin.sdk}, platform has {SDK_VERSION}"
                )
        except ValueError as exc:
            problems.append(f"{plugin.plugin_id}: sdk range {plugin.sdk!r}: {exc}")
        registry.plugins[plugin.plugin_id] = plugin

        for spec in plugin.instrument_types:
            claim(
                "instrument type",
                spec.type_id,
                plugin,
                registry.instrument_types,
                spec,
                spaced=False,
            )
        for model in plugin.models:
            claim("model", model.model_id, plugin, registry.models, model)
        for spec in plugin.metrics:
            claim("metric", spec.metric_id, plugin, registry.metrics, spec)
            if spec.unit != BASE_MONEY and not is_unit(spec.unit):
                problems.append(f"{plugin.plugin_id}: metric {spec.metric_id} unit {spec.unit!r}")
        for spec in plugin.factors:
            claim("factor", spec.factor_id, plugin, registry.factors, spec)
        for spec in plugin.slices:
            claim("slice", spec.slice_id, plugin, registry.slices, spec)
            if not 0 <= spec.coverage_limit <= 1:
                problems.append(f"{plugin.plugin_id}: slice {spec.slice_id} coverage limit")
        for spec in plugin.snapshot_kinds:
            claim("snapshot kind", spec.kind, plugin, registry.snapshot_kinds, spec, spaced=False)
        for spec in plugin.views:
            claim("view", spec.view_id, plugin, registry.views, spec)
        for spec in plugin.report_sections:
            claim("report section", spec.section_id, plugin, registry.report_sections, spec)
        for name, observe in plugin.observations.items():
            claim("observation", name, plugin, registry.observations, observe)
        for spec in plugin.rules:
            claim("rule", spec.rule_id, plugin, registry.rules, spec)
        for spec in plugin.actions:
            claim("action", spec.action_id, plugin, registry.actions, spec, spaced=False)
        for agent in plugin.agents:
            claim("agent", agent.agent_id, plugin, registry.agents, agent)
        for workflow in plugin.workflows:
            claim(
                "workflow", workflow.workflow_id, plugin, registry.workflows, workflow, spaced=False
            )
        for spec in plugin.mcp_servers:
            # The platform's own servers keep their short names: mcp-models, mcp-runs, ...
            spaced = plugin.plugin_id != CORE
            claim("mcp server", spec.name, plugin, registry.mcp_servers, spec, spaced=spaced)
            tools, found = mcp_tools(spec)
            registry.mcp_tools[spec.name] = tools
            problems.extend(f"{plugin.plugin_id}: {problem}" for problem in found)
        for name, version in plugin.prompts.items():
            if prompt_file(plugin, name, version) is None:
                problems.append(
                    f"{plugin.plugin_id}: prompt {name!r} {version} has no file "
                    f"prompts/{name}-{version}.txt in the plugin's package"
                )

        for name in plugin.docs:
            if doc_title(plugin, name) is None:
                problems.append(
                    f"{plugin.plugin_id}: doc {name!r} is not a file docs/{name} of the "
                    "plugin's package starting with a '# ' title"
                )

    # Words of evidence sources and authors are shared: a disagreement is a problem.
    for kind, attribute in (("source", "sources"), ("author", "authors")):
        worded: dict[str, tuple[str, str]] = {}
        for plugin in plugins:
            for key, text in getattr(plugin, attribute).items():
                first = worded.setdefault(key, (plugin.plugin_id, text))
                if first[1] != text:
                    problems.append(
                        f"{plugin.plugin_id}: {kind} {key!r} is worded differently by {first[0]}"
                    )

    # Cross-references are checked once every plugin is indexed.
    for type_id, spec in registry.instrument_types.items():
        model = registry.models.get(spec.default_model)
        if model is None:
            problems.append(
                f"instrument type {type_id}: default model {spec.default_model!r} is not declared"
            )
        elif type_id not in model.instrument_types:
            problems.append(
                f"instrument type {type_id}: default model {model.model_id} does not calculate it"
            )
    for model_id, model in registry.models.items():
        where = f"model {model_id}"
        if not getattr(model, "version", None):
            problems.append(f"{where} has no version")
        for type_id in model.instrument_types:
            if type_id not in registry.instrument_types:
                problems.append(f"{where} calculates undeclared instrument type {type_id!r}")
        for metric in (*model.metrics, *model.required_metrics):
            if metric not in registry.metrics:
                problems.append(f"{where} reports undeclared metric {metric!r}")
        if set(model.required_metrics) - set(model.metrics):
            problems.append(f"{where}: required metrics must be among its metrics")
        for slice_id in model.slices:
            if slice_id not in registry.slices:
                problems.append(f"{where} contributes to undeclared slice {slice_id!r}")
        for factor in model.factors:
            if factor not in registry.factors:
                problems.append(f"{where} reads undeclared factor {factor!r}")
    for rule_id, rule in registry.rules.items():
        if rule.observation not in registry.observations:
            problems.append(f"rule {rule_id} reads undeclared observation {rule.observation!r}")
        for action in rule.actions:
            if action not in registry.actions:
                problems.append(f"rule {rule_id} recommends undeclared action {action!r}")
    for view_id, view in registry.views.items():
        for type_id in view.instrument_types:
            if type_id not in registry.instrument_types:
                problems.append(f"view {view_id} shows undeclared instrument type {type_id!r}")
        for block in view.blocks:
            for metric in block.metric_ids:
                if metric not in registry.metrics:
                    problems.append(f"view {view_id} shows undeclared metric {metric!r}")
        for metric in view.summary_metrics:
            if metric not in registry.metrics:
                problems.append(f"view {view_id} shows undeclared metric {metric!r}")
    if problems:
        raise PluginError(problems)
    return registry


def mcp_tools(spec: McpServerSpec) -> tuple[dict[str, Callable], list[str]]:
    """The server's tools as ``register`` defines them, and what is wrong with them.

    ``register`` runs with a recording decorator and no services: it only defines functions.
    Each tool must take ``audit`` (the gateway's call context) for the audit to record it.
    """
    tools: dict[str, Callable] = {}

    def record(fn):
        tools[fn.__name__] = fn
        return fn

    try:
        spec.register(record, None)
    except Exception as exc:  # noqa: BLE001 - a broken server must name itself
        return {}, [f"mcp server {spec.name!r} cannot list its tools: {type(exc).__name__}: {exc}"]
    problems = [
        f"mcp server {spec.name!r}: tool {name} has no `audit` parameter"
        for name, fn in tools.items()
        if "audit" not in inspect.signature(fn).parameters
    ]
    if not tools:
        problems.append(f"mcp server {spec.name!r} defines no tools")
    return tools, problems


def package_of(plugin: Plugin) -> str:
    """The package that declares ``plugin``: where its prompts and demo data live.

    An installed plugin is ``msa.plugins.<id>`` (the core ``msa.workflows``); a plugin loaded
    from a folder under development has the module name it was loaded under.
    """
    module = next(
        (m for m in list(sys.modules.values()) if getattr(m, "plugin", None) is plugin), None
    )
    return getattr(module, "__name__", f"{PACKAGE}.{plugin.plugin_id}")


def prompt_file(plugin: Plugin, name: str, version: str):
    """The text of a plugin's prompt, ``prompts/<name>-<version>.txt`` of its package."""
    from importlib.resources import files

    try:
        path = files(package_of(plugin)).joinpath("prompts", f"{name}-{version}.txt")
    except ModuleNotFoundError:
        return None
    return path if path.is_file() else None


def doc_file(plugin: Plugin, name: str):
    """A page of a plugin's documentation, ``docs/<name>`` of its package."""
    from importlib.resources import files

    try:
        path = files(package_of(plugin)).joinpath("docs", name)
    except ModuleNotFoundError:
        return None
    return path if path.is_file() else None


def doc_title(plugin: Plugin, name: str) -> str | None:
    """The ``# `` title on the first line of a documentation page; ``None`` without one."""
    path = doc_file(plugin, name)
    if path is None:
        return None
    first = path.read_text(encoding="utf-8").partition("\n")[0]
    return first[2:].strip() if first.startswith("# ") and first[2:].strip() else None


def discover(package: str = PACKAGE) -> list[Plugin]:
    """The built-in ``core`` declaration, then every plugin package under ``package``."""
    root = importlib.import_module(package)
    names = [BUILT_IN] + [
        f"{package}.{info.name}"
        for info in sorted(pkgutil.iter_modules(root.__path__), key=lambda item: item.name)
        if not info.name.startswith("_")
    ]
    plugins, problems = [], []
    for name in names:
        try:
            module = importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001 - a broken plugin must name itself
            problems.append(f"{name} cannot be imported: {type(exc).__name__}: {exc}")
            continue
        declared = getattr(module, "plugin", None)
        if not isinstance(declared, Plugin):
            problems.append(f"{name} exports no `plugin = Plugin(...)` declaration")
            continue
        plugins.append(declared)
    if problems:
        raise PluginError(problems)
    return plugins


_LOCK = RLock()
_CURRENT: Registry | None = None


def registry() -> Registry:
    """The process registry, discovered on first use and kept for the process lifetime."""
    global _CURRENT
    with _LOCK:
        if _CURRENT is None:
            _CURRENT = build(discover())
        return _CURRENT


@contextmanager
def installed(*extra: Plugin) -> Iterator[Registry]:
    """The discovered plugins plus ``extra`` as the process registry, for tests and checks."""
    global _CURRENT
    with _LOCK:
        previous = _CURRENT
        current = build([*discover(), *extra])
        _CURRENT = current
    try:
        yield current
    finally:
        with _LOCK:
            _CURRENT = previous
