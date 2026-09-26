"""``msa-plugin`` (plan, stage D): scaffolds pass the conformance check as generated.

- ``new asset`` writes a package whose model, factor, metrics, editor and demo case pass
  ``check`` and calculate in ``demo-run``;
- ``new agent`` writes an agent that joins the chosen extension point, off by default,
  and every workflow still compiles with it switched on;
- a broken plugin makes ``check`` fail with the finding named;
- the installed plugins pass.
"""

import pytest

from msa.cli.plugin import check, demo_run, load, main, new_agent, new_asset


def test_an_asset_scaffold_passes_the_check_and_calculates(tmp_path):
    target = new_asset("gold", label="Золото", dest=tmp_path)
    assert sorted(p.name for p in target.iterdir()) == [
        "__init__.py",
        "demo.py",
        "editor.py",
        "model.py",
        "schemas.py",
    ]
    assert check(path=target) == []
    output = demo_run(None, path=target, points=64)
    assert "X-1  gold.model.v1  рассчитано, статус ok" in output
    assert "Срез Рыночный результат: P5 / P50 / P95" in output
    plugin = load(target)
    assert plugin.instrument_types[0].type_id == "gold_position"
    assert plugin.models[0].model_id == "gold.model.v1"


def test_an_agent_scaffold_joins_its_point_and_stays_off(tmp_path):
    target = new_agent("watcher", point="before_report", dest=tmp_path)
    assert check(path=target) == []
    (agent,) = load(target).agents
    assert agent.extends == {"stress_test": "before_report"}
    assert agent.enabled_by_default is False
    assert "report" in agent.consumes


def test_a_broken_plugin_fails_the_check(tmp_path, capsys):
    target = new_asset("broken", dest=tmp_path)
    model = target / "model.py"
    # A model that forgets a metric it promised.
    line = 'f"{PLUGIN_ID}.value_current": scalar(f"{PLUGIN_ID}.value_current", unit, value0),'
    text = model.read_text(encoding="utf-8")
    assert line in text
    model.write_text(text.replace(line, ""), encoding="utf-8")
    assert main(["check", "--path", str(target)]) == 1
    assert "broken.value_current" in capsys.readouterr().out


def test_unknown_points_and_taken_names_are_refused(tmp_path):
    with pytest.raises(SystemExit, match="no extension point"):
        new_agent("late", point="after_publication", dest=tmp_path)
    new_asset("twice", dest=tmp_path)
    with pytest.raises(SystemExit, match="already exists"):
        new_asset("twice", dest=tmp_path)
    with pytest.raises(SystemExit, match="lowercase"):
        new_asset("Bad-Name", dest=tmp_path)


def test_the_installed_plugins_pass():
    assert main(["check"]) == 0


def test_the_ui_manifest_is_current():
    """The web build checks its UI plugins against this file: regenerate it with
    ``msa-plugin ui-manifest`` when a plugin's version or view components change."""
    import json

    from msa.cli.plugin import UI_MANIFEST, ui_manifest

    assert json.loads(UI_MANIFEST.read_text(encoding="utf-8")) == ui_manifest()
