"""What the API serves about the registered plugins: one catalog for screens, report and MCP.

Labels of instrument types, their fields, series, metrics, factors, slices, flags and
actions come from here; the browser app keeps no dictionary of its own.
"""

import os
from dataclasses import fields, is_dataclass

from msa.contracts.units import CURRENCIES, PLAIN_UNITS
from msa.plugin_sdk.version import SDK_VERSION

from .registry import registry as current


def _plain(value):
    """A declaration as JSON: dataclasses to dicts, classes and callables left out."""
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: _plain(getattr(value, item.name))
            for item in fields(value)
            if not callable(getattr(value, item.name)) or is_dataclass(getattr(value, item.name))
        }
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple | frozenset | set):
        return [_plain(item) for item in value]
    if isinstance(value, type):
        return None
    return value


def enabled_agents() -> set[str]:
    """Agent plugins turned on for every run of this deployment (``MSA_AGENT_PLUGINS``)."""
    return {item.strip() for item in os.getenv("MSA_AGENT_PLUGINS", "").split(",") if item.strip()}


def asset_types(registry=None) -> dict:
    from msa.reporting import wording

    registry = registry or current()
    types = []
    for type_id, spec in registry.instrument_types.items():
        plugin = registry.plugins[registry.owner["instrument type:" + type_id]]
        view = registry.view_for(type_id)
        models = registry.models_for_type(type_id)
        types.append(
            {
                "asset_type": type_id,
                "label": spec.label,
                "description": spec.description,
                "plugin_id": plugin.plugin_id,
                "plugin_version": plugin.version,
                "schema_version": spec.schema_version,
                "issuer_required": spec.issuer_required,
                "default_model": spec.default_model,
                "models": [
                    {"model_id": m.model_id, "version": m.version, "label": m.label} for m in models
                ],
                "terms_schema": spec.terms_schema.model_json_schema(),
                "position_schema": spec.position_schema.model_json_schema(),
                "editor": [_plain(group) for group in spec.editor],
                "metrics": sorted({metric for m in models for metric in m.metrics}),
                "factors": sorted({factor for m in models for factor in m.factors}),
                "slices": sorted({slice_id for m in models for slice_id in m.slices}),
                "view": _plain(view) if view else None,
            }
        )
    return {
        "sdk_version": SDK_VERSION,
        "plugins": [
            {
                "plugin_id": plugin.plugin_id,
                "version": plugin.version,
                "label": plugin.label,
                "description": plugin.description,
            }
            for plugin in registry.plugins.values()
        ],
        "types": types,
        "metrics": {key: _plain(spec) for key, spec in registry.metrics.items()},
        "factors": {key: _plain(spec) for key, spec in registry.factors.items()},
        "slices": {key: _plain(spec) for key, spec in registry.slices.items()},
        "actions": {key: spec.label for key, spec in registry.actions.items()},
        "rules": {key: _plain(spec) for key, spec in registry.rules.items()},
        # The platform's own flags first; a plugin's wording of the same code wins, as in reports.
        "flags": {**wording.PLATFORM_FLAGS, **registry.flag_wording()},
        "units": {"plain": sorted(PLAIN_UNITS), "currencies": sorted(CURRENCIES)},
        "sources": registry.source_wording(),
        "authors": registry.author_wording(),
    }


def models(registry=None) -> list[dict]:
    from msa.engine.catalog import describe_model

    registry = registry or current()
    result = []
    for model_id in sorted(registry.models):
        item = describe_model(model_id, registry=registry)
        item.pop("input_schema", None)
        details = registry.models[model_id].details_schema
        item["details_schema"] = details.model_json_schema() if details is not None else None
        result.append(item)
    return result


def factors(registry=None) -> list[dict]:
    registry = registry or current()
    return [
        {**_plain(spec), "plugin_id": registry.owner.get("factor:" + key)}
        for key, spec in registry.factors.items()
    ]


def slices(registry=None) -> list[dict]:
    registry = registry or current()
    return [
        {**_plain(spec), "plugin_id": registry.owner.get("slice:" + key)}
        for key, spec in registry.slices.items()
    ]


def workflows(registry=None, enabled=None) -> list[dict]:
    from msa.graph.compiler import describe

    registry = registry or current()
    enabled = enabled_agents() if enabled is None else enabled
    optional = [
        {
            "agent_id": agent.agent_id,
            "version": agent.version,
            "label": agent.label,
            "description": agent.description,
            "extends": dict(agent.extends),
            "enabled": agent.enabled_by_default or agent.agent_id in enabled,
        }
        for agent in registry.agents.values()
        if not agent.core
    ]
    return [
        {**describe(spec, registry, enabled), "agents": optional}
        for spec in registry.workflows.values()
    ]
