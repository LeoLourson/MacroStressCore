"""Прогнать пилотные события на поднятом стенде и сохранить всё, что посчитала платформа.

    uv run --frozen python demo/historical/etalon/research/backtest.py [EVENT_ID ...]
    uv run --frozen python demo/historical/etalon/research/backtest.py \
        --scenario-file scenario.txt EVENT_ID

Стенд должен быть поднят с настоящей моделью (``msa.ps1 up deepseek``), а не с заглушкой:
граф и сценарий строит LLM. Для каждого события аналитик запускает прогон на портфеле,
для которого событие подготовлено, со своими словами о силе события (``metadata
.scenario_text``, либо текст из ``--scenario-file``), подтверждает граф и сценарий, затем
риск-менеджер утверждает отчёт. Артефакты, отчёт, трасса и журнал обращений к LLM
складываются в ``demo/historical/etalon/research/runs/<event_id>-<run_id>.json``.

Долгий: один прогон с DeepSeek — минуты. Запускать через run_in_background.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[4]
CATALOG = Path(__file__).resolve().parent
RUNS = CATALOG / "runs"
API = "http://127.0.0.1:8091"
ACTIVE = {"queued", "running"}
PATIENCE = 2400  # секунд на шаг: LLM отвечает минутами


def env_file() -> dict:
    values = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            name, value = line.split("=", 1)
            values[name] = value.strip("'")
    return values


def events() -> dict:
    return {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        # События всех коллекций каталога: demo/synthetic/events и demo/historical/<case>/events.
        for path in sorted((ROOT / "demo").glob("*/**/events/*.json"))
    }


class Stand:
    def __init__(self, keys):
        self.clients = {
            role: httpx.Client(base_url=API, headers={"X-API-Key": key}, timeout=120)
            for role, key in keys.items()
        }

    def call(self, role, method, path, **kwargs):
        response = self.clients[role].request(method, f"/v1/demo{path}", **kwargs)
        response.raise_for_status()
        return response.json() if response.content else None

    def wait(self, run_id, note):
        deadline = time.monotonic() + PATIENCE
        status = self.call("analyst", "GET", f"/runs/{run_id}")
        while status["status"] in ACTIVE and time.monotonic() < deadline:
            time.sleep(5)
            status = self.call("analyst", "GET", f"/runs/{run_id}")
        print(f"    {note}: {status['status']} ({status.get('errors') or 'без ошибок'})", flush=True)
        return status

    def run(self, event, scenario=None):
        words = scenario or (event.get("metadata") or {}).get("scenario_text")
        status = self.call(
            "analyst",
            "POST",
            "/runs",
            json={
                "portfolio_id": event["metadata"]["portfolio_id"],
                "event": {"kind": "library", "id": event["event_id"]},
                **({"scenario": words} if words else {}),
            },
        )
        run_id = status["run_id"]
        print(f"  прогон {run_id}", flush=True)
        status = self.wait(run_id, "граф")
        if status["status"] == "human_fix_graph":
            graph = self.call("analyst", "GET", f"/runs/{run_id}/artifacts")["graph"]
            self.call("analyst", "POST", f"/runs/{run_id}/resume", json={"graph": graph})
            status = self.wait(run_id, "расчёт и отчёт")
        if status["status"] == "human_approval":
            self.call(
                "risk_manager",
                "POST",
                f"/runs/{run_id}/resume",
                json={"approved": True},
            )
            status = self.wait(run_id, "решение")
        return run_id, status

    def dump(self, run_id, event_id):
        """Всё, что платформа посчитала по прогону, — в файл рядом с остальными."""
        dump = {
            "event_id": event_id,
            "status": self.call("analyst", "GET", f"/runs/{run_id}"),
            "artifacts": self.call("analyst", "GET", f"/runs/{run_id}/artifacts"),
            "report": self.call("analyst", "GET", f"/runs/{run_id}/report"),
            "trace": self.call("analyst", "GET", f"/runs/{run_id}/trace"),
            "activity": self.call("analyst", "GET", f"/runs/{run_id}/activity"),
        }
        RUNS.mkdir(parents=True, exist_ok=True)
        path = RUNS / f"{event_id}-{run_id}.json"
        path.write_text(json.dumps(dump, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"  записано {path.relative_to(ROOT)}", flush=True)
        return dump


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("events", nargs="*", help="event ids; по умолчанию оба пилотных")
    parser.add_argument("--scenario-file", type=Path, help="свои слова о силе события")
    parser.add_argument(
        "--dump",
        metavar="RUN_ID:EVENT_ID",
        help="не запускать прогон, а снять артефакты уже посчитанного",
    )
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
    chosen = args.events or [
        "HIST-ETALON-MORTGAGE-2023-12",
        "HIST-ETALON-MORTGAGE-2024-07",
    ]
    scenario = args.scenario_file.read_text(encoding="utf-8").strip() if args.scenario_file else None
    RUNS.mkdir(parents=True, exist_ok=True)
    failures = []
    for event_id in chosen:
        event = library[event_id]
        print(f"\n{event_id}: {event['title']}", flush=True)
        run_id, status = stand.run(event, scenario)
        dump = stand.dump(run_id, event_id)
        if scenario:
            path = RUNS / f"{event_id}-{run_id}.json"
            path.rename(RUNS / f"{event_id}-{run_id}-alt.json")
        if status["status"] != "completed":
            failures.append(f"{event_id}: {status['status']}")
    if failures:
        print("\nне завершены:\n- " + "\n- ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
