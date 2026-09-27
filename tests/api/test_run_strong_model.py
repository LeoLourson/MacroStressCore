"""Choosing the strong model through the API: refused when the provider has none."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from demo.seed_demo import seed_demo
from msa.api.main import create_app
from msa.db.migrate import migrate
from msa.db.session import engine
from msa.graph.checkpoint import build_checkpointer

ANALYST = "analyst-key"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    root = tmp_path_factory.mktemp("strong")
    bind = engine(f"sqlite:///{root / 'msa.db'}")
    migrate(bind)
    seed_demo(bind)
    expires = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    keys = {
        ANALYST: {
            "actor": "analyst",
            "role": "analyst",
            "scopes": ["demo:*"],
            "expires_at": expires,
        }
    }
    with build_checkpointer() as saver:
        app = create_app(
            bind=bind,
            keys=keys,
            checkpointer=saver,
            storage_root=root / "objects",
            mock_llm=True,
            recover=False,
        )
        with TestClient(app) as test_client:
            yield test_client
    bind.dispose()


def body(strong=None):
    payload = {
        "portfolio_id": "MULTI-ASSET",
        "event": {"kind": "library", "id": "RECYCLING-FEE"},
    }
    if strong is not None:
        payload["strong_model"] = strong
    return payload


def test_strong_model_is_refused_when_the_provider_has_none(client):
    response = client.post("/v1/demo/runs", headers={"X-API-Key": ANALYST}, json=body(True))
    assert response.status_code == 422, response.text


def test_a_run_without_a_strong_model_records_the_provider_default(client):
    response = client.post("/v1/demo/runs", headers={"X-API-Key": ANALYST}, json=body())
    assert response.status_code == 202, response.text
    run_id = response.json()["run_id"]
    status = client.get(f"/v1/demo/runs/{run_id}", headers={"X-API-Key": ANALYST})
    assert status.status_code == 200, status.text
    assert status.json()["versions"]["model_version"] == "mock"
