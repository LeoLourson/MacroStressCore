"""The documentation of the mathematics: the platform's pages, then each plugin's.

Every level is divided on one basis. First by who owns the formula: the platform (one
calculation for every instrument type, ``msa/engine/docs``) or a plugin (``Plugin.docs``,
the ``docs/`` folder of its package). The platform's pages follow what the formula
produces, in the order a stress test calculates it; a plugin's pages follow its own order.
"""

from importlib.resources import files

from .registry import doc_file
from .registry import registry as current

#: The platform's pages: realisations, the factor signal, the statistics of a distribution,
#: the portfolio slice and the attribution of a result.
PLATFORM = ("scenario.md", "transmission.md", "statistics.md", "portfolio.md", "attribution.md")


def page(name: str, text: str) -> dict:
    """A page as the app shows it: its slug, the ``# `` title and the Markdown after it."""
    first, _, body = text.partition("\n")
    return {"slug": name.removesuffix(".md"), "title": first[2:].strip(), "markdown": body.strip()}


def documentation(registry=None) -> dict:
    registry = registry or current()
    root = files("msa.engine").joinpath("docs")
    plugins = [
        {
            "plugin_id": plugin.plugin_id,
            "label": plugin.label,
            "version": plugin.version,
            "pages": [
                page(name, doc_file(plugin, name).read_text(encoding="utf-8"))
                for name in plugin.docs
            ],
        }
        for _, plugin in sorted(registry.plugins.items())
        if plugin.docs
    ]
    return {
        "platform": [
            page(name, root.joinpath(name).read_text(encoding="utf-8")) for name in PLATFORM
        ],
        "plugins": plugins,
    }
