import os
from contextlib import ExitStack, asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from msa.config import settings
from msa.db.database import Database
from msa.db.session import engine
from msa.graph.checkpoint import build_checkpointer

from . import web
from .agent_service import AgentService
from .auth import KeyStore
from .explanations import ExplanationService
from .problem import install_handlers
from .ratelimit import RateLimiter
from .run_service import RunService


def check_platform():
    from msa.graph.compiler import WorkflowError, check
    from msa.platform.catalog import enabled_agents
    from msa.platform.registry import registry

    current = registry()
    problems = []
    for spec in current.workflows.values():
        problems += [f"{spec.workflow_id}: {p}" for p in check(spec, current, enabled_agents())]
    if problems:
        raise WorkflowError(problems)


def create_app(
    *,
    bind=None,
    demo_bind=None,
    keys=None,
    checkpointer=None,
    storage_root=None,
    agent_factory=None,
    mock_llm=None,
    recover=True,
):
    @asynccontextmanager
    async def lifespan(app):
        with ExitStack() as stack:
            # Plugins and workflows are checked before anything is served: an inconsistent
            # declaration stops the process with the list of problems.
            check_platform()
            config = settings()
            database = bind or engine()
            if bind is None:
                stack.callback(database.dispose)
            demo_database = demo_bind
            if demo_database is None and bind is None and config.demo_database_url:
                demo_database = engine(config.demo_database_url)
                stack.callback(demo_database.dispose)
            db = Database(database, demo_database)
            saver = checkpointer
            if saver is None:
                mode = os.getenv("MSA_CHECKPOINT_MODE", "postgres")
                connection = os.getenv("MSA_CHECKPOINT_URL", str(config.database_url))
                saver = stack.enter_context(build_checkpointer(mode, connection_string=connection))
            app.state.db = db
            app.state.keys = KeyStore(keys)
            app.state.limiter = RateLimiter(db)
            app.state.agents = AgentService(
                db,
                Path(storage_root or config.storage_root),
                factory=agent_factory,
                mock_llm=config.llm_provider == "mock" if mock_llm is None else mock_llm,
            )
            app.state.runs = RunService(db, app.state.agents, saver, app.state.limiter)
            stack.callback(app.state.runs.close)
            app.state.explanations = ExplanationService(db, app.state.agents, app.state.runs)
            if recover:
                app.state.runs.recover()
            yield

    app = FastAPI(
        title="MacroStress-Agent",
        version="0.1.0",
        lifespan=lifespan,
        openapi_url="/v1/openapi.json",
        docs_url="/docs",
    )
    install_handlers(app)
    from .routers import catalog, demo, documents, portfolios, runs, snapshots

    for module in (runs, documents, demo, catalog, portfolios, snapshots, web):
        app.include_router(module.router)
    web.mount(app)
    return app


app = create_app()
