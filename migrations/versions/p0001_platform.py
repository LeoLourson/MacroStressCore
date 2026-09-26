"""Platform baseline: parties, instruments, positions, data snapshots, platform runs.

The schema of the plugin platform is a clean start. It is deployed into its own database:
a database migrated by the previous baseline (revision ``0001``) is not touched and reports
an unknown revision instead of being rewritten. Demo data are re-created by the seed.

Later revisions change the schema with explicit Alembic operations; this one creates it from
the application's table definitions as they stood at the baseline.
"""

from pathlib import Path

from alembic import op
from sqlalchemy import MetaData

from msa.db.models import define_tables

revision = "p0001"
down_revision = None
branch_labels = depends_on = None

SEED = Path(__file__).parents[1] / "seeds" / "rule_thresholds.sql"


def _definitions(demo: bool, postgres: bool):
    return define_tables(
        MetaData(),
        prefix="demo_" if demo else "",
        schema="demo" if demo and postgres else None,
    )


def _role(name: str) -> str:
    return f"""DO $$ BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='{name}') THEN
            CREATE ROLE {name} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
        END IF;
        IF EXISTS (SELECT FROM pg_roles WHERE rolname='{name}' AND
                   (rolsuper OR rolcreatedb OR rolcreaterole OR rolbypassrls)) OR
           EXISTS (SELECT FROM pg_auth_members m JOIN pg_roles r ON m.member=r.oid
                   WHERE r.rolname='{name}') THEN
            RAISE EXCEPTION '{name} must be an unprivileged role without memberships';
        END IF;
    END $$"""


def upgrade():
    bind = op.get_bind()
    postgres = bind.dialect.name == "postgresql"
    if postgres:
        op.execute("CREATE SCHEMA IF NOT EXISTS demo")
    working = _definitions(False, postgres)
    demo = _definitions(True, postgres)
    for tables in (working, demo):
        next(iter(tables.values())).metadata.create_all(bind)

    seed = SEED.read_text(encoding="utf-8")
    op.execute(seed)
    target = "demo.demo_rule_threshold" if postgres else "demo_rule_threshold"
    op.execute(seed.replace("INSERT INTO rule_threshold", f"INSERT INTO {target}"))

    if not postgres:
        # SQLite serves local tests only; it still refuses to rewrite the audit trail.
        for table in ("audit_log", "demo_audit_log"):
            for action in ("UPDATE", "DELETE"):
                op.execute(
                    f"CREATE TRIGGER {table}_immutable_{action} BEFORE {action} ON {table} "
                    "BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END"
                )
        return

    op.execute("""CREATE FUNCTION msa_audit_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'audit_log is append-only'; END; $$""")
    for table in ("audit_log", "demo.demo_audit_log"):
        op.execute(
            f"CREATE TRIGGER audit_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION msa_audit_immutable()"
        )

    # Demo sessions run as msa_demo: the demo schema only, no working table.
    for name in ("msa_demo", "msa_readonly", "msa_demo_readonly"):
        op.execute(_role(name))
    op.execute("REVOKE ALL ON SCHEMA demo FROM PUBLIC")
    op.execute("GRANT USAGE ON SCHEMA demo TO msa_demo")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA demo TO msa_demo")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA demo TO msa_demo")
    op.execute("REVOKE UPDATE, DELETE ON demo.demo_audit_log FROM msa_demo")
    for name in working:
        op.execute(f'REVOKE ALL ON TABLE public."{name}" FROM msa_demo, PUBLIC')
    # The MCP servers read through these roles inside read-only transactions.
    op.execute("GRANT USAGE ON SCHEMA public TO msa_readonly")
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO msa_readonly")
    op.execute("GRANT USAGE ON SCHEMA demo TO msa_demo_readonly")
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA demo TO msa_demo_readonly")


def downgrade():
    bind = op.get_bind()
    postgres = bind.dialect.name == "postgresql"
    for demo in (True, False):
        next(iter(_definitions(demo, postgres).values())).metadata.drop_all(bind)
    if postgres:
        op.execute("DROP FUNCTION IF EXISTS msa_audit_immutable()")
        op.execute("DROP SCHEMA IF EXISTS demo")
    # Roles are cluster-wide and may serve another database; never drop them here.
