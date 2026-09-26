"""The historical pilot event of the demo library: the 2023 mortgage-programme change.

It is prepared for the MULTI-ASSET portfolio.
"""

import json
from pathlib import Path

from msa.db.repositories.demo import DemoRepository
from msa.db.repositories.portfolios import PortfoliosRepository
from msa.db.session import session_scope

ROOT = Path(__file__).resolve().parent / "pilot"
EVENT_ID = "HIST-MORTGAGE-2023-12"
PORTFOLIO_ID = "MULTI-ASSET"


def pilot_event(root=ROOT):
    event = json.loads((root / "event.json").read_text("utf-8"))
    sources = json.loads((root / "sources.json").read_text("utf-8"))
    return {
        "event_id": event["event_id"],
        "title": event["title"],
        "text": event["text"],
        "metadata": {
            "dataset": "demo/pilot",
            "event_date": event["event_date"],
            "default_start": True,
            "portfolio_id": PORTFOLIO_ID,
            "sources": sources["sources"],
            "description": (
                "Историческое событие; синтетический портфель MULTI-ASSET. "
                "Граф, сценарий и результаты строятся при запуске. Допущения проверяет аналитик."
            ),
        },
    }


def seed_pilot(bind, root=ROOT):
    """Requires the regular synthetic catalog; writes only to the demo namespace."""
    with session_scope(bind, scope="demo", scopes={"demo:*"}) as session:
        repository = DemoRepository(session)
        PortfoliosRepository(session).get_bundle(PORTFOLIO_ID)
        repository.seed_event(pilot_event(root))
