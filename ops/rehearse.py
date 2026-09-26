"""Dress rehearsal on the live native stack (ops/local_stack.py up), with its LLM profile.

For each library event: the analyst starts a run on DEMO-1, confirms the graph and the
scenario, the risk manager returns the report with a reason, the analyst confirms again, the
risk manager approves. Then the results, the report and its trace are checked.

    uv run --frozen python ops/rehearse.py [EVENT-A EVENT-B]
"""

import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

from local_stack import API, env_file  # noqa: E402

ACTIVE = {"queued", "running"}
PORTFOLIO = "DEMO-1"


class Rehearsal:
    def __init__(self, keys):
        self.clients = {
            role: httpx.Client(base_url=API, headers={"X-API-Key": key}, timeout=60)
            for role, key in keys.items()
        }
        self.failures, self.started = [], time.monotonic()

    def step(self, text):
        now = time.monotonic()
        print(f"  {now - self.started:6.1f} с  {text}", flush=True)
        self.started = now

    def check(self, ok, text):
        print(f"         {'✓' if ok else '✕'} {text}", flush=True)
        if not ok:
            self.failures.append(text)
        return ok

    def call(self, role, method, path, **kwargs):
        response = self.clients[role].request(method, f"/v1/demo{path}", **kwargs)
        response.raise_for_status()
        return response.json() if response.content else None

    def wait(self, run_id, seconds=600):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            status = self.call("analyst", "GET", f"/runs/{run_id}")
            if status["status"] not in ACTIVE:
                return status
            time.sleep(2)
        return status

    def confirm(self, run_id):
        graph = self.call("analyst", "GET", f"/runs/{run_id}/artifacts")["graph"]
        self.call("analyst", "POST", f"/runs/{run_id}/resume", json={"graph": graph})
        return self.wait(run_id)

    def decide(self, run_id, **answer):
        self.call("risk_manager", "POST", f"/runs/{run_id}/resume", json=answer)
        return self.wait(run_id)

    def run(self, event):
        print(f"\n{event['event_id']}: {event['title']}", flush=True)
        words = (event.get("metadata") or {}).get("scenario_text")
        status = self.call(
            "analyst",
            "POST",
            "/runs",
            json={
                "portfolio_id": PORTFOLIO,
                "event": {"kind": "library", "id": event["event_id"]},
                **({"scenario": words} if words else {}),
            },
        )
        run_id = status["run_id"]
        self.step(f"прогон {run_id} создан")
        status = self.wait(run_id)
        if not self.check(status["status"] == "human_fix_graph", f"статус {status['status']}"):
            return
        stop = status["pending_interrupt"][0]["payload"]
        failed = [v for v in stop["violations"] if not v["ok"]]
        if not self.check(
            bool(stop["graph"]) and not failed,
            f"граф и сценарий без нарушений, попыток: {stop['attempts']}"
            + (f"; ошибки: {status['errors'] or failed}" if failed else ""),
        ):
            return
        status = self.confirm(run_id)
        self.step("аналитик подтвердил граф и сценарий, расчёт и отчёт готовы")
        if not self.check(status["status"] == "human_approval", "отчёт ждёт риск-менеджера"):
            return
        reason = "Репетиция: проверьте эластичность спроса"
        status = self.decide(run_id, approved=False, returned=True, reason=reason)
        self.step("риск-менеджер вернул отчёт аналитику")
        decision = (status.get("pending_interrupt") or [{}])[0].get("payload", {}).get("decision")
        self.check((decision or {}).get("reason") == reason, "причина возврата видна аналитику")
        self.confirm(run_id)
        self.step("аналитик подтвердил граф повторно")
        status = self.decide(run_id, approved=True)
        self.step("риск-менеджер утвердил отчёт")
        if not self.check(status["status"] == "completed", "прогон завершён"):
            return
        artifacts = self.call("analyst", "GET", f"/runs/{run_id}/artifacts")
        results = [r for r in artifacts["results"] if r["execution"] == "completed"]
        quantiles = [
            m["quantiles"] for r in results for m in r["metrics"].values() if m.get("quantiles")
        ]
        self.check(
            bool(results) and all(q["p05"] <= q["p50"] <= q["p95"] for q in quantiles),
            f"P5/P50/P95 у {len(results)} из {len(artifacts['results'])} затронутых позиций",
        )
        report = self.call("analyst", "GET", f"/runs/{run_id}/report")
        trace = self.call("analyst", "GET", f"/runs/{run_id}/trace")
        traced = {n["metric_path"] for n in trace["numbers"] if n["lineage"] and n["sources"]}
        missing = [n["metric_path"] for n in report["numbers"] if n["metric_path"] not in traced]
        self.check(
            not missing,
            f"происхождение у {len(report['numbers']) - len(missing)} из "
            f"{len(report['numbers'])} чисел отчёта" + (f", нет: {missing[:3]}" if missing else ""),
        )
        self.step(f"отчёт и трасса получены; модель {status['versions']['model_version']}")


def main():
    values = env_file()
    rehearsal = Rehearsal(
        {
            "analyst": values["MSA_UI_ANALYST_API_KEY"],
            "risk_manager": values["MSA_UI_RISK_MANAGER_API_KEY"],
        }
    )
    library = {event["event_id"]: event for event in rehearsal.call("analyst", "GET", "/events")}
    for event_id in sys.argv[1:] or ["EVENT-A", "EVENT-B"]:
        rehearsal.started = time.monotonic()
        rehearsal.run(library[event_id])
    if rehearsal.failures:
        raise SystemExit("\nРепетиция не прошла:\n- " + "\n- ".join(rehearsal.failures))
    print("\nРепетиция прошла.")


if __name__ == "__main__":
    main()
