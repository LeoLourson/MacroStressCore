"""msa.engine.scenario_set: the approved scenario set and its joint realisations."""

from datetime import date

import numpy as np
import pytest

from msa.contracts.scenario import MacroParameter
from msa.engine.scenario_set import (
    Realisations,
    ScenarioSet,
    idiosyncratic_draws,
    scenario_id,
    scenario_set_from_parameters,
)
from msa.plugin_sdk.model import IdiosyncraticFactor

POINTS = 64
REPLICATES = 8


def parameter(value=0.1, **overrides):
    values = dict(kind="point", value=value, unit="fraction")
    values.update(overrides)
    return MacroParameter(**values)


def shock(name="minimal.noise:I1", subject="I1", sigma=0.01):
    return IdiosyncraticFactor(name=name, subject=subject, sigma=sigma)


def scenario_set(parameters=None, **overrides):
    values = dict(
        parameters=parameters or {"p1": parameter()},
        points=POINTS,
        replicates=REPLICATES,
    )
    values.update(overrides)
    return ScenarioSet(**values)


# -- ScenarioSet validation --------------------------------------------------------------


def test_scenario_set_requires_at_least_one_parameter():
    with pytest.raises(ValueError, match="at least one confirmed parameter"):
        ScenarioSet(parameters={})


def test_scenario_set_points_must_be_a_power_of_two():
    with pytest.raises(ValueError, match="power of two"):
        scenario_set(points=100)


def test_scenario_set_accepts_power_of_two_points():
    assert scenario_set(points=128).points == 128


def test_scenario_set_replicates_below_minimum_rejected():
    with pytest.raises(ValueError, match="at least 8 independent replicates"):
        scenario_set(replicates=4)


def test_scenario_set_idiosyncratic_names_must_be_unique():
    with pytest.raises(ValueError, match="unique names"):
        scenario_set(idiosyncratic=(shock("dup"), shock("dup")))


def test_scenario_set_idiosyncratic_cannot_collide_with_a_parameter_name():
    with pytest.raises(ValueError, match="cannot share a scenario parameter's name"):
        scenario_set(
            parameters={"clash": parameter()},
            idiosyncratic=(shock("clash"),),
        )


# -- spec() / from_spec() round trip ------------------------------------------------------


def test_spec_round_trips_through_from_spec():
    p2 = parameter(kind="triangular", value=None, low=-0.1, mode=0.0, high=0.1)
    original = scenario_set(
        parameters={"p1": parameter(), "p2": p2},
        idiosyncratic=(shock(),),
    )
    restored = ScenarioSet.from_spec(original.spec())
    assert restored.spec() == original.spec()
    assert restored.points == original.points
    assert restored.replicates == original.replicates
    assert restored.idiosyncratic == original.idiosyncratic


def test_spec_sorts_parameters_by_name():
    s = scenario_set(parameters={"z": parameter(), "a": parameter()})
    assert list(s.spec()["parameters"]) == ["a", "z"]


def test_spec_correlation_round_trips():
    correlation = np.eye(2)
    s = scenario_set(
        parameters={"p1": parameter(), "p2": parameter()},
        correlation=correlation,
    )
    restored = ScenarioSet.from_spec(s.spec())
    assert np.array_equal(restored.correlation, correlation)


def test_spec_correlation_none_round_trips_as_none():
    s = scenario_set()
    restored = ScenarioSet.from_spec(s.spec())
    assert restored.correlation is None


# -- with_idiosyncratic dedup/sort --------------------------------------------------------


def test_with_idiosyncratic_deduplicates_by_name_keeping_the_last():
    base = scenario_set()
    updated = base.with_idiosyncratic([shock("a", sigma=0.01), shock("a", sigma=0.02)])
    assert len(updated.idiosyncratic) == 1
    assert updated.idiosyncratic[0].sigma == 0.02


def test_with_idiosyncratic_sorts_by_name():
    base = scenario_set()
    updated = base.with_idiosyncratic([shock("zzz"), shock("aaa")])
    assert [item.name for item in updated.idiosyncratic] == ["aaa", "zzz"]


def test_with_idiosyncratic_preserves_other_fields():
    base = scenario_set(points=128, replicates=16)
    updated = base.with_idiosyncratic([shock()])
    assert updated.points == 128
    assert updated.replicates == 16
    assert updated.parameters == base.parameters


# -- scenario_set_from_parameters ---------------------------------------------------------


def test_scenario_set_from_parameters_accepts_dicts_and_models():
    built = scenario_set_from_parameters(
        {"p1": {"kind": "point", "value": 0.1, "unit": "fraction"}, "p2": parameter()},
        points=POINTS,
        replicates=REPLICATES,
    )
    assert set(built.parameters) == {"p1", "p2"}


# -- idiosyncratic_draws -------------------------------------------------------------------


def test_idiosyncratic_draws_shape():
    draws = idiosyncratic_draws(shock(), seed=1, points=POINTS, replicates=REPLICATES)
    assert draws.shape == (REPLICATES, POINTS)


def test_idiosyncratic_draws_deterministic_for_same_seed_subject_name():
    a = idiosyncratic_draws(shock(), seed=1, points=POINTS, replicates=REPLICATES)
    b = idiosyncratic_draws(shock(), seed=1, points=POINTS, replicates=REPLICATES)
    assert np.array_equal(a, b)


def test_idiosyncratic_draws_differ_with_different_seed():
    a = idiosyncratic_draws(shock(), seed=1, points=POINTS, replicates=REPLICATES)
    b = idiosyncratic_draws(shock(), seed=2, points=POINTS, replicates=REPLICATES)
    assert not np.array_equal(a, b)


def test_idiosyncratic_draws_differ_with_different_subject():
    a = idiosyncratic_draws(shock(subject="I1"), seed=1, points=POINTS, replicates=REPLICATES)
    b = idiosyncratic_draws(shock(subject="I2"), seed=1, points=POINTS, replicates=REPLICATES)
    assert not np.array_equal(a, b)


def test_idiosyncratic_draws_differ_with_different_name():
    a = idiosyncratic_draws(shock(name="a"), seed=1, points=POINTS, replicates=REPLICATES)
    b = idiosyncratic_draws(shock(name="b"), seed=1, points=POINTS, replicates=REPLICATES)
    assert not np.array_equal(a, b)


# -- Realisations ---------------------------------------------------------------------------


def realisations(parameters=None, seed=1, idiosyncratic=(), graph=None, factor_versions=None):
    s = scenario_set(parameters=parameters).with_idiosyncratic(idiosyncratic)
    return Realisations(
        scenario_set=s,
        seed=seed,
        as_of=date(2026, 1, 1),
        horizon=12,
        graph=graph,
        factor_versions=factor_versions or {},
    )


def test_realisations_draws_shape():
    r = realisations()
    assert r.draws("p1").shape == (REPLICATES, POINTS)


def test_realisations_central_reads_management_central_value():
    r = realisations(parameters={"p1": parameter(value=0.25)})
    assert r.central("p1") == 0.25


def test_realisations_parameters_for_filters_by_factor_and_key():
    params = {
        "a": parameter(factor="market.fx", key="USD/RUB"),
        "b": parameter(factor="market.fx", key="EUR/RUB"),
        "c": parameter(factor="credit.revenue"),
    }
    r = realisations(parameters=params)
    assert r.parameters_for("market.fx") == ["a", "b"]
    assert r.parameters_for("market.fx", "USD/RUB") == ["a"]
    assert r.parameters_for("credit.revenue") == ["c"]
    assert r.parameters_for("no.such.factor") == []


def test_realisations_idiosyncratic_returns_shock_draws():
    r = realisations(idiosyncratic=(shock("minimal.noise:I1", subject="I1"),))
    draws = r.idiosyncratic("minimal.noise:I1")
    assert draws.shape == (REPLICATES, POINTS)


def test_realisations_idiosyncratic_unknown_name_raises():
    r = realisations()
    with pytest.raises(KeyError, match="no idiosyncratic shock"):
        r.idiosyncratic("no.such.shock")


def test_realisations_idiosyncratic_is_cached():
    r = realisations(idiosyncratic=(shock("minimal.noise:I1", subject="I1"),))
    first = r.idiosyncratic("minimal.noise:I1")
    second = r.idiosyncratic("minimal.noise:I1")
    assert first is second


# -- scenario_id stability and sensitivity --------------------------------------------------


def test_scenario_id_stable_for_identical_inputs():
    a = realisations().scenario_id
    b = realisations().scenario_id
    assert a == b


def test_scenario_id_changes_with_seed():
    a = realisations(seed=1).scenario_id
    b = realisations(seed=2).scenario_id
    assert a != b


def test_scenario_id_changes_with_a_parameter_value():
    a = realisations(parameters={"p1": parameter(value=0.1)}).scenario_id
    b = realisations(parameters={"p1": parameter(value=0.2)}).scenario_id
    assert a != b


def test_scenario_id_changes_with_an_idiosyncratic_shock():
    a = realisations().scenario_id
    b = realisations(idiosyncratic=(shock(),)).scenario_id
    assert a != b


def test_scenario_id_changes_with_the_graph():
    from msa.contracts.evidence import Evidence
    from msa.contracts.graph import Edge, Node, PointDistribution, TransmissionGraph

    g = TransmissionGraph(
        event_id="event",
        nodes=[
            Node(id="event", kind="event", label="e"),
            Node(id="f", kind="factor", label="f", factor="market.fx"),
        ],
        edges=[
            Edge(
                src="event",
                dst="f",
                sign=1,
                elasticity=PointDistribution(value=1.0),
                lag_months=0,
                evidence=[
                    Evidence(
                        kind="document",
                        source_id="S",
                        locator="l",
                        fragment_sha256="a" * 64,
                    )
                ],
            )
        ],
    )
    a = realisations().scenario_id
    b = realisations(graph=g).scenario_id
    assert a != b


def test_scenario_id_changes_with_factor_versions():
    r1 = realisations()
    r1.factor_versions = {"market.fx": "1.0.0"}
    r2 = realisations()
    r2.factor_versions = {"market.fx": "2.0.0"}
    assert r1.scenario_id != r2.scenario_id


def triangular(low=-0.1, mode=0.0, high=0.1):
    return MacroParameter(kind="triangular", low=low, mode=mode, high=high, unit="fraction")


def test_adding_a_direct_factor_parameter_may_change_other_draws():
    """The code draws all parameters jointly from one sorted-name Sobol net (spec 13.2), so
    adding a parameter changes the dimensionality and, in general, every column's values.
    This does not assert an invariant the code promises -- only what it actually does.
    (A point-mass parameter's ppf ignores its uniform draw, so it must use a real
    distribution to show the effect.)"""
    base = realisations(parameters={"p1": triangular()})
    extended = realisations(parameters={"p1": triangular(), "p2": triangular(-0.2, 0.0, 0.2)})
    assert not np.array_equal(base.draws("p1"), extended.draws("p1"))


def test_scenario_id_function_matches_realisations_property():
    r = realisations()
    direct = scenario_id(
        r.scenario_set,
        r.seed,
        r.as_of,
        r.horizon,
        r.graph,
        r.factor_versions,
        r.macro_draws_sha256,
    )
    assert direct == r.scenario_id
