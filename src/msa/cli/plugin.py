"""``msa-plugin``: scaffold, check and try out plugins.

::

  msa-plugin new asset <plugin_id> [--type-id ID] [--label TEXT] [--dest DIR]
  msa-plugin new agent <plugin_id> [--workflow ID] [--point ID] [--label TEXT] [--dest DIR]
  msa-plugin check [<plugin_id> | --path DIR]
  msa-plugin demo-run <plugin_id> [--path DIR] [--points N] [--seed N]
  msa-plugin ui-manifest [--out PATH]

``new`` writes a package that already passes ``check``: an asset plugin with a model, a
factor, metrics, an editor form and a demo case; an agent plugin joining an extension
point. By default it goes to ``src/msa/plugins/<plugin_id>``, where the platform discovers
it on the next start. ``check`` runs the conformance check (``msa.plugin_sdk.testing``) and
compiles every workflow with the plugin's agents enabled; it exits with 1 on any finding.
``demo-run`` calculates the plugin's demo cases and prints P5/P50/P95 per position and slice.
``ui-manifest`` writes what the web UI's build checks its UI plugins against
(``ui/web/src/plugins/manifest.json``): the installed plugins, their versions and the view
components they declare.
"""

import argparse
import importlib.util
import json
import keyword
import re
import sys
from contextlib import nullcontext
from datetime import date
from importlib.resources import files
from pathlib import Path

PLUGINS = Path(__file__).resolve().parents[1] / "plugins"
UI_MANIFEST = (
    Path(__file__).resolve().parents[3] / "ui" / "web" / "src" / "plugins" / "manifest.json"
)
_ID = re.compile(r"^[a-z][a-z0-9_]*$")


def _template(kind: str, name: str) -> str:
    return files("msa.cli").joinpath("templates", kind, name).read_text(encoding="utf-8")


def _render(text: str, values: dict) -> str:
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    if "{{" in text:
        raise ValueError(f"unfilled placeholder in template: {text[text.index('{{') :][:40]}")
    return text


def _target(plugin_id: str, dest: str | None) -> Path:
    if not _ID.match(plugin_id) or keyword.iskeyword(plugin_id):
        raise SystemExit(f"plugin id must be a lowercase Python identifier, got {plugin_id!r}")
    target = (Path(dest) if dest else PLUGINS) / plugin_id
    if target.exists():
        raise SystemExit(f"{target} already exists")
    return target


def new_asset(plugin_id, *, type_id=None, label=None, dest=None) -> Path:
    target = _target(plugin_id, dest)
    type_id = type_id or f"{plugin_id}_position"
    if not _ID.match(type_id):
        raise SystemExit(f"type id must be lowercase letters, digits and _, got {type_id!r}")
    values = {
        "plugin_id": plugin_id,
        "type_id": type_id,
        "label": label or plugin_id,
        "type_label": label or type_id,
    }
    target.mkdir(parents=True)
    for name in ("__init__", "schemas", "model", "editor", "demo"):
        text = _render(_template("asset", f"{name}.py.tmpl"), values)
        (target / f"{name}.py").write_text(text, encoding="utf-8")
    return target


def new_agent(
    plugin_id, *, workflow="stress_test", point="after_calculation", label=None, dest=None
) -> Path:
    from msa.platform.registry import registry

    target = _target(plugin_id, dest)
    spec = registry().workflows.get(workflow)
    if spec is None:
        raise SystemExit(f"unknown workflow {workflow!r}; known: {sorted(registry().workflows)}")
    found = next((p for p in spec.extension_points if p.point_id == point), None)
    if found is None:
        known = [p.point_id for p in spec.extension_points]
        raise SystemExit(f"{workflow} has no extension point {point!r}; known: {known}")
    values = {
        "plugin_id": plugin_id,
        "agent_id": f"{plugin_id}.agent",
        "label": label or plugin_id,
        "workflow": workflow,
        "point": point,
        "consumes": repr(tuple(found.available)),
    }
    target.mkdir(parents=True)
    text = _render(_template("agent", "__init__.py.tmpl"), values)
    (target / "__init__.py").write_text(text, encoding="utf-8")
    return target


def load(path: Path):
    """The ``plugin`` of a package outside ``msa.plugins`` (a plugin being developed)."""
    path = Path(path).resolve()
    name = f"msa_plugin_{path.name}"
    spec = importlib.util.spec_from_file_location(
        name, path / "__init__.py", submodule_search_locations=[str(path)]
    )
    if spec is None or spec.loader is None:
        raise SystemExit(f"{path} is not a Python package")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module.plugin


def _chosen(plugin_id, path):
    """The plugin to work on and the registry it is judged in."""
    from msa.platform.registry import installed, registry

    if path:
        plugin = load(path)
        return plugin, installed(plugin)
    if plugin_id not in registry().plugins:
        raise SystemExit(f"no installed plugin {plugin_id!r}; known: {sorted(registry().plugins)}")
    return registry().plugins[plugin_id], nullcontext(registry())


def check(plugin_id=None, *, path=None) -> list[str]:
    from msa.graph.compiler import check as check_workflow
    from msa.platform.registry import registry
    from msa.plugin_sdk.testing import check_plugin

    if plugin_id is None and path is None:
        plugins, scope = list(registry().plugins.values()), nullcontext(registry())
    else:
        plugin, scope = _chosen(plugin_id, path)
        plugins = [plugin]
    problems = []
    with scope as reg:
        for plugin in plugins:
            problems += [str(f) for f in check_plugin(plugin, reg)]
            # Every workflow must still compile with the plugin's agents switched on.
            agents = [a.agent_id for a in plugin.agents if not a.core]
            for workflow in reg.workflows.values():
                problems += [
                    f"{plugin.plugin_id} workflow {workflow.workflow_id}: {problem}"
                    for problem in check_workflow(workflow, reg, agents)
                ]
    return list(dict.fromkeys(problems))


def demo_run(plugin_id, *, path=None, points=256, seed=20260911) -> str:
    from msa.contracts.domain import contexts
    from msa.contracts.graph import TransmissionGraph
    from msa.engine.aggregation import aggregate_slices
    from msa.engine.runner import run_batch
    from msa.reporting.wording import EXECUTION, flag

    plugin, scope = _chosen(plugin_id, path)
    if plugin.demo is None:
        raise SystemExit(f"{plugin.plugin_id} has no demo case")
    lines = []
    with scope as reg:
        wording = reg.flag_wording()
        for case in plugin.demo():
            as_of = case.bundle.portfolio.as_of or case.snapshot.as_of or date.today()
            sectors = {party.party_id: party.okved for party in case.bundle.parties}
            graph = None if case.graph is None else TransmissionGraph.model_validate(case.graph)
            batch = run_batch(
                contexts(case.bundle),
                case.snapshot,
                case.scenario,
                graph,
                as_of=as_of,
                horizon=12,
                seed=seed,
                registry=reg,
                sector_of=sectors.get,
                points=points,
                replicates=8,
                options=reg.run_options("demo"),
            )
            lines.append(
                f"# {case.name}: позиций {len(batch.results)}, дата оценки {as_of}, "
                f"scenario_id {batch.realisations.scenario_id[:12]}…"
            )
            for result in batch.results:
                lines.append(
                    f"{result.position_id}  {result.model_id}  "
                    f"{EXECUTION[result.execution]}, статус {result.status}"
                )
                for metric_id, value in sorted(result.metrics.items()):
                    label = reg.metrics[metric_id].label if metric_id in reg.metrics else metric_id
                    if value.quantiles is not None:
                        q = value.quantiles
                        text = f"P5 / P50 / P95 = {q.p05:.4g} / {q.p50:.4g} / {q.p95:.4g}"
                    else:
                        text = f"{value.value:.4g}"
                    lines.append(f"    {label}: {text} {value.unit}")
                for code in result.flags:
                    lines.append(f"    ! {flag(code, wording)}")
            portfolio = aggregate_slices(
                f"demo-{case.name}",
                batch.results,
                draws=batch.draws,
                exposures=batch.exposures,
                registry=reg,
                base_currency=case.bundle.portfolio.base_currency,
                as_of=as_of,
                horizon=12,
                seed=seed,
                scenario_id=batch.realisations.scenario_id,
                macro_draws_sha256=batch.realisations.macro_draws_sha256,
            )
            for slice_id, item in sorted(portfolio.slices.items()):
                label = reg.slices[slice_id].label
                if item.loss_quantiles is None:
                    lines.append(f"Срез {label}: итог не рассчитан, статус {item.status}")
                    continue
                q = item.loss_quantiles
                lines.append(
                    f"Срез {label}: P5 / P50 / P95 = {q.p05:.4g} / {q.p50:.4g} / {q.p95:.4g} "
                    f"{item.unit}; ES95 {item.expected_shortfall_95:.4g}; покрытие "
                    f"{item.coverage.covered_share:.0%}; статус {item.status}"
                )
    return "\n".join(lines)


def ui_manifest() -> dict:
    """The server side of the UI plugins' compatibility check."""
    from msa.platform.registry import registry
    from msa.plugin_sdk.version import SDK_VERSION

    reg = registry()
    return {
        "generated_by": "msa-plugin ui-manifest",
        "sdk_version": SDK_VERSION,
        "plugins": {pid: plugin.version for pid, plugin in sorted(reg.plugins.items())},
        "components": {
            view.component: reg.owner["view:" + view.view_id]
            for view in sorted(reg.views.values(), key=lambda v: v.view_id)
            if view.component
        },
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="msa-plugin", description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    new = commands.add_parser("new", help="scaffold a plugin package")
    kinds = new.add_subparsers(dest="kind", required=True)
    asset = kinds.add_parser("asset", help="an asset type with its model")
    asset.add_argument("plugin_id")
    asset.add_argument("--type-id")
    asset.add_argument("--label")
    asset.add_argument("--dest")
    agent = kinds.add_parser("agent", help="an agent joining a workflow's extension point")
    agent.add_argument("plugin_id")
    agent.add_argument("--workflow", default="stress_test")
    agent.add_argument("--point", default="after_calculation")
    agent.add_argument("--label")
    agent.add_argument("--dest")
    checking = commands.add_parser("check", help="conformance of one plugin or all")
    checking.add_argument("plugin_id", nargs="?")
    checking.add_argument("--path")
    demo = commands.add_parser("demo-run", help="calculate a plugin's demo cases")
    demo.add_argument("plugin_id", nargs="?")
    demo.add_argument("--path")
    demo.add_argument("--points", type=int, default=256)
    demo.add_argument("--seed", type=int, default=20260911)
    manifest = commands.add_parser("ui-manifest", help="write the UI plugins' manifest")
    manifest.add_argument("--out", default=str(UI_MANIFEST))
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        # Russian labels survive a Windows pipe.
        sys.stdout.reconfigure(encoding="utf-8")

    if args.command == "new":
        if args.kind == "asset":
            target = new_asset(
                args.plugin_id, type_id=args.type_id, label=args.label, dest=args.dest
            )
        else:
            target = new_agent(
                args.plugin_id,
                workflow=args.workflow,
                point=args.point,
                label=args.label,
                dest=args.dest,
            )
        print(f"created {target}")
        where = f" --path {target}" if args.dest else f" {args.plugin_id}"
        print(f"next: msa-plugin check{where}")
        return 0
    if args.command == "ui-manifest":
        text = json.dumps(ui_manifest(), ensure_ascii=False, indent=2)
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"written {args.out}")
        return 0
    if args.command == "check":
        problems = check(args.plugin_id, path=args.path)
        for problem in problems:
            print(problem)
        print("ok" if not problems else f"{len(problems)} problem(s)")
        return 1 if problems else 0
    if args.plugin_id is None and args.path is None:
        parser.error("demo-run needs a plugin id or --path")
    print(demo_run(args.plugin_id, path=args.path, points=args.points, seed=args.seed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
