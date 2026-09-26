"""The platform's own workflows and their core agents, declared like any plugin's."""

from msa.plugin_sdk import Plugin
from msa.workflows.explain import AGENT as EXPLAIN_AGENT
from msa.workflows.explain import EXPLAIN
from msa.workflows.stress_test import CORE_AGENTS, STRESS_TEST

plugin = Plugin(
    plugin_id="core",
    version="2.0.0",
    sdk=">=1.0,<2.0",
    label="Процессы платформы",
    description="Стресс-тест портфеля по тексту события и объяснение результатов прогона.",
    agents=(*CORE_AGENTS, EXPLAIN_AGENT),
    workflows=(STRESS_TEST, EXPLAIN),
)
