"""Questions about a calculated run, answered by the explanation workflow in the background."""

import logging
from uuid import uuid4

from msa.db.repositories.runs import DurableRunRepository, ExplanationsRepository
from msa.graph.checkpoint import run_config
from msa.graph.workflow import build_explanation_graph

from .problem import Problem


class ExplanationService:
    def __init__(self, db, agents, runs):
        self.db, self.agents, self.runs = db, agents, runs

    def ask(self, scope, run_id, question, principal):
        self.runs.status(scope, run_id)
        results, _ = self.runs.results(scope, run_id)
        if not results:
            raise Problem(409, "У прогона ещё нет результатов расчёта")
        if scope == "production" and self.agents.llm()["external"]:
            # The bank portfolio's numbers never reach a model outside the perimeter.
            raise Problem(409, "Внешняя LLM: объяснения доступны только для демо-портфелей")
        explanation_id = str(uuid4())
        with self.db.session(scope) as session:
            record = ExplanationsRepository(session).create(
                explanation_id, run_id, question, created_by=principal.actor
            )
        self.db.audit(
            scope,
            principal.actor,
            "explanation.created",
            run_id=run_id,
            details={"explanation_id": explanation_id},
        )
        self.runs.pool.submit(self.execute, scope, run_id, explanation_id)
        return self._view(record)

    def execute(self, scope, run_id, explanation_id):
        with self.db.session(scope) as session:
            record = ExplanationsRepository(session).get(explanation_id)
            ExplanationsRepository(session).update(explanation_id, status="running")
        try:
            graph = build_explanation_graph(
                explainer=self.agents.explainer(scope),
                repository=DurableRunRepository(self.db, scope),
            )
            state = graph.invoke(
                {
                    "run_id": run_id,
                    "explanation_id": explanation_id,
                    "question": record["question"],
                    "mode": scope,
                },
                config=run_config(run_id),
            )
            if state.get("status") != "completed" or "explanation" not in state:
                raise RuntimeError("; ".join(state.get("errors") or ["no explanation"]))
            answer = {**state["explanation"], "extensions": state.get("extensions") or {}}
            with self.db.session(scope) as session:
                ExplanationsRepository(session).update(
                    explanation_id, status="completed", answer=answer
                )
        except Exception as exc:
            logging.getLogger(__name__).exception("Explanation %s failed", explanation_id)
            with self.db.session(scope) as session:
                ExplanationsRepository(session).update(
                    explanation_id, status="failed", error=f"{type(exc).__name__}: {exc}"[:500]
                )

    def list(self, scope, run_id):
        self.runs.status(scope, run_id)
        with self.db.session(scope) as session:
            return [self._view(r) for r in ExplanationsRepository(session).for_run(run_id)]

    def get(self, scope, run_id, explanation_id):
        self.runs.status(scope, run_id)
        with self.db.session(scope) as session:
            record = ExplanationsRepository(session).get(explanation_id)
        if record["run_id"] != run_id:
            raise KeyError(explanation_id)
        return self._view(record)

    @staticmethod
    def _view(record):
        return {
            key: record[key]
            for key in (
                "explanation_id",
                "run_id",
                "question",
                "status",
                "answer",
                "error",
                "created_by",
                "created_at",
                "updated_at",
            )
        }
