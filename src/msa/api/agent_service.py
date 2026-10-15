"""What a run needs from the outside world, per namespace: agents, portfolios, snapshots and
documents."""

import base64
from datetime import date

from pydantic import BaseModel

from msa import activity
from msa.agents import build_agents
from msa.agents.ingest import IngestAgent
from msa.contracts import PortfolioBundle, SourceDocument
from msa.db.repositories.demo import DemoRepository
from msa.db.repositories.portfolios import PortfoliosRepository
from msa.db.repositories.rule_thresholds import RuleThresholdsRepository
from msa.db.repositories.runs import json_payload
from msa.integrations.llm.client import LLMClient
from msa.integrations.llm.providers import active as active_llm
from msa.mcp.gateway import McpResolver, ToolGateway
from msa.mcp.services import Services
from msa.platform.registry import registry
from msa.prompts.registry import current_version
from msa.db.originals import OriginalStore
from msa.version import code_sha256

from .problem import Problem

MAX_DOCUMENT_BYTES = 20 * 1024 * 1024


class RepositoryProxy:
    """A repository whose every call opens its own session in the namespace."""

    def __init__(self, db, scope, repository):
        self.db, self.scope, self.repository = db, scope, repository

    def __getattr__(self, method):
        def call(*args, **kwargs):
            with self.db.session(self.scope) as session:
                return getattr(self.repository(session), method)(*args, **kwargs)

        return call


class FixedDocument:
    """The ingest agent of a run whose event was parsed before the run started."""

    def __init__(self, document):
        self.document = document

    def run(self, payload):
        return self.document.model_copy(deep=True)


class AgentService:
    def __init__(self, db, storage_root, *, factory=None, mock_llm=False):
        self.db, self.storage_root, self.factory = db, storage_root, factory
        self.mock_llm = mock_llm
        self.code_hash = code_sha256()
        self._tools = {}

    def tools(self, scope):
        """The MCP servers of a namespace, called in-process by the run's agents (TZ 5)."""
        if scope not in self._tools:
            self._tools[scope] = ToolGateway(
                Services(self.db, scope, "agent:msa", self.storage_root)
            )
        return self._tools[scope]

    def options(self, scope) -> dict:
        """The plugins' run options of a namespace (the credit calibration in force)."""
        return registry().run_options(scope)

    def agents(self, scope, *, portfolio_id=None, model=None):
        if self.factory:
            return self.factory(scope=scope, mock_llm=self.mock_llm, portfolio_id=portfolio_id)
        tools = self.tools(scope)
        mock = self.mock_llm
        return build_agents(
            llm=None if mock else self.llm_client(scope, model),
            mock_llm=mock,
            registry=registry(),
            # Snapshot items come through mcp-portfolio, audited per call.
            resolver=McpResolver(tools, portfolio_id),
            thresholds_repository=RepositoryProxy(self.db, scope, RuleThresholdsRepository),
            original_store=OriginalStore(self.storage_root / scope),
            options=self.options(scope),
            tools=tools,
        )

    def llm_client(self, scope, model=None):
        """The model agents call, recorded per node; with fixtures (``mock``) there is none.

        ``model`` is the provider's strong model when the run chose it, else its default.
        """
        if self.mock_llm:
            return None
        return LLMClient(model=model, observer=self.llm_recorder(scope))

    def explain_llm(self, scope):
        """The model that explains results; with fixtures (``mock``) there is none."""
        return self.llm_client(scope)

    def explainer(self, scope):
        from msa.agents.explain import ExplainAgent

        return ExplainAgent(llm=self.explain_llm(scope), tools=self.tools(scope))

    def bundle(self, scope, portfolio_id) -> PortfolioBundle:
        with self.db.session(scope) as session:
            return PortfoliosRepository(session).get_bundle(portfolio_id)

    def names(self, scope, portfolio_id) -> dict[str, str]:
        with self.db.session(scope) as session:
            return PortfoliosRepository(session).names(portfolio_id)

    def valuation_date(self, scope, portfolio_id) -> date:
        """The portfolio's own valuation date; a portfolio without one is valued today."""
        with self.db.session(scope) as session:
            return PortfoliosRepository(session).valuation_date(portfolio_id) or date.today()

    def ingest(self, scope, payload):
        if isinstance(payload, BaseModel):
            payload = payload.model_dump(mode="json", exclude_none=True)
        if "content_base64" in payload:
            payload = {
                "bytes": base64.b64decode(payload["content_base64"], validate=True),
                "name": payload.get("filename", "document.pdf"),
            }
        content = payload.get("bytes", payload.get("text", "").encode("utf-8"))
        if len(content) > MAX_DOCUMENT_BYTES:
            raise Problem(413, "Document exceeds 20 MiB")
        document = IngestAgent(OriginalStore(self.storage_root / scope)).run(payload)
        self.db.put(
            scope,
            "api_document",
            {"doc_id": document.doc_id, "payload": document.model_dump(mode="json")},
        )
        return document

    def document(self, scope, event):
        event = json_payload(event)
        match event["kind"]:
            case "library":
                if scope != "demo":
                    raise Problem(403, "Event library is available only in demo")
                events = self.events(scope)
                found = next((e for e in events if e["event_id"] == event["id"]), None)
                if found is None:
                    raise KeyError(event["id"])
                return self.ingest(scope, {"text": found["text"]})
            case "doc_id":
                return SourceDocument.model_validate(
                    self.db.get(scope, "api_document", {"doc_id": event["doc_id"]})["payload"]
                )
            case "text" | "url":
                return self.ingest(scope, {k: v for k, v in event.items() if k != "kind"})
        raise ValueError("Unknown event kind")

    def llm(self):
        """The model that answers, and whether it lies outside the bank perimeter."""
        if self.mock_llm:
            return {
                "provider": "mock",
                "model": "mock",
                "base_url": None,
                "external": False,
                "strong_model": None,
            }
        return active_llm().describe()

    def llm_recorder(self, scope):
        """Every LLM answer goes to audit_log under the run, node and attempt that asked."""

        def record(entry):
            call = activity.current()
            self.db.audit(
                scope,
                f"llm:{entry['provider']}",
                "llm." + entry["status"],
                run_id=call and call["run_id"],
                node=call and call["node"],
                attempt=call and call["attempt"],
                standalone=call is None,
                details=entry,
            )

        return record

    def events(self, scope):
        with self.db.session(scope) as session:
            return DemoRepository(session).events()

    def stamp(self, model=None):
        """The versions a run records: the answering model, the prompt and the code."""
        return {
            "model_version": model or self.llm()["model"],
            "prompt_version": current_version("causal"),
            "code_sha256": self.code_hash,
            "macro_draws_sha256": None,
        }
