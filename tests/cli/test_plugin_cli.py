"""``msa-plugin``: scaffolds pass the conformance check as generated.

- ``new asset`` writes a package whose model, factor, metrics, editor and demo case pass
  ``check`` and calculate in ``demo-run``;
- ``new agent`` writes an agent that joins the chosen extension point, off by default,
  with its own MCP tool, prompt and UI view, and every workflow still compiles with it;
- a broken plugin makes ``check`` fail with the finding named;
- the installed plugins pass.
"""

import pytest

from msa.cli.plugin import check, demo_run, load, main, new_agent, new_asset


def test_an_asset_scaffold_passes_the_check_and_calculates(tmp_path):
    target = new_asset("scaffoldgold", label="Золото", dest=tmp_path)
    assert sorted(p.name for p in target.iterdir()) == [
        "README.md",
        "__init__.py",
        "demo.py",
        "demo_data",
        "editor.py",
        "model.py",
        "schemas.py",
        "tests",
    ]
    assert (target / "tests" / "test_scaffoldgold.py").is_file()
    assert (target / "demo_data" / "README.md").is_file()
    assert check(path=target) == []
    output = demo_run(None, path=target, points=64)
    assert "X-1  scaffoldgold.model.v1  рассчитано, статус ok" in output
    assert "Срез Рыночный результат: P5 / P50 / P95" in output
    plugin = load(target)
    assert plugin.instrument_types[0].type_id == "scaffoldgold_position"
    assert plugin.models[0].model_id == "scaffoldgold.model.v1"


def test_an_agent_scaffold_joins_its_point_and_stays_off(tmp_path):
    target = new_agent("scaffoldwatcher", point="before_report", dest=tmp_path)
    assert check(path=target) == []
    plugin = load(target)
    (agent,) = plugin.agents
    assert agent.extends == {"stress_test": "before_report"}
    assert agent.enabled_by_default is False
    assert "report" in agent.consumes
    # It calls its own read-only MCP tool, has a prompt, tests and a view of its output.
    assert agent.tools == ("scaffoldwatcher.notes.summarize",)
    assert [server.name for server in plugin.mcp_servers] == ["scaffoldwatcher.notes"]
    assert plugin.prompts == {"note": "v1"}
    assert (target / "prompts" / "note-v1.txt").is_file()
    assert (target / "tests" / "test_scaffoldwatcher.py").is_file()
    ui = tmp_path / "ui" / "scaffoldwatcher"
    assert sorted(p.name for p in ui.iterdir()) == ["index.tsx", "plugin.json"]
    assert '"agents": ["scaffoldwatcher.agent"]' in (ui / "plugin.json").read_text(encoding="utf-8")


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
