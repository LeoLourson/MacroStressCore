"""CausalAgent._attributed: the model's magnitude claim becomes an attributed assumption."""

import pytest
from pydantic import ValidationError

from msa.agents.base import AgentError
from msa.agents.causal import CausalAgent
from msa.agents.causal_output import ScenarioParameter
from msa.contracts import SourceDocument
from msa.db.repositories.runs import json_payload
from tests.support import positions

from .test_causal_plugins import (
    CapturingLLM,
    library_payload,
    payload_for,
    property_position,
    property_registry,
)


def estimated_payload():
    """A payload and mock answer whose scenario has one estimated triangular parameter."""
    payload = payload_for([property_position()], property_registry())
    document = SourceDocument.model_validate(payload["document"])
    response = CausalAgent._mock_response(document, set(), payload["portfolio_context"])
    return payload, response


def test_estimated_magnitude_is_attributed_to_the_model():
    payload, response = estimated_payload()
    cited = response["scenario"]["direct_0"]["evidence"][0]
    output = CausalAgent(llm=CapturingLLM(response)).run_structured(payload)
    parameter = output.scenario["direct_0"]
    assert parameter.kind == "triangular"
    assert parameter.evidence
    for evidence in parameter.evidence:
        assert evidence.kind == "expert_assumption"
        assert evidence.author.startswith("LLM:")
        assert "оценка модели" in evidence.author
        assert evidence.as_of is not None
        assert evidence.locator == cited["locator"]
        assert evidence.fragment_sha256 == cited["fragment_sha256"]
    assert "magnitude" not in parameter.model_dump()


def test_stated_magnitude_keeps_its_document_evidence():
    output = CausalAgent(mock=True).run_structured(library_payload("RECYCLING-FEE", positions()))
    parameter = next(iter(output.scenario.values()))
    assert parameter.evidence[0].kind == "document"
    assert parameter.evidence[0].author is None
    assert parameter.evidence[0].as_of is None


def test_estimated_point_magnitude_is_rejected():
    payload, response = estimated_payload()
    response["scenario"]["direct_0"]["kind"] = "point"
    response["scenario"]["direct_0"]["value"] = -0.1
    with pytest.raises(AgentError):
        CausalAgent(llm=CapturingLLM(response)).run_structured(payload)


def test_estimated_magnitude_without_evidence_is_rejected():
    payload, response = estimated_payload()
    response["scenario"]["direct_0"]["evidence"] = []
    with pytest.raises(AgentError):
        CausalAgent(llm=CapturingLLM(response)).run_structured(payload)


def test_a_scenario_parameter_without_a_magnitude_fails_validation():
    payload, response = estimated_payload()
    del response["scenario"]["direct_0"]["magnitude"]
    with pytest.raises(ValidationError):
        CausalAgent(llm=CapturingLLM(response)).run_structured(payload)


def test_the_attributed_scenario_is_storable_as_macro_parameters():
    payload, response = estimated_payload()
    output = CausalAgent(llm=CapturingLLM(response)).run_structured(payload)
    stored = json_payload(output.scenario)
    for spec in stored.values():
        ScenarioParameter.model_validate(spec)
