"""A plugin's own versioned prompt (``Plugin.prompts``), read through ``msa.prompts.registry``."""

import pytest

from msa.cli.plugin import load
from msa.platform.registry import PluginError, installed
from msa.prompts.registry import current_version, get

INIT = """\
from msa.plugin_sdk.plugin import Plugin

plugin = Plugin(
    plugin_id="promptdemo",
    version="1.0.0",
    sdk=">=1.0,<2.0",
    label="Prompt demo",
    prompts={{{prompts}}},
)
"""


def _write_plugin(tmp_path, *, prompts, texts=()):
    """A temporary plugin package under ``tmp_path``, declaring ``prompts`` (name -> version)."""
    package = tmp_path / "promptdemo"
    package.mkdir()
    items = ", ".join(f"{name!r}: {version!r}" for name, version in prompts.items())
    (package / "__init__.py").write_text(INIT.format(prompts=items), encoding="utf-8")
    if texts:
        (package / "prompts").mkdir()
        for filename, text in texts:
            (package / "prompts" / filename).write_text(text, encoding="utf-8")
    return load(package)


def test_current_version_and_get_read_a_plugins_own_prompt_file(tmp_path):
    plugin = _write_plugin(
        tmp_path,
        prompts={"brief": "v1"},
        texts=[("brief-v1.txt", "Текст брифа v1\n")],
    )
    with installed(plugin):
        assert current_version("promptdemo.brief") == "v1"
        assert get("promptdemo.brief") == "Текст брифа v1\n"


def test_get_of_an_undeclared_prompt_name_raises_keyerror(tmp_path):
    plugin = _write_plugin(
        tmp_path,
        prompts={"brief": "v1"},
        texts=[("brief-v1.txt", "Текст брифа v1\n")],
    )
    with installed(plugin):
        with pytest.raises(KeyError):
            get("promptdemo.missing")


def test_a_declared_prompt_without_its_file_makes_installed_raise_naming_it(tmp_path):
    plugin = _write_plugin(tmp_path, prompts={"missing": "v1"})
    with pytest.raises(PluginError, match="prompt 'missing'"):
        with installed(plugin):
            pass


def test_platform_prompts_still_work_outside_any_plugin_install():
    assert current_version("causal") == "v3"
    assert get("causal")
