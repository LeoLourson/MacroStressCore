"""Russian wording of evidence ``source_id``/``author`` (``Plugin.sources``/``authors``):
merged across plugins, and a build problem when two plugins word the same key differently."""

import pytest

from msa.platform import catalog
from msa.platform.registry import PluginError, build, registry
from msa.plugin_sdk.plugin import Plugin


def test_source_wording_has_the_credit_and_equity_demo_words():
    wording = registry().source_wording()
    assert wording["TZ-v3"] == "демо-данные техзадания"
    assert wording["demo:market"] == "рыночные данные демо-снимка"


def test_author_wording_has_the_equity_demo_desk():
    assert registry().author_wording()["demo:market-desk"] == "аналитик рынка демо-стенда"


def test_asset_types_sources_come_from_the_registrys_source_wording():
    assert catalog.asset_types()["sources"] == registry().source_wording()


def _source_plugin(plugin_id, key, text):
    return Plugin(
        plugin_id=plugin_id,
        version="1.0.0",
        sdk=">=1.0,<2.0",
        label="Extra",
        sources={key: text},
    )


def _author_plugin(plugin_id, key, text):
    return Plugin(
        plugin_id=plugin_id,
        version="1.0.0",
        sdk=">=1.0,<2.0",
        label="Extra",
        authors={key: text},
    )


def test_two_plugins_wording_one_source_identically_build_fine():
    a = _source_plugin("srca", "shared:source", "общий текст")
    b = _source_plugin("srcb", "shared:source", "общий текст")
    reg = build([a, b])
    assert reg.source_wording()["shared:source"] == "общий текст"


def test_two_plugins_wording_one_source_differently_is_a_build_problem():
    a = _source_plugin("srca", "shared:source", "текст один")
    b = _source_plugin("srcb", "shared:source", "текст два")
    with pytest.raises(PluginError, match="worded differently"):
        build([a, b])


def test_two_plugins_wording_one_author_differently_is_a_build_problem():
    a = _author_plugin("autha", "shared:author", "текст один")
    b = _author_plugin("authb", "shared:author", "текст два")
    with pytest.raises(PluginError, match="worded differently"):
        build([a, b])
