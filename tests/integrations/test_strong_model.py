"""The provider's strong model: declared, advertised by the API, and chosen by a run."""

import pytest
from pydantic import ValidationError

from msa.api.agent_service import AgentService
from msa.contracts.api import RunRequest
from msa.integrations.llm.client import LLMClient
from msa.integrations.llm.providers import Provider, active


def provider(**overrides):
    base = {
        "name": "test",
        "base_url": "http://127.0.0.1:1234/v1",
        "model": "test-model",
        "api_key": "",
        "json_mode": "json_schema",
        "timeout": 1.0,
        "max_tokens": None,
        "external": False,
    }
    base.update(overrides)
    return Provider(**base)


def test_provider_strong_model_defaults_to_none():
    assert provider().strong_model is None
    assert provider(strong_model="big").strong_model == "big"


def test_describe_shows_the_strong_model_and_never_the_api_key():
    described = provider(api_key="secret", strong_model="big").describe()
    assert described["strong_model"] == "big"
    assert "api_key" not in described
    assert "secret" not in described.values()


@pytest.mark.parametrize("name", ["local", "mock"])
def test_profiles_without_a_strong_model(monkeypatch, name):
    monkeypatch.setenv("MSA_LLM_PROVIDER", name)
    assert active().strong_model is None


def test_the_deepseek_profile_carries_its_strong_model(monkeypatch):
    monkeypatch.setenv("MSA_LLM_PROVIDER", "deepseek")
    built = active()
    assert built.strong_model == "deepseek-v4-pro"
    assert built.describe()["strong_model"] == "deepseek-v4-pro"
    assert "api_key" not in built.describe()


def test_llm_with_mock_reports_no_strong_model(tmp_path):
    described = AgentService(None, tmp_path, mock_llm=True).llm()
    assert described["provider"] == "mock"
    assert described["strong_model"] is None


def test_stamp_records_the_given_model_or_the_provider_default(tmp_path):
    agents = AgentService(None, tmp_path, mock_llm=True)
    assert agents.stamp("deepseek-v4-pro")["model_version"] == "deepseek-v4-pro"
    assert agents.stamp()["model_version"] == "mock"
    assert agents.stamp(None)["model_version"] == "mock"


def test_llm_client_is_none_with_mock_and_uses_the_chosen_model(monkeypatch, tmp_path):
    assert AgentService(None, tmp_path, mock_llm=True).llm_client("demo", "chosen") is None
    monkeypatch.setenv("MSA_LLM_PROVIDER", "deepseek")
    agents = AgentService(None, tmp_path, mock_llm=False)
    chosen = agents.llm_client("demo", "deepseek-v4-pro")
    assert isinstance(chosen, LLMClient)
    assert chosen.model == "deepseek-v4-pro"
    assert agents.llm_client("demo").model == "deepseek-flash"


def test_run_request_strong_model_defaults_to_false():
    request = RunRequest(portfolio_id="PF1", event={"kind": "text", "text": "t"})
    assert request.strong_model is False


def test_run_request_strong_model_is_strict():
    with pytest.raises(ValidationError):
        RunRequest(
            portfolio_id="PF1",
            event={"kind": "text", "text": "t"},
            strong_model="true",
        )
