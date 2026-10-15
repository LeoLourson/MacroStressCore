"""The documentation of the mathematics: the platform's pages and those each plugin carries
(``Plugin.docs``), served by ``GET /v1/docs``. Formulas are checked in KaTeX at the UI build
(``ui/web/scripts/check-math.mjs``)."""

import re

import pytest

from msa.cli.plugin import load
from msa.platform.docs import PLATFORM, documentation
from msa.platform.registry import PluginError, installed, registry

INIT = """\
from msa.plugin_sdk.plugin import Plugin

plugin = Plugin(
    plugin_id="docdemo",
    version="1.0.0",
    sdk=">=1.2,<2.0",
    label="Doc demo",
    docs=({docs}),
)
"""


def _write_plugin(tmp_path, docs, texts=()):
    package = tmp_path / "docdemo"
    package.mkdir()
    (package / "__init__.py").write_text(
        INIT.format(docs="".join(f"{name!r}, " for name in docs)), encoding="utf-8"
    )
    if texts:
        (package / "docs").mkdir()
        for filename, text in texts:
            (package / "docs" / filename).write_text(text, encoding="utf-8")
    return load(package)


def test_the_platform_pages_come_first_then_every_plugin_that_carries_docs():
    docs = documentation()
    assert [page["slug"] for page in docs["platform"]] == [n.removesuffix(".md") for n in PLATFORM]
    carriers = sorted(p.plugin_id for p in registry().plugins.values() if p.docs)
    assert [group["plugin_id"] for group in docs["plugins"]] == carriers
    assert {"credit", "equity", "market", "research"} <= set(carriers)
    credit = next(group for group in docs["plugins"] if group["plugin_id"] == "credit")
    assert credit["version"] == registry().plugins["credit"].version
    assert [page["slug"] for page in credit["pages"]][:2] == ["trajectory", "pd"]


def test_every_page_has_a_title_and_balanced_formulas_without_its_title_line():
    docs = documentation()
    pages = docs["platform"] + [page for group in docs["plugins"] for page in group["pages"]]
    for page in pages:
        assert page["title"] and not page["markdown"].startswith("# ")
        text = re.sub(r"`[^`]*`", "", page["markdown"])
        assert text.count("$") % 2 == 0, page["slug"]


def test_a_plugin_page_is_read_from_the_docs_folder_of_its_package(tmp_path):
    plugin = _write_plugin(tmp_path, ["model.md"], [("model.md", "# Модель\n\nЦена $P = 1$.\n")])
    with installed(plugin):
        (group,) = [g for g in documentation()["plugins"] if g["plugin_id"] == "docdemo"]
    assert group["pages"] == [{"slug": "model", "title": "Модель", "markdown": "Цена $P = 1$."}]


def test_a_declared_page_without_its_file_blocks_the_plugin(tmp_path):
    plugin = _write_plugin(tmp_path, ["absent.md"])
    with pytest.raises(PluginError, match="doc 'absent.md'"):
        with installed(plugin):
            pass


def test_a_page_without_a_title_line_blocks_the_plugin(tmp_path):
    plugin = _write_plugin(tmp_path, ["page.md"], [("page.md", "Без заголовка\n")])
    with pytest.raises(PluginError, match="doc 'page.md'"):
        with installed(plugin):
            pass
