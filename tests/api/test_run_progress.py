"""msa.api.run_service: the step the run is on, and the LLM call it is waiting for."""

import pytest

from msa.graph import activity
from msa.api.run_service import RunService
from msa.db.database import Database
from msa.db.migrate import migrate
from msa.db.repositories.runs import ApplicationRunRepository
from msa.db.session import engine

RUN = "RUN1"
SCOPE = "demo"


@pytest.fixture
def service(tmp_path):
    bind = engine(f"sqlite:///{tmp_path / 'runs.db'}")
    migrate(bind)
    runs = RunService(Database(bind), None, None, None)
    yield runs
    runs.close()
    bind.dispose()


def make_run(db, run_id=RUN):
    with db.session(SCOPE) as session:
        ApplicationRunRepository(session).create_run(
            run_id,
            "event text",
            seed=1,
            mc_points=8192,
            workflow_id="stress_test",
            workflow_version="2.0.0",
            portfolio_id="P",
            snapshot_id="S",
        )
    db.put(
        SCOPE,
        "api_job",
        {
            "job_id": run_id,
            "kind": "run",
            "principal": "analyst",
            "payload": {},
            "status": "running",
            "state": {},
            "error": None,
        },
    )


def test_progress_writes_the_node_and_saves_results_only_after_the_first_state(service):
    make_run(service.db)
    step = service.progress(SCOPE, service.job(SCOPE, RUN))
    first = {
        "trace": ["quant_agent"],
        "sorted_results": [{"position_id": "POS1"}],
        "portfolio_result": {"slices": {}},
    }
    step(first)
    assert service.job(SCOPE, RUN)["state"]["node"] == "quant_agent"
    assert service.results(SCOPE, RUN) == ([], None)  # the first state is already saved
    step({"trace": ["aggregate"], **{k: v for k, v in first.items() if k != "trace"}})
    assert service.job(SCOPE, RUN)["state"]["node"] == "aggregate"
    assert service.results(SCOPE, RUN) == ([], None)  # unchanged numbers
    changed = {
        "trace": ["advisory_agent"],
        "sorted_results": [{"position_id": "POS2"}],
        "portfolio_result": {"slices": {"credit.loss": {}}},
    }
    step(changed)
    results, portfolio = service.results(SCOPE, RUN)
    assert [result["position_id"] for result in results] == ["POS2"]
    assert portfolio == {"slices": {"credit.loss": {}}}


def test_progress_handles_a_state_with_no_trace(service):
    make_run(service.db)
    step = service.progress(SCOPE, service.job(SCOPE, RUN))
    step({"sorted_results": [], "portfolio_result": None})
    assert service.job(SCOPE, RUN)["state"] == {}


def test_status_reports_the_waiting_llm_call(service):
    make_run(service.db)
    assert service.status(SCOPE, RUN)["llm_waiting"] is None
    with activity.node_call(RUN, "causal_agent", 1):
        with activity.llm_waiting({"model": "m", "schema": "S", "purpose": "answer"}):
            waiting = service.status(SCOPE, RUN)["llm_waiting"]
            assert waiting["node"] == "causal_agent"
            assert waiting["model"] == "m"
    assert service.status(SCOPE, RUN)["llm_waiting"] is None


def test_progress_writes_the_deduped_upcoming_nodes(service):
    make_run(service.db)
    step = service.progress(SCOPE, service.job(SCOPE, RUN))
    state = {"trace": ["validate_causal"], "sorted_results": [], "portfolio_result": None}
    step(state, ["causal_agent", "causal_agent", "exposure_profiler"])
    assert service.job(SCOPE, RUN)["state"] == {
        "node": "validate_causal",
        "next": ["causal_agent", "exposure_profiler"],
    }
    # A retry: the same node with another next node is written again.
    step(state, ["exposure_profiler"])
    assert service.job(SCOPE, RUN)["state"] == {
        "node": "validate_causal",
        "next": ["exposure_profiler"],
    }


def test_progress_without_trace_or_upcoming_writes_nothing(service):
    make_run(service.db)
    step = service.progress(SCOPE, service.job(SCOPE, RUN))
    step({"sorted_results": [], "portfolio_result": None}, [])
    assert service.job(SCOPE, RUN)["state"] == {}


def test_activity_appends_a_waiting_item_that_is_not_counted(service):
    make_run(service.db)
    service.db.audit(
        SCOPE,
        "graph",
        "llm.completed",
        run_id=RUN,
        node="causal_agent",
        attempt=1,
        details={"model": "done", "prompt_tokens": 3, "completion_tokens": 1},
    )
    with activity.node_call(RUN, "advisory_agent", 1):
        with activity.llm_waiting({"model": "pending", "schema": "S", "purpose": "answer"}):
            report = service.activity(SCOPE, RUN)
    assert report["llm"]["calls"] == 1
    assert report["llm"]["failed"] == 0
    assert report["llm"]["prompt_tokens"] == 3
    waiting = [item for item in report["items"] if item["status"] == "waiting"]
    assert len(waiting) == 1
    assert waiting[0]["kind"] == "llm"
    assert waiting[0]["name"] == "pending"
    assert waiting[0]["node"] == "advisory_agent"
    assert service.activity(SCOPE, RUN)["llm"]["calls"] == 1
