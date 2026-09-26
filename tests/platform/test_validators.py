"""msa.validators: the dispatcher (V1 + registered rules) and V2/V7/V8/V9/V11 individually."""

import pytest

from msa.validators import register, validate
from msa.validators.v2_units import UnitsValidator
from msa.validators.v7_acyclic import AcyclicValidator
from msa.validators.v8_evidence import EvidenceValidator
from msa.validators.v9_numbers import NumbersValidator
from msa.validators.v11_macro_hash import check as check_macro_hash

SHA = "a" * 64


def evidence():
    return [{"kind": "document", "source_id": "S", "locator": "l", "fragment_sha256": SHA}]


def node(node_id, kind, **overrides):
    values = {"id": node_id, "kind": kind, "label": node_id}
    values.update(overrides)
    return values


def edge(src, dst, **overrides):
    values = {
        "src": src,
        "dst": dst,
        "sign": 1,
        "elasticity": {"family": "point", "value": 1.0},
        "lag_months": 0,
        "evidence": evidence(),
    }
    values.update(overrides)
    return values


def graph_payload(*, nodes=None, edges=None):
    return {
        "event_id": "event",
        "nodes": nodes
        if nodes is not None
        else [
            node("event", "event"),
            node("channel", "channel"),
        ],
        "edges": edges if edges is not None else [edge("event", "channel")],
        "factor_elasticity": {},
    }


# -- dispatcher.validate(): unknown artifact / V1 -------------------------------------------


def test_validate_unknown_artifact_type_returns_v1_failure():
    verdicts = validate("NoSuchContract", {})
    assert len(verdicts) == 1
    assert verdicts[0].ok is False
    assert verdicts[0].rule_id == "V1"


def test_validate_contract_violation_reports_v1_path_with_json_pointer_escaping():
    verdicts = validate("PortfolioBundle", {"portfolio": {"portfolio_id": "p"}})
    assert any(v.rule_id == "V1" and not v.ok for v in verdicts)


def test_validate_a_valid_transmission_graph_runs_v2_v7_v8():
    verdicts = validate("TransmissionGraph", graph_payload())
    rule_ids = {v.rule_id for v in verdicts}
    assert {"V1", "V2", "V7", "V8"} <= rule_ids
    assert all(v.ok for v in verdicts)


def test_validate_array_artifact_type_suffix():
    verdicts = validate("CalculationResult[]", [])
    assert verdicts[0].ok is True


def test_validate_invalid_graph_still_surfaces_v7_v8_findings():
    # event_id names no event node, so V1 (the TransmissionGraph contract) fails; the payload
    # also has a cycle and an edge without evidence, so V7 and V8's own (failing) findings are
    # still useful and are appended even though V1 rejected the contract.
    payload = graph_payload(
        nodes=[node("event", "channel"), node("channel", "channel")],
        edges=[edge("event", "channel"), edge("channel", "event", evidence=[])],
    )
    verdicts = validate("TransmissionGraph", payload)
    assert any(v.rule_id == "V1" and not v.ok for v in verdicts)
    assert any(v.rule_id == "V7" and not v.ok for v in verdicts)
    assert any(v.rule_id == "V8" and not v.ok for v in verdicts)
    # V2 and V9-style rules are not appended for an invalid contract; only V7/V8 are.
    assert not any(v.rule_id == "V2" for v in verdicts)


# -- register() -------------------------------------------------------------------------


def test_register_rejects_v1_as_extension_rule_id():
    with pytest.raises(ValueError, match="V1 is built in"):
        register("V1", UnitsValidator(), ["TransmissionGraph"])


def test_register_rejects_rule_id_out_of_range():
    with pytest.raises(ValueError, match="V1 is built in"):
        register("V12", UnitsValidator(), ["TransmissionGraph"])


def test_register_rejects_duplicate_rule_id():
    with pytest.raises(ValueError, match="already registered"):
        register("V2", UnitsValidator(), ["TransmissionGraph"])


def test_register_rejects_unknown_contract_name():
    with pytest.raises(ValueError, match="applies_to must name known contracts"):
        register("V10", UnitsValidator(), ["NoSuchContract"])


def test_register_rejects_empty_applies_to():
    with pytest.raises(ValueError, match="applies_to must name known contracts"):
        register("V10", UnitsValidator(), [])


# -- V2: UnitsValidator.check_graph -------------------------------------------------------


def test_v2_flags_unknown_factor_on_a_factor_node():
    payload = graph_payload(
        nodes=[node("event", "event"), node("f", "factor", factor="no.such.factor")],
        edges=[edge("event", "f")],
    )
    verdicts = UnitsValidator().check(payload)
    assert any(not v.ok and "Неизвестный фактор" in v.message for v in verdicts)


def test_v2_requires_key_for_direct_factor_node():
    # Currency-pair factors can appear in the graph, but must identify the pair.
    payload = graph_payload(
        nodes=[node("event", "event"), node("f", "factor", factor="market.fx")],
        edges=[edge("event", "f")],
    )
    verdicts = UnitsValidator().check(payload)
    assert any(not v.ok and "нужен ключ" in v.message for v in verdicts)


def test_v2_valid_graph_reports_ok():
    verdicts = UnitsValidator().check(graph_payload())
    assert all(v.ok for v in verdicts)


def test_v2_check_bundle_flags_unregistered_instrument_type():
    # PortfolioBundle's own contract only checks that references resolve; it does not know
    # which instrument types the registry serves, so an unknown type reaches V2 as data.
    payload = {
        "portfolio": {"portfolio_id": "p", "name": "P"},
        "parties": [],
        "instruments": [{"instrument_id": "I1", "instrument_type": "no.such.type", "name": "I1"}],
        "positions": [{"position_id": "POS1", "instrument_id": "I1"}],
    }
    verdicts = UnitsValidator().check(payload)
    assert any(not v.ok for v in verdicts)


# -- V7: AcyclicValidator -----------------------------------------------------------------


def test_v7_accepts_an_acyclic_graph():
    verdicts = AcyclicValidator().check(graph_payload())
    assert verdicts[0].ok is True


def test_v7_rejects_a_cycle():
    payload = graph_payload(
        nodes=[node("a", "event"), node("b", "channel")],
        edges=[edge("a", "b"), edge("b", "a")],
    )
    verdicts = AcyclicValidator().check(payload)
    assert verdicts[0].ok is False
    assert "cycle" in verdicts[0].message.lower()


def test_v7_malformed_data_returns_no_findings():
    assert AcyclicValidator().check({"nodes": "not-a-list", "edges": []}) == []
    assert AcyclicValidator().check({}) == []


def test_v7_edge_to_unknown_node_returns_no_findings():
    payload = graph_payload(edges=[edge("event", "nowhere")])
    assert AcyclicValidator().check(payload) == []


# -- V8: EvidenceValidator ------------------------------------------------------------------


def test_v8_accepts_edges_with_evidence():
    verdicts = EvidenceValidator().check(graph_payload())
    assert verdicts[0].ok is True


def test_v8_flags_edge_without_evidence():
    payload = graph_payload(edges=[edge("event", "channel", evidence=[])])
    verdicts = EvidenceValidator().check(payload)
    assert verdicts[0].ok is False
    assert verdicts[0].path == "/edges/0/evidence"


def test_v8_malformed_data_returns_no_findings():
    assert EvidenceValidator().check({}) == []


# -- V9: NumbersValidator -------------------------------------------------------------------


def _report(**overrides):
    values = {
        "run_id": "RUN1",
        "summary": "Итог 1,50.",
        "recommendations": [],
        "assumptions": [],
        "sources": [],
        "numbers": [{"value": 1.5, "metric_path": "/m/value", "rounding": 2}],
    }
    values.update(overrides)
    return values


def test_v9_without_a_metric_tree_and_no_numbers_is_ok():
    verdicts = NumbersValidator().check(_report(summary="без чисел", numbers=[]))
    assert verdicts[0].ok is True


def test_v9_without_a_metric_tree_but_with_numbers_fails():
    verdicts = NumbersValidator().check(_report())
    assert verdicts[0].ok is False
    assert "Quantitative metric tree is required" in verdicts[0].message


def test_v9_with_a_tree_resolves_a_matching_number():
    tree = {"m": {"value": 1.5}}
    verdicts = NumbersValidator(metric_tree=tree).check(_report())
    assert verdicts[0].ok is True


def test_v9_with_a_tree_flags_untraceable_number_in_summary():
    tree = {"m": {"value": 1.5}}
    verdicts = NumbersValidator(metric_tree=tree).check(_report(summary="Итог 1,50 и ещё 9,99."))
    assert any(not v.ok for v in verdicts)


def test_v9_accepts_explicit_metrics_argument_over_constructor_tree():
    verdicts = NumbersValidator(metric_tree={"other": {}}).check(
        _report(), metrics={"m": {"value": 1.5}}
    )
    assert verdicts[0].ok is True


# -- V11: macro_draws_sha256 -------------------------------------------------------------


def _calc_result(macro_hash, position_id="POS1"):
    return {
        "position_id": position_id,
        "instrument_id": "I1",
        "instrument_type": "t",
        "plugin_id": "p",
        "plugin_version": "1.0.0",
        "model_id": "m",
        "model_version": "1.0.0",
        "as_of": "2026-01-01",
        "horizon": 12,
        "seed": 1,
        "execution": "completed",
        "status": "ok",
        "macro_draws_sha256": macro_hash,
    }


def test_v11_ok_when_every_result_shares_the_same_hash():
    verdicts = check_macro_hash([_calc_result(SHA), _calc_result(SHA, "POS2")])
    assert verdicts[0].ok is True


def test_v11_flags_result_with_a_different_hash():
    other = "b" * 64
    verdicts = check_macro_hash([_calc_result(SHA), _calc_result(other, "POS2")])
    failures = [v for v in verdicts if not v.ok]
    assert len(failures) == 1
    assert "POS2" in failures[0].message


def test_v11_flags_result_with_no_hash_at_all():
    result = _calc_result(SHA)
    del result["macro_draws_sha256"]
    verdicts = check_macro_hash([result])
    assert verdicts[0].ok is False


def test_v11_no_results_is_ok_with_a_distinct_message():
    verdicts = check_macro_hash([])
    assert verdicts[0].ok is True
    assert "No position branches" in verdicts[0].message


def test_v11_explicit_expected_hash_overrides_the_first_result():
    verdicts = check_macro_hash([_calc_result(SHA)], expected_hash="b" * 64)
    assert verdicts[0].ok is False
