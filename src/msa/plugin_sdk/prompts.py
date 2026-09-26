"""A plugin's versioned prompts.

``prompt("<plugin_id>.<name>")`` reads the version in force (``Plugin.prompts``) from
``prompts/<name>-<version>.txt`` of the plugin's package; ``current_version`` names it, so
an agent can record which prompt produced its output.
"""

from msa.prompts.registry import current_version
from msa.prompts.registry import get as prompt

__all__ = ["current_version", "prompt"]
