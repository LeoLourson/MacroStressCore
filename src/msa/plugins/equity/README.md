# Плагин `equity`: акции (факторный стресс)

Обыкновенные акции, длинные позиции, стресс рыночного, отраслевого и валютного факторов на
горизонте. Версия 1.1.0; SDK `>=1.0,<2.0`. Зависит от базового плагина `market`: валютный
фактор `market.fx`, срез `market.pnl`, виды снимка `price` и `fx_rate`
(`msa.plugins.market.fx`, `msa.plugins.market.kinds`).

| Что объявлено | Значения |
|---|---|
| Тип инструмента | `common_stock` |
| Модель | `equity.factor_stress.v1`: `P_T = P_0 · exp(β_m f_m + β_s f_s + ε)`, курс `FX_T = FX_0 · exp(f_fx)`, дивиденды за горизонт по курсу конца горизонта |
| Факторы | `equity.market` (`global`, ключ — индекс, например `MOEX`), `equity.sector` (`graph`: изменение отрасли сверх рынка приходит по графу события через ОКВЭД эмитента; `terms.sector` называет отрасль, к которой оценена `beta_sector`); `market.fx` плагина `market` |
| Срез | вклад в `market.pnl` плагина `market` |
| Виды снимка | `sensitivity` (беты и остаточная волатильность), `dividend` (сумма на акцию за горизонт) |
| Отчёт и правила | разделы `equity.results`, `equity.factors`; правила `equity.E1` (потери P95 выше порога доли стоимости), `equity.E2` (отрицательный медианный результат); действия `equity_hedge`, `equity_watch` |
| UI | `ui/web/src/plugins/equity`: вид позиции (данные, центральный сценарий, вклад факторов, гистограмма потерь) |

Чувствительности загружаются со снимком данных, у каждой — автор и источник;
автоматической калибровки пока нет. Нулевой остаточный риск или нулевые дивиденды
задаются явно: отсутствие данных останавливает позицию с причиной.

## Папка плагина

| Путь | Что там |
|---|---|
| `__init__.py` | объявление `plugin = Plugin(...)` |
| `model.py` | `ShareFactorStress`: требования к данным, проверка, расчёт на общих реализациях, вклады Шепли |
| `schemas.py` | `terms`, `params`, `details`; виды снимка `sensitivity` и `dividend` |
| `editor.py`, `sectors.py` | форма редактора, `from_draft`, соответствие ОКВЭД и отраслевых факторов |
| `report.py` | разделы отчёта, наблюдения и правила, дерево `tree` |
| `demo.py`, `demo_case.json` | демо-кейс для `msa-plugin check` |
| `demo_data/` | часть демо-стенда: `SHARE-OIL`, `SHARE-US-TECH` в MULTI-ASSET и их цены, курс, чувствительности, дивиденды в демо-снимке |
| `tests/` | тесты плагина, включая приёмочные (`test_equity_acceptance.py`) |

## Проверка

```powershell
uv run msa-plugin check equity
uv run msa-plugin demo-run equity
uv run --frozen pytest src/msa/plugins/equity
```
