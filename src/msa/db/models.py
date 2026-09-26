"""Application tables; the demo namespace uses the same definitions as demo.demo_*.

Identifiers and relations are relational columns: parties, instruments, positions,
portfolios, snapshots and their items, runs and their results. A plugin's own parameters —
instrument terms, position parameters, snapshot values — are JSON validated against the
plugin's versioned schema on the way in, so a new asset family needs no migration.
"""

from functools import lru_cache

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)

from .base import Base, utcnow


def define_tables(metadata: MetaData, *, prefix: str = "", schema: str | None = None):
    result = {}

    def ref(name, column):
        return f"{schema + '.' if schema else ''}{prefix}{name}.{column}"

    def table(name, *columns):
        result[name] = Table(prefix + name, metadata, *columns, schema=schema)
        return result[name]

    table(
        "party",
        Column("party_id", String, primary_key=True),
        Column("name", Text, nullable=False),
        Column("kind", String, nullable=False),
        Column("okved", String, index=True),
        Column("country", String),
        Column("description", Text, nullable=False, default=""),
        Column("evidence", JSON, nullable=False),
    )
    table(
        "portfolio",
        Column("portfolio_id", String, primary_key=True),
        Column("name", Text, nullable=False),
        Column("base_currency", String(3), nullable=False),
        Column("as_of", Date),
        Column("snapshot_id", String),
        Column("builtin", Boolean, nullable=False, default=False),
        Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
        Column("expires_at", DateTime(timezone=True)),
        Column("metadata", JSON, nullable=False, default=dict),
    )
    table(
        "instrument",
        Column("instrument_id", String, primary_key=True),
        Column("instrument_type", String, nullable=False, index=True),
        Column("name", Text, nullable=False),
        Column("currency", String(3), nullable=False),
        Column("issuer_id", String, ForeignKey(ref("party", "party_id"))),
        Column("terms", JSON, nullable=False),
        Column("schema_version", String, nullable=False),
        # Instruments typed into an analyst's portfolio go with it.
        Column("owner_portfolio_id", String),
    )
    table(
        "position",
        Column(
            "portfolio_id", String, ForeignKey(ref("portfolio", "portfolio_id")), primary_key=True
        ),
        Column("position_id", String, primary_key=True),
        Column(
            "instrument_id", String, ForeignKey(ref("instrument", "instrument_id")), nullable=False
        ),
        Column("model_id", String),
        Column("params", JSON, nullable=False),
        Column("schema_version", String, nullable=False),
    )
    table(
        "data_snapshot",
        Column("snapshot_id", String, primary_key=True),
        Column("as_of", Date, nullable=False),
        Column("label", Text, nullable=False),
        Column("kind", String, nullable=False),
        Column("sha256", String(64), nullable=False),
        Column("created_by", String, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
        Column("expires_at", DateTime(timezone=True)),
        Column("metadata", JSON, nullable=False, default=dict),
    )
    items = table(
        "snapshot_item",
        Column(
            "snapshot_id",
            String,
            ForeignKey(ref("data_snapshot", "snapshot_id")),
            primary_key=True,
        ),
        Column("item_id", String, primary_key=True),
        Column("kind", String, nullable=False),
        Column("subject", String, nullable=False),
        Column("observed_on", Date, nullable=False),
        Column("values", JSON, nullable=False),
        Column("attributes", JSON, nullable=False),
        Column("evidence", JSON, nullable=False),
    )
    Index(f"ix_{prefix}snapshot_item_lookup", items.c.snapshot_id, items.c.kind, items.c.subject)
    table(
        "run",
        Column("run_id", String, primary_key=True),
        Column("event_text", Text, nullable=False),
        Column("event_sha256", String(64), nullable=False),
        Column("seed", Integer, nullable=False),
        Column("mc_points", Integer, nullable=False),
        Column("status", String, nullable=False),
        # What the run is fixed to: the process, the code, the data and the positions.
        Column("workflow_id", String, nullable=False),
        Column("workflow_version", String, nullable=False),
        Column("portfolio_id", String, nullable=False),
        Column("snapshot_id", String, nullable=False),
        Column("position_ids", JSON, nullable=False),
        Column("plugins", JSON, nullable=False),
        Column("models", JSON, nullable=False),
        Column("scenario", JSON),
        Column("scenario_id", String(64)),
        Column("versions", JSON, nullable=False),
        Column("macro_draws_sha256", String(64)),
        Column("graph", JSON),
        Column("report", JSON),
        Column("approved_by", String),
        Column("approved_at", DateTime(timezone=True)),
        Column("approved_report_sha256", String(64)),
        Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
        Column("updated_at", DateTime(timezone=True), nullable=False, default=utcnow),
        CheckConstraint("seed >= 0 AND seed <= 4294967295", name="seed"),
        CheckConstraint("mc_points IN (8192, 16384, 32768)", name="mc_points"),
    )
    table(
        "run_result",
        Column("run_id", String, ForeignKey(ref("run", "run_id")), primary_key=True),
        Column("kind", String, primary_key=True),
        Column("artifact_id", String, primary_key=True),
        Column("payload", JSON, nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False, default=utcnow),
    )
    table(
        "run_node_result",
        Column("run_id", Text, primary_key=True),
        Column("node", Text, primary_key=True),
        Column("attempt", Integer, primary_key=True),
        Column("payload", Text, nullable=False),
        # A rerun of a node is identified by its code version and its inputs.
        Column("agent_version", String),
        Column("inputs_sha256", String(64)),
        CheckConstraint("attempt >= 1", name="attempt"),
    )
    table(
        "run_explanation",
        Column("explanation_id", String, primary_key=True),
        Column("run_id", String, ForeignKey(ref("run", "run_id")), nullable=False, index=True),
        Column("question", Text, nullable=False),
        Column("status", String, nullable=False),
        Column("answer", JSON),
        Column("error", Text),
        Column("created_by", String, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
        Column("updated_at", DateTime(timezone=True), nullable=False, default=utcnow),
    )
    table(
        "audit_log",
        Column("audit_id", String, primary_key=True),
        Column("occurred_at", DateTime(timezone=True), nullable=False, default=utcnow),
        Column("actor", String, nullable=False),
        Column("action", String, nullable=False),
        Column("run_id", String, index=True),
        Column("node", String),
        Column("attempt", Integer),
        Column("tool", String),
        Column("standalone", Boolean, nullable=False),
        Column("details", JSON, nullable=False),
        CheckConstraint("attempt IS NULL OR attempt >= 1", name="attempt"),
    )
    table(
        "rule_threshold",
        Column("rule_id", String, primary_key=True),
        Column("revision", Integer, primary_key=True),
        Column("metric", String, nullable=False),
        Column("operator", String, nullable=False),
        Column("threshold", Float, nullable=False),
        Column("unit", String, nullable=False),
        Column("actions", JSON, nullable=False),
        Column("fallback_only", Boolean, nullable=False),
        Column("effective_at", DateTime(timezone=True), nullable=False),
        Column("changed_by", String, nullable=False),
        Column("reason", Text, nullable=False),
        UniqueConstraint("rule_id", "effective_at"),
        CheckConstraint("revision >= 1", name="revision"),
    )
    table(
        "event",
        Column("event_id", String, primary_key=True),
        Column("title", Text, nullable=False),
        Column("text", Text, nullable=False),
        Column("sha256", String(64), nullable=False),
        Column("metadata", JSON, nullable=False),
    )
    # Durable HTTP state: queued/running jobs, quotas and parsed event documents.
    table(
        "api_job",
        Column("job_id", String, primary_key=True),
        Column("kind", String, nullable=False),
        Column("principal", String, nullable=False),
        Column("payload", JSON, nullable=False),
        Column("status", String, nullable=False),
        Column("state", JSON, nullable=False),
        Column("error", Text),
    )
    table(
        "api_quota",
        Column("principal", String, primary_key=True),
        Column("history", JSON, nullable=False),
        Column("active", JSON, nullable=False),
    )
    table(
        "api_document",
        Column("doc_id", String, primary_key=True),
        Column("payload", JSON, nullable=False),
    )
    return result


TABLES = define_tables(Base.metadata)


@lru_cache
def demo_tables(dialect: str):
    return define_tables(
        MetaData(naming_convention=Base.metadata.naming_convention),
        prefix="demo_",
        schema="demo" if dialect == "postgresql" else None,
    )


def tables_for(session):
    if session.info.get("data_scope") == "demo":
        return demo_tables(session.get_bind().dialect.name)
    return TABLES
