"""Прогнать событие пилота АФК на поднятом стенде и сохранить всё, что посчитала платформа.

    uv run --frozen python demo/pilot-afk/backtest.py [EVENT_ID ...]
    uv run --frozen python demo/pilot-afk/backtest.py --dump RUN_ID:EVENT_ID

Стенд должен быть поднят с настоящей моделью (``msa.ps1 up deepseek``): граф и сценарий
строит LLM по тексту события и словам аналитика о силе события (``metadata.scenario_text``).
Аналитик подтверждает граф и сценарий, риск-менеджер утверждает отчёт. Артефакты, отчёт,
трасса и журнал обращений к LLM складываются в ``demo/pilot-afk/runs/<event_id>-<run_id>.json``.

Долгий: один прогон — минуты. Запускать через run_in_background.
"""

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOG = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from demo.pilot_afk import EVENT_ID  # noqa: E402


def _etalon():
    """Стенд пилота «Эталон»: тот же способ запуска прогона, отдельный файл."""
    path = CATALOG.parent / "pilot-etalon" / "backtest.py"
    spec = importlib.util.spec_from_file_location("pilot_etalon_backtest", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


stand_module = _etalon()
Stand, env_file = stand_module.Stand, stand_module.env_file
RUNS = CATALOG / "runs"
# ``dump`` из чужого модуля пишет по своему ``RUNS``: направляем его в папку этого пилота.
stand_module.RUNS = RUNS


def events() -> dict:
    return {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((ROOT / "demo" / "events").glob("*.json"))
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("events", nargs="*", help=f"event ids; по умолчанию {EVENT_ID}")
    parser.add_argument("--scenario-file", type=Path, help="свои слова о силе события")
    parser.add_argument("--dump", metavar="RUN_ID:EVENT_ID", help="снять уже посчитанный прогон")
    args = parser.parse_args()
    values = env_file()
    stand = Stand(
        {
            "analyst": values["MSA_UI_ANALYST_API_KEY"],
            "risk_manager": values["MSA_UI_RISK_MANAGER_API_KEY"],
        }
    )
    if args.dump:
        run_id, _, event_id = args.dump.partition(":")
        stand.dump(run_id, event_id)
        return 0
    library = events()
    scenario = (
        args.scenario_file.read_text(encoding="utf-8").strip() if args.scenario_file else None
    )
    RUNS.mkdir(parents=True, exist_ok=True)
    failures = []
    for event_id in args.events or [EVENT_ID]:
        event = library[event_id]
        print(f"\n{event_id}: {event['title']}", flush=True)
        run_id, status = stand.run(event, scenario)
        stand.dump(run_id, event_id)
        if status["status"] != "completed":
            failures.append(f"{event_id}: {status['status']}")
    if failures:
        print("\nне завершены:\n- " + "\n- ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
