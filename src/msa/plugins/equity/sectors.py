"""Editable model groups, not an official OKVED-to-stock-index classification.

Longest-prefix matching lets a specific activity override a broad group. An analyst's
explicit sector always wins, including custom keys used by an existing calibration.
"""

SECTORS = (
    ("oil_gas", "Нефть и газ"),
    ("materials", "Сырьё и материалы"),
    ("industrials", "Промышленность и оборудование"),
    ("utilities", "Энергетика и коммунальные услуги"),
    ("consumer", "Потребительские товары и услуги"),
    ("trade", "Торговля"),
    ("transport", "Транспорт и хранение"),
    ("technology", "Информационные технологии"),
    ("telecom", "Телекоммуникации"),
    ("financials", "Финансовые услуги"),
    ("real_estate", "Недвижимость и строительство"),
    ("healthcare", "Здравоохранение и фармацевтика"),
)

OKVED_SECTORS = (
    *((f"{code:02}", "consumer") for code in (1, 2, 3, *range(10, 19), 31, 32, 55, 56)),
    *((f"{code:02}", "materials") for code in (5, 7, 8, 9, 19, 20, 22, 23, 24)),
    *((f"{code:02}", "industrials") for code in (*range(25, 31), 33)),
    *((f"{code:02}", "utilities") for code in range(35, 40)),
    *((f"{code:02}", "real_estate") for code in (41, 42, 43, 68)),
    *((f"{code:02}", "trade") for code in (45, 46, 47)),
    *((f"{code:02}", "transport") for code in range(49, 54)),
    *((f"{code:02}", "technology") for code in (58, 62, 63)),
    *((f"{code:02}", "financials") for code in (64, 65, 66)),
    *((f"{code:02}", "healthcare") for code in (21, 86, 87, 88)),
    ("06", "oil_gas"),
    ("09.1", "oil_gas"),
    ("19.2", "oil_gas"),
    ("46.71", "oil_gas"),
    ("46.6", "industrials"),
    ("61", "telecom"),
)


def sector_for_okved(okved: str | None) -> str | None:
    code = (okved or "").replace(".", "")
    matches = [
        (prefix, value)
        for prefix, value in OKVED_SECTORS
        if code.startswith(prefix.replace(".", ""))
    ]
    return max(matches, key=lambda item: len(item[0].replace(".", "")))[1] if matches else None
