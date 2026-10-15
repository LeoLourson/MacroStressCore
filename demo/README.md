# Демо-каталог

Каталог состоит из *коллекций* одного устройства. Коллекция — папка с `events/`, `portfolios/`
и `snapshots/`; синтетическая одна, исторических — по папке на случай.

```text
demo/
  synthetic/                    вымышленные компании и новости (metadata.synthetic: true)
    events/                     события, по файлу на событие (с mock_answer для профиля mock)
    portfolios/                 заголовки портфелей: {"portfolio": {...}} без позиций
    snapshots/                  заголовки снимков данных без items
    story_catalog.json          компании и книги деловых историй (вход build_catalog.py)
  historical/                   настоящие события и публичные данные (metadata.synthetic: false)
    etalon/                     ГК «Эталон», ипотека 2023–2024
      events/ portfolios/ snapshots/
      sources.json              источники случая
      research/                 сбор данных: заметки, котировки, отчётность, скрипты, сверка с фактом
    afk-systema/                «дочки» АФК «Система», ключевая ставка 25.10.2024
      events/ portfolios/ snapshots/
      sources.json
      research/                 (raw/ — страницы MOEX ISS)
    mortgage-2023/              льготная ипотека 23.12.2023 для синтетического MULTI-ASSET
      event.json                событие в формате пилота (не каталога): заносит demo/pilot.py
      sources.json
  sanity/                       проверки здравого смысла: python -m demo.sanity
  catalog.py                    сборка портфелей и снимков из заголовков и частей плагинов
  build_catalog.py              генератор синтетических портфелей и ответов профиля mock
  build_etalon.py               генератор файлов случая historical/etalon
  build_pilot_afk.py            генератор файлов случая historical/afk-systema
  seed_demo.py                  загрузка каталога в демо-контур
  pilot.py, pilot_afk.py        исторические события стартовых кейсов для библиотеки стенда
```

| Часть | Что в ней | Признак |
|---|---|---|
| `synthetic/` | Все вымышленные портфели (`MULTI-ASSET`, тематические, деловые истории), их снимки `SYNTHETIC-*` и события | `metadata.synthetic: true` |
| `historical/etalon/` | `ETALON-DEC-2023`, `ETALON-JUN-2024`, снимки `ETALON-2023-12-31`, `ETALON-2024-06-30`, события `HIST-ETALON-MORTGAGE-2023-12`, `HIST-ETALON-MORTGAGE-2024-07` | `metadata.synthetic: false` |
| `historical/afk-systema/` | `AFK-SYSTEMA-OCT-2024`, снимок `AFK-SYSTEMA-2024-10-24`, событие `HIST-KEY-RATE-2024-10` | `metadata.synthetic: false` |
| `historical/mortgage-2023/` | Событие `HIST-MORTGAGE-2023-12` и его источники; портфеля и снимка нет | `metadata.synthetic: false` (ставит `pilot.py`) |

Части портфелей и снимков лежат в плагинах по тому же пути коллекции и под тем же именем файла:
`src/msa/plugins/<id>/demo_data/<коллекция>/portfolios/<portfolio_id>.json` (`parties`,
`instruments`, `positions`) и `src/msa/plugins/<id>/demo_data/<коллекция>/snapshots/<snapshot_id>.json`
(`items`), где коллекция — `synthetic` или `historical/<случай>`. Строки деловых историй —
`demo_data/synthetic/story_rows.json`. Заголовок и части сводит `demo/catalog.py`: части читаются
в порядке плагинов реестра, одинаковая запись из двух плагинов допустима, разные записи под одним
идентификатором — ошибка; ошибка и часть в другой коллекции, чем заголовок, и
`metadata.synthetic`, противоречащий коллекции. Плагин может принести и собственный заголовок
портфеля или снимка, которого нет в ядре, — в своей `demo_data/<коллекция>/`.

Сгенерированные файлы пишут генераторы; `--check` сверяет их без записи:

```powershell
uv run --frozen python -m demo.build_catalog [--check]     # synthetic/ и ответы mock
uv run --frozen python -m demo.build_etalon [--check]      # historical/etalon/
uv run --frozen python -m demo.build_pilot_afk [--check]   # historical/afk-systema/
```
