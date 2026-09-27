"""msa.agents.causal: the mock profile's fallback never leaves a channel without a factor."""

from msa.agents.causal import CausalAgent
from msa.agents.ingest import fragment
from msa.contracts import SourceDocument
from msa.validators import validate


def document(text="Событие без подготовленного ответа."):
    part = fragment(text, "p1")
    return SourceDocument(
        doc_id="unknown-event", sha256=part.sha256, mime="text/plain", fragments=[part]
    )


def test_without_any_factor_only_the_event_node_survives():
    response = CausalAgent._mock_response(document(), set(), {"factors": [], "positions": []})
    assert response["graph"]["nodes"] == [{"id": "event", "kind": "event", "label": "event"}]
    assert response["graph"]["edges"] == []
    assert response["direct_okved"] == []
    assert response["scenario"] == {}


def test_a_direct_factor_keeps_the_channel_and_reaches_the_factor():
    context = {
        "factors": [
            {
                "factor_id": "market.fx",
                "label": "Курс",
                "scope": "currency_pair",
                "unit": "fraction",
            }
        ],
        "positions": [{"factors": [{"factor_id": "market.fx", "key": "USD/RUB"}]}],
    }
    response = CausalAgent._mock_response(document(), set(), context)
    edges = [(item["src"], item["dst"]) for item in response["graph"]["edges"]]
    assert edges == [("event", "channel"), ("channel", "direct_0")]
    assert all(verdict.ok for verdict in validate("TransmissionGraph", response["graph"]))
