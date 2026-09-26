"""msa.engine.exposure: which positions an approved scenario reaches."""

from msa.contracts.domain import Instrument, Party, Position, PositionContext
from msa.contracts.evidence import Evidence
from msa.contracts.graph import Edge, Node, PointDistribution, TransmissionGraph
from msa.contracts.scenario import MacroParameter
from msa.engine.exposure import reached_sectors, reasons
from msa.platform.registry import Registry
from msa.plugin_sdk.model import DataRequirements, FactorRequirement
from msa.plugin_sdk.specs import FactorSpec
from msa.plugin_sdk.testing import graph_reaching


def evidence():
    return [Evidence(kind="document", source_id="S", locator="l", fragment_sha256="a" * 64)]


def edge(src, dst, lag=0):
    return Edge(
        src=src,
        dst=dst,
        sign=1,
        elasticity=PointDistribution(value=1.0),
        lag_months=lag,
        evidence=evidence(),
    )


def registry_with_factor(factor_id, scope):
    spec = FactorSpec(
        factor_id=factor_id,
        label="F",
        unit="fraction",
        scope=scope,
        application="relative",
        quantity="relative_change",
    )
    return Registry(factors={factor_id: spec})


def fx_param(key="USD/RUB", factor_id="market.fx"):
    return MacroParameter(kind="point", value=0.1, unit="fraction", factor=factor_id, key=key)


def context(okved="23.61", issuer_id="ISSUER"):
    instrument = Instrument(
        instrument_id="I1", instrument_type="minimal_cash", name="I1", issuer_id=issuer_id
    )
    issuer = Party(party_id=issuer_id, name="Issuer", okved=okved) if issuer_id else None
    return PositionContext(
        portfolio_id="PF1",
        position=Position(position_id="POS1", instrument_id="I1"),
        instrument=instrument,
        issuer=issuer,
    )


# -- reached_sectors ------------------------------------------------------------------


def test_reached_sectors_finds_sectors_on_the_path_to_a_factor():
    g = graph_reaching("23.61", "credit.revenue")
    assert reached_sectors(g) == ["23.61"]


def test_reached_sectors_excludes_sectors_not_on_a_path_to_any_factor():
    g = TransmissionGraph(
        event_id="event",
        nodes=[
            Node(id="event", kind="event", label="e"),
            Node(id="sector", kind="sector", label="s", okved="99.99"),
            Node(id="factor", kind="factor", label="f", factor="credit.revenue"),
        ],
        edges=[edge("event", "factor")],  # sector node is disconnected from the path
    )
    assert reached_sectors(g) == []


# -- reasons(): graph-scope factors ----------------------------------------------------


def test_reasons_empty_when_no_graph_factors_in_requirements():
    reg = Registry()
    ctx = context()
    result = reasons(ctx, DataRequirements(), None, {}, reg)
    assert result == []


def test_reasons_graph_sector_when_okved_matches_reached_sector():
    reg = registry_with_factor("credit.revenue", scope="graph")
    ctx = context(okved="23.61")
    g = graph_reaching("23.61", "credit.revenue")
    requirements = DataRequirements(factors=[FactorRequirement(factor_id="credit.revenue")])
    result = reasons(ctx, requirements, g, {}, reg)
    assert result == ["graph_sector:23.61"]


def test_reasons_no_graph_sector_when_okved_does_not_match():
    reg = registry_with_factor("credit.revenue", scope="graph")
    ctx = context(okved="99.99")
    g = graph_reaching("23.61", "credit.revenue")
    requirements = DataRequirements(factors=[FactorRequirement(factor_id="credit.revenue")])
    result = reasons(ctx, requirements, g, {}, reg)
    assert result == []


def test_reasons_no_graph_sector_without_a_graph():
    reg = registry_with_factor("credit.revenue", scope="graph")
    ctx = context(okved="23.61")
    requirements = DataRequirements(factors=[FactorRequirement(factor_id="credit.revenue")])
    result = reasons(ctx, requirements, None, {}, reg)
    assert result == []


def test_reasons_no_graph_sector_without_an_okved():
    reg = registry_with_factor("credit.revenue", scope="graph")
    ctx = context(okved=None, issuer_id=None)
    g = graph_reaching("23.61", "credit.revenue")
    requirements = DataRequirements(factors=[FactorRequirement(factor_id="credit.revenue")])
    result = reasons(ctx, requirements, g, {}, reg)
    assert result == []


def test_reasons_ignores_requirement_for_undeclared_factor():
    reg = Registry()  # the factor is not registered
    ctx = context()
    g = graph_reaching("23.61", "credit.revenue")
    requirements = DataRequirements(factors=[FactorRequirement(factor_id="credit.revenue")])
    result = reasons(ctx, requirements, g, {}, reg)
    assert result == []


# -- reasons(): direct factors ----------------------------------------------------------


def test_reasons_direct_factor_matches_by_id_and_key():
    reg = registry_with_factor("market.fx", scope="currency_pair")
    ctx = context()
    requirements = DataRequirements(
        factors=[FactorRequirement(factor_id="market.fx", key="USD/RUB")]
    )
    result = reasons(ctx, requirements, None, {"p1": fx_param()}, reg)
    assert result == ["factor:p1"]


def test_reasons_direct_factor_key_none_matches_any_key():
    reg = registry_with_factor("market.fx", scope="currency_pair")
    ctx = context()
    requirements = DataRequirements(factors=[FactorRequirement(factor_id="market.fx", key=None)])
    result = reasons(ctx, requirements, None, {"p1": fx_param()}, reg)
    assert result == ["factor:p1"]


def test_reasons_direct_factor_does_not_match_a_different_key():
    reg = registry_with_factor("market.fx", scope="currency_pair")
    ctx = context()
    requirements = DataRequirements(
        factors=[FactorRequirement(factor_id="market.fx", key="EUR/RUB")]
    )
    result = reasons(ctx, requirements, None, {"p1": fx_param()}, reg)
    assert result == []


def test_reasons_direct_factor_results_sorted_by_parameter_name():
    reg = registry_with_factor("market.fx", scope="currency_pair")
    ctx = context()
    requirements = DataRequirements(factors=[FactorRequirement(factor_id="market.fx")])
    parameters = {"z": fx_param(), "a": fx_param(key="EUR/RUB")}
    result = reasons(ctx, requirements, None, parameters, reg)
    assert result == ["factor:a", "factor:z"]


def test_reasons_combines_graph_and_direct_factors():
    reg = Registry(
        factors={
            "credit.revenue": FactorSpec(
                factor_id="credit.revenue",
                label="F",
                unit="fraction",
                scope="graph",
                application="relative",
                quantity="relative_change",
            ),
            "market.fx": FactorSpec(
                factor_id="market.fx",
                label="FX",
                unit="log_return",
                scope="currency_pair",
                application="log",
                quantity="log_return",
            ),
        }
    )
    ctx = context(okved="23.61")
    g = graph_reaching("23.61", "credit.revenue")
    requirements = DataRequirements(
        factors=[
            FactorRequirement(factor_id="credit.revenue"),
            FactorRequirement(factor_id="market.fx", key="USD/RUB"),
        ]
    )
    result = reasons(ctx, requirements, g, {"fx1": fx_param()}, reg)
    assert result == ["graph_sector:23.61", "factor:fx1"]
