"""The platform's own workflows and their core agents, declared like any plugin's.

``core`` is built in: the registry loads it before it looks at ``msa.plugins``, so every
package under ``msa.plugins`` is an extension. Its workflows (``stress_test``,
``explain_results``) and their core agents belong to the platform; plugins join them at
their extension points.
"""

from msa.plugin_sdk import Plugin

from .explain import AGENT as EXPLAIN_AGENT
from .explain import EXPLAIN
from .stress_test import CORE_AGENTS, STRESS_TEST

plugin = Plugin(
    plugin_id="core",
    version="2.0.0",
    sdk=">=1.0,<2.0",
    label="Процессы платформы",
    description="Стресс-тест портфеля по тексту события и объяснение результатов прогона.",
    agents=(*CORE_AGENTS, EXPLAIN_AGENT),
    workflows=(STRESS_TEST, EXPLAIN),
)
