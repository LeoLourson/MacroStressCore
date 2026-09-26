"""Every registered plugin passes the platform's conformance check on its own demo cases."""

import pytest

from msa.platform.registry import registry
from msa.plugin_sdk.testing import check_plugin


@pytest.mark.parametrize("plugin_id", sorted(registry().plugins))
def test_plugin_conforms(plugin_id):
    findings = check_plugin(registry().plugins[plugin_id])
    assert [str(f) for f in findings] == []


def test_asset_plugins_ship_demo_cases():
    for plugin in registry().plugins.values():
        if plugin.instrument_types:
            assert plugin.demo is not None and plugin.demo(), plugin.plugin_id
