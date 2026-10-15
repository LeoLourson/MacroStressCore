"""Библиотечное событие пилота АФК: повышение ключевой ставки 25.10.2024.

Оно подготовлено для портфеля ``AFK-SYSTEMA-OCT-2024``. Портфель собирается генератором
``demo.build_pilot_afk`` из ``demo/historical/afk-systema/research``. Текст события и источники
читаются из каталога (``demo/historical/afk-systema/events/HIST-KEY-RATE-2024-10.json`` и
``demo/historical/afk-systema/sources.json``):
здесь только то, что должно попасть в библиотеку на стенде, где демо-каталог не переносится
целиком.
"""

import json
from pathlib import Path

from msa.db.repositories.demo import DemoRepository
from msa.db.repositories.portfolios import PortfoliosRepository
from msa.db.session import session_scope

CATALOG = Path(__file__).resolve().parent
ROOT = CATALOG / "historical" / "afk-systema"
EVENT_ID = "HIST-KEY-RATE-2024-10"
PORTFOLIO_ID = "AFK-SYSTEMA-OCT-2024"
#: Идентификатор пилота в ``demo_data`` плагинов; каталог сборки едет отдельной папкой.
MODULE_ID = "pilot-afk"


def pilot_event(catalog=CATALOG, root=ROOT):
    event = json.loads((root / "events" / f"{EVENT_ID}.json").read_text("utf-8"))
    sources = json.loads((root / "sources.json").read_text("utf-8"))
    return {
        "event_id": event["event_id"],
        "title": event["title"],
        "text": event["text"],
        "metadata": {
            # Всё из файла события — в том числе слова аналитика о силе события
            # (``scenario_text``) — плюс источники пилота: библиотека и каталог не расходятся.
            **event["metadata"],
            "dataset": "demo/historical/afk-systema",
            "default_start": True,
            "portfolio_id": PORTFOLIO_ID,
            "sources": sources["sources"],
        },
    }


def seed_pilot(bind, catalog=CATALOG, root=ROOT):
    """Requires the pilot's portfolio in the catalog; writes only to the demo namespace."""
    with session_scope(bind, scope="demo", scopes={"demo:*"}) as session:
        repository = DemoRepository(session)
        PortfoliosRepository(session).get_bundle(PORTFOLIO_ID)
        repository.seed_event(pilot_event(catalog, root))
