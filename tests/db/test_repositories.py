"""msa.db.repositories: PortfoliosRepository, SnapshotsRepository, DemoRepository, runs journal.

Uses a fresh in-memory SQLite database, migrated once per test module.
"""

from datetime import date, timedelta

import pytest

from msa.contracts.domain import Instrument, Party, Portfolio, PortfolioBundle, Position
from msa.contracts.evidence import Evidence, Parameter
from msa.contracts.snapshot import DataSnapshot, SnapshotItem
from msa.db.base import utcnow
from msa.db.migrate import migrate
from msa.db.repositories.demo import DemoRepository
from msa.db.repositories.portfolios import PortfolioProblem, PortfoliosRepository
from msa.db.repositories.runs import ApplicationRunRepository
from msa.db.repositories.snapshots import SnapshotConflict, SnapshotsRepository
from msa.db.session import engine, session_scope
from msa.platform.registry import build

from ..platform import minimal_plugin as mp


@pytest.fixture(scope="module")
def bind():
    bound = engine("sqlite:///:memory:")
    migrate(bound)
    yield bound
    bound.dispose()


@pytest.fixture
def registry():
    return build([mp.plugin, mp.MARKET_PLUGIN])


def evidence():
    return [Evidence(kind="document", source_id="S", locator="l", fragment_sha256="a" * 64)]


def amount_param(value=10.0, currency="RUB"):
    return Parameter(value=value, unit=f"{currency}_million", evidence=evidence()).model_dump(
        mode="json"
    )


def bundle(portfolio_id="PF1", position_id="POS1", **overrides):
    # Each test uses its own portfolio_id, so the party/instrument/position ids are made
    # unique per portfolio to avoid accidental cross-portfolio sharing of the same instrument.
    party_id, instrument_id = f"P-{portfolio_id}", f"I-{portfolio_id}"
    party = Party(party_id=party_id, name="Issuer", okved="23.61")
    instrument = Instrument(
        instrument_id=instrument_id,
        instrument_type=mp.TYPE_ID,
        name="I1",
        issuer_id=party_id,
        currency="RUB",
    )
    position = Position(
        position_id=position_id,
        instrument_id=instrument_id,
        params={"amount": amount_param()},
    )
    values = {
        "portfolio": Portfolio(portfolio_id=portfolio_id, name="Portfolio"),
        "parties": [party],
        "instruments": [instrument],
        "positions": [position],
    }
    values.update(overrides)
    return PortfolioBundle(**values)


# -- PortfoliosRepository -----------------------------------------------------------------


def test_save_and_get_bundle_round_trips(bind, registry):
    with session_scope(bind, scope="production") as session:
        repo = PortfoliosRepository(session)
        repo.save_bundle(bundle("PF-ROUND"), registry=registry)
    with session_scope(bind, scope="production") as session:
        repo = PortfoliosRepository(session)
        got = repo.get_bundle("PF-ROUND")
    assert got.portfolio.portfolio_id == "PF-ROUND"
    assert [p.position_id for p in got.positions] == ["POS1"]
    assert got.instrument("I-PF-ROUND").issuer_id == "P-PF-ROUND"


def test_save_bundle_rejects_a_position_that_fails_the_plugin_schema(bind, registry):
    broken = bundle(
        "PF-BROKEN",
        positions=[Position(position_id="POS1", instrument_id="I-PF-BROKEN", params={})],
    )
    with session_scope(bind, scope="production") as session:
        repo = PortfoliosRepository(session)
        with pytest.raises(PortfolioProblem):
            repo.save_bundle(broken, registry=registry)


def test_exists_true_after_save_false_for_unknown_id(bind, registry):
    with session_scope(bind, scope="production") as session:
        repo = PortfoliosRepository(session)
        repo.save_bundle(bundle("PF-EXISTS"), registry=registry)
        assert repo.exists("PF-EXISTS") is True
        assert repo.exists("PF-NOPE") is False


def test_get_bundle_of_unknown_portfolio_raises_keyerror(bind):
    with session_scope(bind, scope="production") as session:
        repo = PortfoliosRepository(session)
        with pytest.raises(KeyError):
            repo.get_bundle("PF-NEVER-SAVED")


def test_list_portfolios_reports_position_count(bind, registry):
    with session_scope(bind, scope="production") as session:
        repo = PortfoliosRepository(session)
        repo.save_bundle(bundle("PF-LIST"), registry=registry)
        rows = {row["portfolio_id"]: row for row in repo.list_portfolios()}
    assert rows["PF-LIST"]["positions"] == 1


def test_list_portfolios_excludes_expired(bind, registry):
    with session_scope(bind, scope="production") as session:
        repo = PortfoliosRepository(session)
        repo.save_bundle(
            bundle("PF-EXPIRED"), registry=registry, expires_at=utcnow() - timedelta(days=1)
        )
        ids = {row["portfolio_id"] for row in repo.list_portfolios()}
    assert "PF-EXPIRED" not in ids


def test_delete_portfolio_removes_positions_and_owned_instruments(bind, registry):
    with session_scope(bind, scope="production") as session:
        repo = PortfoliosRepository(session)
        repo.save_bundle(bundle("PF-DEL"), registry=registry, owned=True)
        repo.delete_portfolio("PF-DEL")
        assert repo.exists("PF-DEL") is False
        with pytest.raises(KeyError):
            repo.get_bundle("PF-DEL")


def test_delete_builtin_portfolio_is_forbidden(bind, registry):
    demo_bind = bind
    with session_scope(demo_bind, scope="demo") as session:
        demo = DemoRepository(session)
        b = bundle("PF-BUILTIN")
        demo.seed_portfolio(b, registry=registry)
    with session_scope(demo_bind, scope="demo") as session:
        repo = PortfoliosRepository(session)
        with pytest.raises(PermissionError):
            repo.delete_portfolio("PF-BUILTIN")


def test_names_uses_issuer_name_when_present(bind, registry):
    with session_scope(bind, scope="production") as session:
        repo = PortfoliosRepository(session)
        repo.save_bundle(bundle("PF-NAMES"), registry=registry)
        names = repo.names("PF-NAMES")
    assert names["POS1"] == "Issuer"


def test_sectors_maps_party_to_okved(bind, registry):
    with session_scope(bind, scope="production") as session:
        repo = PortfoliosRepository(session)
        repo.save_bundle(bundle("PF-SECTORS"), registry=registry)
        sectors = repo.sectors()
    assert sectors["P-PF-SECTORS"] == "23.61"


# -- SnapshotsRepository --------------------------------------------------------------------


def snapshot(snapshot_id="SNAP-1", as_of=date(2026, 1, 1)):
    item = SnapshotItem(
        item_id="i1",
        kind="rate",
        subject="S",
        observed_on=as_of,
        values={"rate": Parameter(value=1.0, unit="ratio", evidence=evidence())},
    )
    return DataSnapshot(snapshot_id=snapshot_id, as_of=as_of, label="L", items=[item])


def test_snapshot_save_and_get_round_trips(bind):
    with session_scope(bind, scope="production") as session:
        repo = SnapshotsRepository(session)
        repo.save(snapshot("SNAP-A"), created_by="tester")
    with session_scope(bind, scope="production") as session:
        repo = SnapshotsRepository(session)
        got = repo.get("SNAP-A")
    assert got.items[0].item_id == "i1"
    assert got.as_of == date(2026, 1, 1)


def test_snapshot_save_same_content_twice_is_a_no_op(bind):
    with session_scope(bind, scope="production") as session:
        repo = SnapshotsRepository(session)
        first = repo.save(snapshot("SNAP-B"), created_by="tester")
        second = repo.save(snapshot("SNAP-B"), created_by="someone-else")
    assert first["sha256"] == second["sha256"]
    assert second["created_by"] == "tester"  # the original row was not overwritten


def test_snapshot_save_different_content_under_same_id_raises(bind):
    with session_scope(bind, scope="production") as session:
        repo = SnapshotsRepository(session)
        repo.save(snapshot("SNAP-C", as_of=date(2026, 1, 1)), created_by="tester")
        with pytest.raises(SnapshotConflict):
            repo.save(snapshot("SNAP-C", as_of=date(2026, 2, 1)), created_by="tester")


def test_snapshot_exists_and_delete(bind):
    with session_scope(bind, scope="production") as session:
        repo = SnapshotsRepository(session)
        repo.save(snapshot("SNAP-D"), created_by="tester")
        assert repo.exists("SNAP-D") is True
        repo.delete("SNAP-D")
        assert repo.exists("SNAP-D") is False


def test_snapshot_header_of_unknown_id_raises_keyerror(bind):
    with session_scope(bind, scope="production") as session:
        repo = SnapshotsRepository(session)
        with pytest.raises(KeyError):
            repo.header("SNAP-NEVER")


def test_snapshot_items_filters_by_kind(bind):
    with session_scope(bind, scope="production") as session:
        repo = SnapshotsRepository(session)
        repo.save(snapshot("SNAP-E"), created_by="tester")
        assert [i.item_id for i in repo.items("SNAP-E", kind="rate")] == ["i1"]
        assert repo.items("SNAP-E", kind="fx_rate") == []


# -- DemoRepository: scope enforcement --------------------------------------------------------


def test_demo_repository_requires_a_demo_scoped_session(bind):
    with session_scope(bind, scope="production") as session:
        with pytest.raises(PermissionError):
            DemoRepository(session)


# -- ApplicationRunRepository: node journal upsert identity -----------------------------------


def test_upsert_node_result_is_idempotent_for_identical_payload(bind):
    with session_scope(bind, scope="production") as session:
        repo = ApplicationRunRepository(session)
        repo.create_run(
            "RUN-J1",
            "event text",
            seed=1,
            mc_points=8192,
            workflow_id="stress_test",
            workflow_version="1.0.0",
            portfolio_id="PF-J1",
            snapshot_id="SNAP-J1",
        )
        repo.upsert_node_result("RUN-J1", "node_a", 1, {"value": 1}, agent_version="1.0.0")
        repo.upsert_node_result("RUN-J1", "node_a", 1, {"value": 1}, agent_version="1.0.0")
        rows = repo.list_node_results("RUN-J1")
    assert len(rows) == 1
    assert rows[0]["payload"] == {"value": 1}


def test_upsert_node_result_different_attempt_is_a_new_row(bind):
    with session_scope(bind, scope="production") as session:
        repo = ApplicationRunRepository(session)
        repo.create_run(
            "RUN-J2",
            "event text",
            seed=1,
            mc_points=8192,
            workflow_id="stress_test",
            workflow_version="1.0.0",
            portfolio_id="PF-J2",
            snapshot_id="SNAP-J2",
        )
        repo.upsert_node_result("RUN-J2", "node_a", 1, {"value": 1})
        repo.upsert_node_result("RUN-J2", "node_a", 2, {"value": 2})
        rows = {row["attempt"]: row["payload"] for row in repo.list_node_results("RUN-J2")}
    assert rows == {1: {"value": 1}, 2: {"value": 2}}


def test_node_identity_records_agent_version_and_inputs_hash(bind):
    with session_scope(bind, scope="production") as session:
        repo = ApplicationRunRepository(session)
        repo.create_run(
            "RUN-J3",
            "event text",
            seed=1,
            mc_points=8192,
            workflow_id="stress_test",
            workflow_version="1.0.0",
            portfolio_id="PF-J3",
            snapshot_id="SNAP-J3",
        )
        repo.upsert_node_result(
            "RUN-J3",
            "node_a",
            1,
            {"value": 1},
            agent_version="2.0.0",
            inputs_sha256="h1",
        )
        identity = repo.node_identity("RUN-J3", "node_a", 1)
    assert identity == ("2.0.0", "h1")


def test_node_identity_of_unknown_node_is_none(bind):
    with session_scope(bind, scope="production") as session:
        repo = ApplicationRunRepository(session)
        repo.create_run(
            "RUN-J4",
            "event text",
            seed=1,
            mc_points=8192,
            workflow_id="stress_test",
            workflow_version="1.0.0",
            portfolio_id="PF-J4",
            snapshot_id="SNAP-J4",
        )
        assert repo.node_identity("RUN-J4", "nope", 1) is None
        assert repo.get_node_result("RUN-J4", "nope", 1) is None
