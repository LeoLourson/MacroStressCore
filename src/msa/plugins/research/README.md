# Плагин `research`: пример агентного плагина

Исследовательские заметки о том, где сосредоточены хвостовые потери портфеля.
Все агенты выключены по умолчанию: включаются в запросе прогона
(`"agents": ["research.concentration", "research.brief", "research.digest"]`) или
переменной `MSA_AGENT_PLUGINS`. Плагин показывает SDK агентов целиком и ничего не правит в
ядре.

| Агент | Что показывает |
|---|---|
| `research.concentration` | подграф LangGraph с собственным состоянием и адаптерами входа и выхода; ограниченный цикл по срезам; позиции с долей не меньше 25 % в ES95 своего среза |
| `research.brief` | чтение вывода другого агента (`ext:research.concentration/notes`) и порядок `after` |
| `research.digest` | вызов собственного MCP-инструмента `research.notes.slice_digest` через `AgentContext.tools`: только объявленные инструменты, каждый вызов в аудите под узлом агента |

Все три подключаются к точке `after_calculation` процесса `stress_test`, пишут только в
свои пространства `extensions["research.*"]` и не обходят решение риск-менеджера.

| Что ещё объявлено | Значения |
|---|---|
| MCP-сервер | `research.notes` (`mcp-research.notes`): `slice_digest(slices)` — число позиций, наибольшая доля в ES95 и индекс Херфиндаля по срезам; только арифметика над аргументами, без доступа к данным |
| UI | `ui/web/src/plugins/research`: таблицы выводов `research.concentration` и `research.digest` на вкладке «Портфель» (`UiPlugin.agents`) |

Без шлюза MCP (граф теста без серверов) `research.digest` завершается ошибкой в своём
пространстве (`{"failed": true, "errors": [...]}`), а прогон продолжается.

## Папка плагина

| Путь | Что там |
|---|---|
| `__init__.py` | агенты, их подграф и адаптеры, MCP-сервер `research.notes` |

Тесты агентов плагина пока лежат в тестах платформы: `tests/graph/test_agent_plugins.py`,
`tests/graph/test_agent_tools.py`, `tests/api/test_research_digest.py`.

## Проверка

```powershell
uv run msa-plugin check research
uv run --frozen pytest tests/graph/test_agent_plugins.py tests/graph/test_agent_tools.py tests/api/test_research_digest.py
```
