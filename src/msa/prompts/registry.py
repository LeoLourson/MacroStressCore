import json
from importlib.resources import files

_CURRENT = {"causal": "v3", "advisory": "v2", "explain": "v2"}
_KNOWN = {"causal": {"v1", "v2", "v3"}, "advisory": {"v1", "v2"}, "explain": {"v1", "v2"}}


def current_version(name: str) -> str:
    return _CURRENT[name]


def get(name: str, version: str | None = None) -> str:
    version = version or current_version(name)
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
