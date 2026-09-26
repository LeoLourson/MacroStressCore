"""Russian wording of the credit plugin's flags; no phrase carries a digit (V9).

A key ending in ``:`` covers a prefix; ``{}`` takes the argument after it (the scenario
parameter, named by the analyst's words where known). ``name:>`` marks a flag that wraps
another flag (``profile:proxy_required``), worded as the inner one.
"""

FLAGS = {
    "limited_disclosure": "ограниченное раскрытие отчётности",
    "proxy_required": "нужна оценка по компаниям-аналогам",
    "lgd_not_applicable": "LGD не применяется",
    "ead_is_credit_limit": "сумма под риском — лимит кредитной линии",
    "negative_ebitda": "отрицательная EBITDA",
    "missing_financials": "нет отчётности",
    "missing_financials_and_peers": "нет отчётности и компаний-аналогов",
    "incomplete_model_inputs": "не хватает обязательных входов модели",
    "no_peers": "нет компаний-аналогов",
    "base_covenant_breached": "ковенант нарушен ещё до события",
    "ebitda_nonpositive": "EBITDA не положительна, покрытие процентов не определено",
    "shapley_not_converged": "вклад каналов оценён приближённо",
    "pd_uncalibrated": "модель PD не откалибрована",
    "constant_hazard_approximation": "PD оценена приближением постоянной интенсивности",
    "duration_approximation_gap": "приближение через дюрацию расходится с полной переоценкой",
    "leasing_ecl_missing": "нет оценки ожидаемых потерь лизингового портфеля",
    "market_calibration_missing": "рыночная модель не откалибрована",
    "demand_elasticity_missing_or_invalid": "эластичность спроса не задана или некорректна",
    "project_rate_subsidy_simplified": "субсидия ставки учтена упрощённо",
    "project_funding_gap": "у проекта дефицит финансирования",
    "funding_gap": "дефицит финансирования",
    "not_applicable": "не применяется",
    "annual_financials_spread_evenly": "годовая отчётность разнесена по месяцам равномерно",
    "assumed_working_capital_days": "сроки оборотного капитала приняты по допущению",
    "assumed_tax_rate": "ставка налога принята по допущению",
    "assumed_demand_elasticity": "эластичность спроса принята по допущению",
    "assumed_no_pass_through": "перенос роста затрат в цену не задан и не учитывается",
    "capacity_binding": "упор в производственную мощность",
    "capital_nonpositive": "капитал не положителен",
    "cash_interest_nonpositive": "процентные платежи не положительны",
    "cash_iteration_not_converged": "расчёт денежного потока не сошёлся",
    "construction_limit_exceeded": "превышен лимит на строительство",
    "discontinuous_boundary": "порог нарушения достигается скачком",
    "ltm_annualised": "показатели за последний год приведены к годовым",
    "market_structure_mismatch": "структура рынка не совпадает с моделью",
    "missing_pre_horizon_history": "нет истории до начала горизонта",
    "negative_cost": "отрицательные затраты",
    "non_monotonic": "зависимость немонотонна",
    "out_of_domain": "значения вне области применимости модели",
    "pd_clipped_for_numerical_stability": "PD ограничена для устойчивости расчёта",
    "shapley_not_efficient": "сумма вкладов каналов не равна итогу",
    "simplified_tax": "налог рассчитан упрощённо",
    "volume_floor_binding": "объём упёрся в нижнюю границу",
    "calibration_synthetic": "PD по синтетической демо-калибровке, не эмпирической",
    "market_inputs_from_profile": "рыночные входы облигации взяты из условий выпуска",
    "spread_scaled_by_pd_ratio": "изменение спреда принято пропорциональным изменению PD",
    "spread_change_unavailable": "без калиброванной PD спред не меняется",
    "numerical_tolerance_not_met": "численная точность вне допуска",
    "icr_undefined_in_some_scenarios": "в части сценариев покрытие процентов не определено",
    "escrow_coverage_undefined_in_some_scenarios": "в части сценариев покрытие эскроу не задано",
    "debt_equity_undefined_in_some_scenarios": "в части сценариев долг к капиталу не определён",
    "funding_gap_undefined_in_some_scenarios": "в части сценариев дефицит не определён",
    "credit_currency_unsupported": "кредитные модели считают только в рублях",
    "issuer_okved_missing": "у заёмщика не указан ОКВЭД",
    "profile_invalid": "профиль позиции не собран",
    "scenario_parameter_unmapped:": "параметр сценария «{}» не используется моделью позиции",
    "factor_not_reached:": "шок «{}» не доходит до показателей позиции",
    "uncalibrated_threshold:": "порог «{}» не откалиброван",
    # Free text or an identifier follows these; the phrase stands without it.
    "covenant_outside_horizon:": "ковенант не проверяется в пределах горизонта расчёта",
    "covenant_metric_unavailable:": "показатель ковенанта модель не рассчитывает",
    "covenant_metric_undefined:": "показатель ковенанта не определён в стрессовом сценарии",
    "reverse_stress_undefined:": "обратный стресс-тест не выполнен: показатель теряет смысл",
    "out_of_domain:": "значения вне области применимости модели",
    "profile_needs_review:": "профиль позиции требует проверки",
    "V2:": "вход модели вне объявленных единиц или границ",
    # A flag of the profile or of LGD, carried inside a flag of the model.
    "profile:>": "",
    "lgd:>": "",
}

#: How the numbers were reached rather than a limit on them: a channel that does not reach
#: the position, the length of the history, a funding gap the report states in its section.
INFORMATIONAL = frozenset(
    {
        "factor_not_reached:",
        "ltm_annualised",
        "missing_pre_horizon_history",
        "funding_gap",
        "project_funding_gap",
    }
)

# Where the credit demo data comes from and who stands behind it, without digits (V9).
SOURCES = {
    "TZ-v3": "демо-данные техзадания",
    "demo:track-a-v3.2": "пересчёт демо-данных под текущую модель",
    "demo:conventions": "соглашения демо-каталога",
    "demo:peers": "компании-аналоги",
    "demo/portfolios/DEMO-3.json": "нагрузочный демо-портфель",
}
AUTHORS = {
    "demo:spec-v3": "составитель демо-данных",
    "demo:methodology": "методолог демо-стенда",
    "demo:generate_load_portfolio": "генератор нагрузочного портфеля",
}
