"""Versioned prompts: the platform's own in ``templates/``, a plugin's in its package.

A plugin's prompt is named ``<plugin_id>.<name>``: its version in force is declared in
``Plugin.prompts`` and its text is ``prompts/<name>-<version>.txt`` of the plugin's package
(the registry refuses a declared prompt without its file).
"""

import json
from importlib.resources import files

_CURRENT = {"causal": "v7", "advisory": "v2", "explain": "v2"}
_KNOWN = {name: {version} for name, version in _CURRENT.items()}
_KNOWN["causal"].add("v6")


def _plugin_prompt(name: str):
    """``(plugin, short name)`` of a plugin's prompt, or ``None`` for a platform prompt."""
    plugin_id, dot, short = name.partition(".")
    if not dot:
        return None
    from msa.platform.registry import registry

    plugin = registry().plugins.get(plugin_id)
    if plugin is None or short not in plugin.prompts:
        raise KeyError(name)
    return plugin, short


def current_version(name: str) -> str:
    found = _plugin_prompt(name)
    if found is not None:
        plugin, short = found
        return plugin.prompts[short]
    return _CURRENT[name]


def get(name: str, version: str | None = None) -> str:
    version = version or current_version(name)
    found = _plugin_prompt(name)
    if found is not None:
        from msa.platform.registry import prompt_file

        path = prompt_file(*found, version)
        if path is None:
            raise KeyError((name, version))
        return path.read_text(encoding="utf-8")
    if name not in _CURRENT or version not in _KNOWN[name]:
        raise KeyError((name, version))
    return (
        files("msa.prompts.templates").joinpath(f"{name}-{version}.txt").read_text(encoding="utf-8")
    )


def _describe(violation):
    if isinstance(violation, dict):
        return " ".join(
            str(violation[key]) for key in ("rule_id", "path", "message") if violation.get(key)
        )
    return str(violation)


def messages_for(
    name: str,
    document_text: str,
    *,
    version=None,
    violations=(),
    doc_id=None,
    okved_scope=(),
    graph_factors=(),
    direct_factors=(),
    portfolio_context=None,
):
    """``graph_factors``: (id, label, description); ``direct_factors``: (id, key, label)."""
    instructions = get(name, version)
    if violations:
        instructions += (
            "\n\nYour previous answer was rejected. Fix every issue below and return the "
            "full corrected answer:\n" + "\n".join(f"- {_describe(v)}" for v in violations)
        )
    opening = f'<source_document doc_id="{doc_id}">' if doc_id else "<source_document>"
    content = opening + "\n" + document_text + "\n</source_document>"
    if portfolio_context is not None:
        content += (
            "\n<portfolio_context>\n"
            + json.dumps(portfolio_context, ensure_ascii=False, sort_keys=True)
            + "\n</portfolio_context>"
        )
    if okved_scope:
        content += "\n<portfolio_okved>" + ", ".join(sorted(okved_scope)) + "</portfolio_okved>"
    if graph_factors:
        content += (
            "\n<graph_factors>\n"
            + "\n".join(f"{fid}: {label} — {text}" for fid, label, text in graph_factors)
            + "\n</graph_factors>"
        )
    if direct_factors:
        content += (
            "\n<direct_factors>\n"
            + "\n".join(f"{fid} key={key}: {label}" for fid, key, label in direct_factors)
            + "\n</direct_factors>"
        )
    return [
        {"role": "system", "content": instructions},
        {"role": "user", "content": content},
    ]
