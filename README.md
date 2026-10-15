# MacroStress Core

Стресс-тест портфеля по тексту события. Аналитик вставляет текст (постановление, решение
регулятора, санкции) и описывает силу события своими словами. LLM строит граф передачи шока
«событие → канал → отрасль → фактор» и предлагает сценарий; аналитик их подтверждает. Каждую
затронутую позицию считает модель её типа на общей матрице сценариев:

- кредит — помесячная модель заёмщика: P5/P50/P95, ковенанты, ликвидность, вклад каналов,
  обратный стресс-тест;
- акции — факторный стресс с валютным фактором.

Итоги по срезам (кредитные потери, рыночный результат) складываются внутри общих реализаций;
разные срезы между собой не складываются. Каждое число отчёта ссылается на метрику, отчёт
утверждает риск-менеджер. К готовому прогону можно задать вопрос: ответ строится только на его
числах, прочитанных через MCP-инструменты.

Типы инструментов, модели, факторы, срезы, экраны и агенты подключаются плагинами без правки
ядра — [docs/plugins.md](docs/plugins.md).

## Запуск (Windows, без Docker)

```powershell
.\msa.ps1 up mock        # без LLM: граф по отраслям портфеля, расчёт настоящий
.\msa.ps1 up deepseek    # DeepSeek API, ключ в DEEPSEEK_API_KEY; только демо-портфели
.\msa.ps1 up local       # OpenAI-совместимый сервер на 127.0.0.1:1234 (LM Studio, vLLM)
.\msa.ps1 status | logs | down
.\msa.ps1 rehearse RECYCLING-FEE MORTGAGE-DOWN-PAYMENT   # репетиция линии на поднятом стенде
```

`up` создаёт `.env` с локальными ключами и поднимает PostgreSQL 16 (порт 5433). Затем он
применяет миграцию, загружает демо-каталог (портфели, снимок данных, события), собирает
`ui/web` и запускает API с интерфейсом на http://127.0.0.1:8091.

Демо-портфели и события — [demo/README.md](demo/README.md).

## Разработка

```powershell
uv sync --frozen                       # Python 3.12, зависимости из uv.lock
uv run --frozen pytest                 # testpaths: tests/ и src/msa/plugins/ (тесты платформы и плагинов)
uv run --frozen ruff check . ; uv run --frozen ruff format --check .
uv run --frozen lint-imports           # граница ядра и плагинов: правила импорта
uv run --frozen python -m demo.sanity  # проверки здравого смысла на синтетике (docs/sanity-report.md)
cd ui/web; npm ci; npm run dev         # интерфейс с прокси на API :8091
npm run build                          # манифест плагинов, совместимость UI-плагинов, типы, сборка
```

Плагины:

```powershell
uv run msa-plugin new asset <id>       # шаблон типа инструмента с моделью, тестами, демо-данными
uv run msa-plugin new agent <id>       # шаблон агента с MCP-инструментом, промптом и UI-видом
uv run msa-plugin check [<id>]         # проверка соответствия плагина
uv run msa-plugin demo-run <id>        # демо-расчёт: P5/P50/P95 по позициям и срезам
uv run msa-plugin ui-manifest          # манифест UI-плагинов (npm run build делает это сам)
```

Плагин — папка `src/msa/plugins/<id>/` и, если нужен UI, `ui/web/src/plugins/<id>/`; правка
вне этих папок не требуется. Как писать плагин — [docs/plugins.md](docs/plugins.md).

## Карта

| Путь | Что там |
|---|---|
| `src/msa/plugins/` | Плагины: [`credit`](src/msa/plugins/credit/README.md), [`equity`](src/msa/plugins/equity/README.md), [`market`](src/msa/plugins/market/README.md), [`research`](src/msa/plugins/research/README.md) (пример агента). |
| `src/msa/plugin_sdk/` | SDK плагинов: объявления, `CalculationModel`, `AgentPlugin`, `WorkflowSpec`, MCP-серверы, вычисления ядра (`calc`), отчёт, промпты, помощники тестов и проверка соответствия |
| `src/msa/platform/` | Реестр плагинов и каталоги (`/v1/asset-types`, `/v1/models`, `/v1/workflows`) |
| `src/msa/engine/` | Расчёт без знания типа: снимок данных, сценарии и общие реализации, передача шока, диспетчер моделей, срезы портфеля |
| `src/msa/contracts/` | Контракты: Party/Instrument/Position, DataSnapshot, граф, сценарий, CalculationResult, отчёт, объяснение |
| `src/msa/agents/`, `src/msa/graph/`, `src/msa/core/` | Агенты ядра и объяснения; компилятор процессов LangGraph, журнал, остановки; встроенное объявление `core` (процессы, их агенты и MCP-серверы) |
| `src/msa/mcp/` | MCP-серверы из реестра (ядра: `mcp-portfolio`, `mcp-models`, `mcp-runs`), шлюз, аудит вызовов |
| `src/msa/reporting/` | Дерево метрик, отчёт без собственных чисел, правила, трасса происхождения |
| `src/msa/api/` | FastAPI: портфели, снимки, прогоны, объяснения, каталоги, раздача `ui/web` |
| `src/msa/cli/` | `msa-plugin` и шаблоны плагинов |
| `src/msa/db/`, `migrations/` | Таблицы рабочего и демо-контура, миграция `p0001` |
| `ui/web/` | Браузерный интерфейс (React, Mantine); UI-плагины в `src/plugins/` |
| `demo/` | [Демо-каталог](demo/README.md): синтетические и исторические портфели, снимки, события; генераторы и загрузка |
| `demo/sanity/` | Проверки здравого смысла: синтетические портфели и события, прогон всей линии, [разбор результатов](docs/sanity-report.md) |
| `ops/` | Нативный стенд, генерация `.env`, загрузка рабочего портфеля, репетиция |
| `tests/` | Тесты ядра; тесты плагинов лежат в их папках |
| `.github/CODEOWNERS` | Владельцы ядра, каждого плагина, `demo/` и `docs/` |

## Документация

| Документ | Для кого |
|---|---|
| [docs/tz/overview.md](docs/tz/overview.md) | читатель без кода: назначение, ход прогона, как читать P5/P50/P95, ограничения |
| [docs/tz/developer.md](docs/tz/developer.md) | разработчик: архитектура, данные, API, MCP, хранение, безопасность, приёмка |
| [docs/tz/math.md](docs/tz/math.md) | методолог: путь от события до отчёта, формулы по разделам в [docs/tz/math/](docs/tz/math/) |
| [docs/architecture.md](docs/architecture.md), [docs/platform.md](docs/platform.md) | устройство ядра и платформы |
| [docs/plugins.md](docs/plugins.md) | автор плагина |
| [docs/demo-stories.md](docs/demo-stories.md) | ведущий демонстрации |
| [docs/sanity-report.md](docs/sanity-report.md) | разбор проверок здравого смысла |
| [docs/manual-tests/](docs/manual-tests/) | задания по ручному тестированию |
| [docs/backlog.md](docs/backlog.md) | открытые задачи |
