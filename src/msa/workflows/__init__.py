"""The platform's own workflows and their core agents, declared like any plugin's.

``core`` is built in: the registry loads it before it looks at ``msa.plugins``, so every
package under ``msa.plugins`` is an extension. Its workflows (``stress_test``,
``explain_results``) and their core agents belong to the platform; plugins join them at
their extension points. Its MCP servers are declared the way a plugin declares its own.
"""

from msa.mcp import models, portfolio, runs
from msa.plugin_sdk import McpServerSpec, Plugin

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
    mcp_servers=(
        McpServerSpec(
            "portfolio",
            portfolio.register,
            label="Данные портфеля",
            description="Состав портфеля и данные позиции из снимка на дату оценки.",
        ),
        McpServerSpec(
            "models",
            models.register,
            label="Расчётные модели",
            description="Расчёт позиции зарегистрированной моделью и каталог моделей.",
        ),
        McpServerSpec(
            "runs",
            runs.register,
            label="Результаты прогона",
            description="Чтение результатов рассчитанного прогона для объяснения.",
        ),
    ),
    # The generated demo catalog (demo/build_catalog.py) belongs to no single plugin.
    sources={
        "demo:companies": "синтетические данные компаний демо-каталога",
        # run_service.ANALYST_SCENARIO: a parameter the analyst added to the scenario.
        "analyst:scenario": "сценарий, заданный аналитиком",
    },
    authors={"demo:catalog": "генератор демо-каталога"},
)
