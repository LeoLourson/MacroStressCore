"""Russian wording of the report template shared by every plugin.

Every number of the report text must trace to a calculated metric (V9), so no phrase here
may contain a digit: counts, periods and thresholds are said in words or not at all. The
wording of a plugin's own flags, actions and rules is declared by that plugin.
"""

from .numbers import extract_numbers

STATUSES = {
    "ok": "рассчитано",
    "uncalibrated": "модель не откалибрована",
    "needs_review": "нужна ручная проверка",
    "incomplete": "неполный расчёт",
    "invalid": "расчёт недействителен",
}

EXECUTION = {
    "completed": "рассчитано",
    "not_run": "не рассчитано",
    "failed": "расчёт завершился ошибкой",
}

#: Flags of the platform itself: the dispatcher, the aggregator, the data resolution.
PLATFORM_FLAGS = {
    "scenario_factor_missing": "для затронутой позиции не задан сценарий факторов модели; "
    "нужно допущение аналитика, потери не оценены",
    "portfolio_incomplete": "итог среза неполный",
    "portfolio_exclusions": "часть позиций исключена из итога среза",
    "needs_review_included_by_rule": "позиции с ручной проверкой включены по утверждённому правилу",
    "exposure_unknown": "размер части позиций не измерен",
    "positions_outside_slices": "часть позиций не входит ни в один портфельный срез",
    "not_calculated": "позиция не рассчитана",
    "unknown_instrument_type": "тип инструмента не объявлен ни одним плагином",
    "no_model": "для позиции нет расчётной модели",
    "schema": "условия инструмента не соответствуют схеме плагина",
    "schema_version_mismatch": "условия записаны по другой версии схемы плагина",
    "issuer_missing": "у инструмента не указан эмитент",
    "included_by_rule:": "включена в срез по утверждённому правилу",
    "inclusion_rule:": "правило включения",
    "output:": "выход модели не соответствует её объявлению",
    "model_error:": "расчёт завершился ошибкой",
    "data_missing:": "нет данных «{}» на дату оценки",
    "data_dated_after_as_of:": "данные «{}» датированы позже даты оценки и не используются",
    "incompatible:": "вклад несовместим со срезом",
}

# Sources and authors of the demo catalog, in words and without digits (V9).
SOURCES = {
    "TZ-v3": "демо-данные техзадания",
    "demo:track-a-v3.2": "пересчёт демо-данных под текущую модель",
    "demo:conventions": "соглашения демо-каталога",
    "demo:peers": "компании-аналоги",
    "demo:market": "рыночные данные демо-снимка",
    "demo:equity-sensitivities": "экспертные чувствительности акций демо-стенда",
    "demo/portfolios/DEMO-3.json": "нагрузочный демо-портфель",
}
AUTHORS = {
    "demo:spec-v3": "составитель демо-данных",
    "demo:methodology": "методолог демо-стенда",
    "demo:generate_load_portfolio": "генератор нагрузочного портфеля",
    "demo:market-desk": "аналитик рынка демо-стенда",
}


def flag(code: str, wording: dict[str, str], labels: dict[str, str] | None = None) -> str:
    """A flag in words: an exact entry, else a prefix entry (``name:``) with its argument.

    ``labels`` names the arguments (scenario parameters by the analyst's words). An unknown
    flag is shown as is, unless its free text carries digits (V9).
    """
    table = {**PLATFORM_FLAGS, **wording}
    if code in table:
        return table[code]
    prefix, _, rest = code.partition(":")
    rest = rest.strip()
    nested = table.get(prefix + ":>")
    if nested is not None:
        return flag(rest, wording, labels)
    phrase = table.get(prefix + ":")
    if phrase is not None:
        if "{}" not in phrase:
            return phrase
        argument = (labels or {}).get(rest) or rest
        if extract_numbers(argument):
            return phrase.replace("«{}»", "").replace("{}", "").replace("  ", " ").strip()
        return phrase.format(argument)
    return prefix if extract_numbers(code) else code


def informational(code: str, flags: frozenset[str]) -> bool:
    """Whether a flag describes how the numbers were reached rather than a limit on them."""
    prefix = code.partition(":")[0]
    return code in flags or (prefix + ":") in flags or prefix in flags
