"""The HTTP API end to end on SQLite with the mock LLM: catalogs, portfolios, snapshots, a run.

The run goes through the real agents and the MCP servers in-process: exposure resolves the
positions' data through ``mcp-portfolio``, every position is calculated through
``mcp-models.run_model``, and both leave audited tool calls.
"""

import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from demo.seed_demo import seed_demo
from msa.api.main import create_app
from msa.db.migrate import migrate
from msa.db.session import engine
from msa.graph.checkpoint import build_checkpointer

ANALYST, RISK = "analyst-key", "risk-key"
FINAL = {"human_fix_graph", "human_approval", "completed", "rejected", "failed"}


def keys():
    expires = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    return {
        ANALYST: {
            "actor": "analyst",
            "role": "analyst",
            "scopes": ["demo:*", "production:*"],
            "expires_at": expires,
        },
        RISK: {
            "actor": "risk",
            "role": "risk_manager",
            "scopes": ["demo:*", "production:*"],
            "expires_at": expires,
        },
    }


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    root = tmp_path_factory.mktemp("api")
    bind = engine(f"sqlite:///{root / 'msa.db'}")
    migrate(bind)
    seed_demo(bind)
    with build_checkpointer() as saver:
        app = create_app(
            bind=bind,
            keys=keys(),
            checkpointer=saver,
            storage_root=root / "objects",
            mock_llm=True,
            recover=False,
        )
        with TestClient(app) as test_client:
            yield test_client
    bind.dispose()


def get(client, path, key=ANALYST, **params):
    response = client.get(path, headers={"X-API-Key": key}, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def post(client, path, body, key=ANALYST, expect=(200, 201, 202)):
    response = client.post(path, headers={"X-API-Key": key}, json=body)
    assert response.status_code in expect, response.text
    return response.json()


def wait(client, run_id):
    for _ in range(600):
        status = get(client, f"/v1/demo/runs/{run_id}")
        if status["status"] in FINAL:
            return status
        time.sleep(0.05)
    raise AssertionError("run did not stop")


def test_the_catalogs_come_from_the_plugins(client):
    catalog = get(client, "/v1/asset-types")
    types = {item["asset_type"]: item for item in catalog["types"]}
    assert {"corp_loan", "bond_fixed", "pf_escrow", "leasing"} <= set(types)
    loan = types["corp_loan"]
    assert loan["default_model"] == "credit.corporate.v3"
    assert loan["terms_schema"]["title"] and loan["position_schema"]["properties"]["ead"]
    assert [group["group_id"] for group in loan["editor"]][:2] == ["position", "statement"]
    assert catalog["metrics"]["credit.delta_expected_loss"]["unit"] == "RUB_million"
    assert catalog["flags"]["calibration_synthetic"]
    models = {item["model_id"]: item for item in get(client, "/v1/models")}
    assert models["credit.bond.v3"]["instrument_types"] == ["bond_fixed", "bond_floater"]
    assert "credit.loss" in models["credit.bond.v3"]["slices"]
    factors = {item["factor_id"]: item for item in get(client, "/v1/factors")}
    assert factors["credit.working_capital"]["application"] == "additive"
    assert factors["market.fx"]["scope"] == "currency_pair"
    assert {item["slice_id"] for item in get(client, "/v1/slices")} >= {"credit.loss", "market.pnl"}
    docs = get(client, "/v1/docs")
    assert docs["platform"][0]["slug"] == "scenario"
    assert "credit" in {group["plugin_id"] for group in docs["plugins"]}
    (workflow,) = [w for w in get(client, "/v1/workflows") if w["workflow_id"] == "stress_test"]
    assert [stage["title"] for stage in workflow["stages"]][0] == "Анализ события"
    assert {p["point_id"] for p in workflow["extension_points"]} == {
        "after_event_parsed",
        "before_scenario_approval",
        "after_calculation",
        "before_report",
    }


def test_portfolios_and_snapshots_are_served_and_imported(client):
    listed = {row["portfolio_id"] for row in get(client, "/v1/demo/portfolios")}
    assert {"MULTI-ASSET", "ATYPICAL-BORROWERS", "LOAD-TEST"} <= listed
    bundle = get(client, "/v1/demo/portfolios/MULTI-ASSET")
    assert bundle["portfolio"]["snapshot_id"] == "SYNTHETIC-2026-09-11"
    assert {p["position_id"] for p in bundle["positions"]} >= {
        "BOND-CONCRETE",
        "PROJECT-HOUSING",
        "LOAN-MACHINERY",
        "LOAN-LEASING",
        "LOAN-FERTILIZER",
    }
    rates = get(client, "/v1/demo/snapshots/SYNTHETIC-2026-09-11", kind="rate")
    assert [item["subject"] for item in rates["items"]] == ["risk_free:RUB"]

    snapshot = {
        "snapshot_id": "TEST-SNAP",
        "as_of": "2026-09-30",
        "label": "Тестовый снимок",
        "items": [
            {
                "item_id": "fx:USD/RUB",
                "kind": "fx_rate",
                "subject": "USD/RUB",
                "observed_on": "2026-09-30",
                "values": {
                    "rate": {"value": 92.5, "unit": "RUB_per_unit", "evidence": [_evidence()]}
                },
            }
        ],
    }
    post(client, "/v1/demo/snapshots", snapshot)
    post(client, "/v1/demo/snapshots", snapshot)  # The same content again is a no-op.
    changed = {**snapshot, "label": "Другой"}
    post(client, "/v1/demo/snapshots", changed, expect=(409,))
    late = {**snapshot, "snapshot_id": "LATE", "as_of": "2026-09-01"}
    post(client, "/v1/demo/snapshots", late, expect=(422,))


def test_an_analyst_draft_becomes_a_bundle_and_a_snapshot(client):
    draft = {
        "name": "Черновик",
        "positions": [
            {
                "position_id": "P1",
                "name": "Дистрибьютор",
                "instrument_type": "corp_loan",
                "okved": "46.63",
                "values": {
                    "ead": 500.0,
                    "lgd": 0.45,
                    "revenue": 12000.0,
                    "cogs": 9000.0,
                    "net_debt": 2500.0,
                    "borrowing_rate": 0.16,
                },
                "tables": {
                    "covenants": [
                        {
                            "metric": "icr",
                            "operator": "ge",
                            "threshold": 1.5,
                            "test_dates": ["2026-12-31"],
                        }
                    ]
                },
            }
        ],
    }
    saved = post(client, "/v1/demo/portfolios/draft", draft)
    bundle = get(client, f"/v1/demo/portfolios/{saved['portfolio_id']}")
    (instrument,) = bundle["instruments"]
    assert instrument["terms"]["covenants"][0]["unit"] == "ratio"
    snapshot = get(client, f"/v1/demo/snapshots/{bundle['portfolio']['snapshot_id']}")
    (statement,) = snapshot["items"]
    assert statement["values"]["revenue"]["evidence"][0]["author"] == "analyst"
    wrong = {**draft, "positions": [{**draft["positions"][0], "values": {"ebitda": 1.0}}]}
    post(client, "/v1/demo/portfolios/draft", wrong, expect=(422,))


def test_a_run_goes_from_the_event_to_the_approved_report(client):
    status = post(
        client,
        "/v1/demo/runs",
        {"portfolio_id": "MULTI-ASSET", "event": {"kind": "library", "id": "RECYCLING-FEE"}},
    )
    status = wait(client, status["run_id"])
    run_id = status["run_id"]
    assert status["status"] == "human_fix_graph", status
    assert status["workflow_id"] == "stress_test" and status["plugins"]["credit"] == "3.4.0"
    stop = status["pending_interrupt"][0]["payload"]
    post(client, f"/v1/demo/runs/{run_id}/resume", {"graph": stop["graph"]})
    status = wait(client, run_id)
    assert status["status"] == "human_approval", status
    artifacts = get(client, f"/v1/demo/runs/{run_id}/artifacts")
    completed = [r for r in artifacts["results"] if r["execution"] == "completed"]
    assert completed and all(r["scenario_id"] == status["scenario_id"] for r in completed)
    assert "credit.loss" in artifacts["portfolio"]["slices"]
    assert artifacts["snapshot"]["snapshot_id"] == "SYNTHETIC-2026-09-11"
    assert artifacts["workflow"]["stages"][2]["title"] == "Расчёт по позициям"
    report = get(client, f"/v1/demo/runs/{run_id}/report")
    assert "### Итог" in report["summary"] and report["numbers"]
    trace = get(client, f"/v1/demo/runs/{run_id}/trace")
    assert all(item["lineage"] for item in trace["numbers"])
    activity = get(client, f"/v1/demo/runs/{run_id}/activity")
    tools = {item["name"] for item in activity["items"] if item["kind"] == "tool"}
    assert {"mcp-portfolio.resolve_inputs", "mcp-models.run_model"} <= tools
    post(client, f"/v1/demo/runs/{run_id}/resume", {"approved": True}, key=RISK)
    assert wait(client, run_id)["status"] == "completed"


def test_a_stopped_demo_run_is_deleted_with_its_results(client):
    status = post(
        client,
        "/v1/demo/runs",
        {"portfolio_id": "MULTI-ASSET", "event": {"kind": "library", "id": "RECYCLING-FEE"}},
    )
    run_id = wait(client, status["run_id"])["run_id"]
    headers = {"X-API-Key": ANALYST}
    assert client.delete(f"/v1/demo/runs/{run_id}", headers=headers).status_code == 204
    assert client.get(f"/v1/demo/runs/{run_id}", headers=headers).status_code == 404
    assert run_id not in {row["run_id"] for row in get(client, "/v1/demo/runs")}
    assert client.delete(f"/v1/demo/runs/{run_id}", headers=headers).status_code == 404
    # The risk manager does not delete, and production runs have no delete at all.
    assert client.delete(f"/v1/demo/runs/{run_id}", headers={"X-API-Key": RISK}).status_code == 403
    assert client.delete(f"/v1/runs/{run_id}", headers=headers).status_code == 405


def _evidence():
    return {
        "kind": "expert_assumption",
        "source_id": "test",
        "locator": "fx",
        "fragment_sha256": "0" * 64,
        "author": "test",
        "as_of": "2026-09-30",
    }


def test_equity_scenario_check_and_resume_reject_unmapped_operating_shock(client):
    saved = post(
        client,
        "/v1/demo/portfolios/draft",
        {
            "name": "Проверка акции",
            "positions": [
                {
                    "position_id": "EQ1",
                    "name": "Эмитент",
                    "instrument_type": "common_stock",
                    "okved": "46.63",
                    "values": {
                        "quantity": 100,
                        "ticker": "TEST",
                        "price": 250,
                        "beta_market": 1,
                        "beta_sector": 1,
                        "residual_volatility": 0,
                        "dividend": 0,
                    },
                }
            ],
        },
    )
    bundle = get(client, f"/v1/demo/portfolios/{saved['portfolio_id']}")
    assert bundle["instruments"][0]["terms"]["sector"] == "industrials"
    status = post(
        client,
        "/v1/demo/runs",
        {
            "portfolio_id": saved["portfolio_id"],
            # Not a library event: the mock profile's generic answer names every direct
            # factor of the portfolio for the analyst to quantify.
            "event": {"kind": "text", "text": "Введён утилизационный сбор на спецтехнику."},
        },
    )
    status = wait(client, status["run_id"])
    stop = status["pending_interrupt"][0]["payload"]
    parameters = {
        k: v for k, v in stop["macro_parameters"].items() if v["factor"].startswith("credit.")
    }
    checked = post(
        client,
        "/v1/demo/scenario-check",
        {
            "run_id": status["run_id"],
            "graph": stop["graph"],
            "macro_parameters": parameters,
            "required": True,
        },
    )
    assert any("EQ1" in v["message"] for v in checked["violations"])
    post(
        client,
        f"/v1/demo/runs/{status['run_id']}/resume",
        {
            "graph": stop["graph"],
            "macro_parameters": parameters,
        },
        expect=(422,),
    )
    assert get(client, f"/v1/demo/runs/{status['run_id']}")["status"] == "human_fix_graph"
    checked = post(
        client,
        "/v1/demo/scenario-check",
        {
            "run_id": status["run_id"],
            "graph": stop["graph"],
            "macro_parameters": stop["macro_parameters"],
            "required": True,
        },
    )
    assert checked["violations"] == []
