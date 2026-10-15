# Плагин `credit`: кредитный риск

Помесячная модель заёмщика, PD и ожидаемые потери на общих сценариях прогона.

| Что объявлено | Значения |
|---|---|
| Типы инструментов | `corp_loan`, `bond_fixed`, `bond_floater`, `pf_escrow`, `leasing` |
| Модели | `credit.corporate.v3`, `credit.bond.v3`, `credit.project_finance.v3`, `credit.leasing.v3` — по одной на семейство |
| Факторы (`scope="graph"`) | `credit.revenue`, `credit.cogs`, `credit.logistics`, `credit.working_capital`, `credit.interest`, `credit.capex`, `credit.fx` |
| Срез | `credit.loss` — рост ожидаемых потерь, база покрытия EAD |
| Виды снимка | `financial_statement` (отчётность заёмщика и аналогов), `rate` (кривая, например `risk_free:RUB`) |
| Отчёт и правила | разделы `credit.*`, правила R1–R5, действия `restructure`, `add_collateral`, `covenant_talks`, `limit_cut`, `hedge`, `watchlist` |
| Параметры контура | `run_options`: реестр калибровок PD (синтетический — только в демо-контуре), `notes` раскрывают его в отчёте |
| UI | `ui/web/src/plugins/credit`: вид позиции, заметка о калибровке PD, пояснения ковенантов в отчёте (`glosses`), термины PD, LGD, EAD, ΔEL, ΔPD, ICR, «Ковенант», «Обратный стресс-тест» (`glossary`) |

## Папка плагина

| Путь | Что там |
|---|---|
| `__init__.py` | объявление `plugin = Plugin(...)` |
| `model.py` | `CreditModel`: адаптер помесячной модели к `CalculationModel` (`requirements` → `validate` → `calculate`) |
| `position_risk.py` | риск одной позиции: шоки факторов → семейство → риск, P5/P50/P95, Шепли, обратный стресс |
| `family.py`, `families/` | `CreditFamily` и четыре семейства: операционная компания, облигация, проектное финансирование, лизинг |
| `math/` | математика плагина: помесячные модели семейств, календарь, финансовые метрики, PD и ожидаемые потери (`math/credit.py`), ковенанты, оси риска (`math/impact.py`), обратный стресс |
| `contracts.py`, `schemas.py` | профиль и результат кредитной позиции (`RiskResult`, траектории, ковенанты, вклады, оси); схемы `terms` и `params` |
| `profile.py`, `editor.py`, `editor_help.py` | профиль позиции из снимка; форма редактора и `from_draft` |
| `report.py`, `wording.py`, `impact.py` | разделы отчёта, правила, дерево `tree`; слова флагов, источников и авторов демо-данных |
| `calibration.py`, `registries/` | реестры калибровок PD как версионированные файлы данных |
| `demo.py`, `demo_case.json` | демо-кейс для `msa-plugin check` |
| `demo_data/` | часть демо-стенда по коллекциям `synthetic/` и `historical/<случай>/` (см. `demo/README.md`): позиции MULTI-ASSET, ATYPICAL-BORROWERS, LOAD-TEST и отчётность снимка SYNTHETIC-2026-09-11 |
| `tests/` | тесты плагина и эталон кредитной модели |

Плагин импортирует только `msa.plugin_sdk` (включая `calc` и `report`), `msa.contracts` и
свой пакет; это проверяет `lint-imports`.

## Новое кредитное семейство

Кредитный плагин расширяется семейством: класс `CreditFamily` в `families/` объявляет
типы, входы отчётности, ряды, метрики ковенантов и помесячную модель; строка в `FAMILIES`
(`families/__init__.py`) регистрирует его, и модель семейства появляется в реестре.
Факторы `credit.*`, срез `credit.loss`, правила R1–R5 и калибровки PD семейство использует
общие. Вид `financial_statement` описывает поля отчётности всех семейств
(`fields_from("statement")`), поэтому новое семейство расширяет его само.

## Эталон

`tests/test_credit_reference.py` сверяет все позиции MULTI-ASSET и ATYPICAL-BORROWERS и
срез `credit.loss` с эталоном `credit_reference.json`. Эталон пишет
`tests/capture_reference.py` на одном сценарии: пять факторов через граф с лагами и
треугольной эластичностью, 512 точек × 8 реплик, зерно 20260911.

```powershell
uv run --frozen python -m msa.plugins.credit.tests.capture_reference   # переписать эталон
```

Эталон переписывают, только когда изменение чисел задумано, и в сообщении коммита
объясняют, что изменилось. Хеш реализаций не сравнивается: вместо него сверяются сводки
реализаций каждого параметра (сумма, сумма квадратов, первые значения, P5/P50/P95).
Допуск — 1e-8 относительный (при масштабе больше 1). Эталон снят на Windows.

## Ограничения

Требуют методического решения; поведение и флаги описаны в
[docs/tz/math/05-credit-risk.md](../../../../docs/tz/math/05-credit-risk.md).

- Структурный параметр сценария `elasticity` расчёт игнорирует (`scenario_parameter_unmapped`).
- Спред облигации сдвигается пропорционально отношению PD (`spread_scaled_by_pd_ratio`).
- Кредитные потери лизингополучателей не моделируются (`leasing_ecl_missing`).
- Правила осей риска не утверждены: все оси «не оценено», пока в реестре калибровок нет `axis_rules`.
- Залоги профиля не участвуют в LGD.

## Проверка

```powershell
uv run msa-plugin check credit
uv run msa-plugin demo-run credit
uv run --frozen pytest src/msa/plugins/credit
```
