import json
from collections.abc import Callable
from dataclasses import dataclass, field
from hashlib import sha256

from langchain_core.runnables import RunnableConfig
from pydantic import TypeAdapter

from msa import activity
from msa.agents import Agents
from msa.agents.base import AgentFailure, on_failure, with_retries
from msa.db.repositories.runs import RunRepository, json_payload

from .checkpoint import thread_id


class InputsChanged(RuntimeError):
    """A node's recorded result was produced from other inputs than it has now."""


@dataclass
class NodeContext:
    agents: Agents
    repository: RunRepository
    validate: Callable
    auto_approve_demo: bool = False
    registry: object = None
    #: Run options of the namespace, passed to the models (``credit.registry_id``, ...).
    options: dict = field(default_factory=dict)

    def call(self, name, payload, output_type):
        @with_retries()
        def invoke():
            result = getattr(self.agents, name).run(payload)
            return TypeAdapter(output_type).validate_python(json_payload(result))

        return invoke()


def node_key(name, state, *, branch=None):
    revision = state.get("graph_revision", 0)
    if name == "causal_agent":
        attempt = state.get("attempts", 0) + 1
    elif name == "validate_causal":
        attempt = state["attempts"] + revision
    else:
        attempt = revision + 1
    if branch is not None:
        name = f"{name}/{state[branch]}"
    return name, attempt


def digest(value) -> str:
    text = json.dumps(json_payload(value), sort_keys=True, separators=(",", ":"))
    return sha256(text.encode("utf-8")).hexdigest()


def journaled(name, fn, context, *, version=None, inputs=None, branch=None):
    """Run a node once per key; replay its recorded result on a resumed run.

    A node is identified by its name, the position branch, the scenario revision, the
    agent version and a hash of what it read. A recorded result whose inputs differ from
    the current ones is never replayed silently.
    """

    def run(state, config: RunnableConfig):
        run_id = state["run_id"]
        if config["configurable"]["thread_id"] != thread_id(run_id):
            raise ValueError("thread_id does not match run_id")
        node, attempt = node_key(name, state, branch=branch)
        inputs_sha256 = digest(inputs(state)) if inputs is not None else None
        saved = context.repository.get_node_result(run_id, node, attempt)
        with activity.node_call(run_id, node, attempt):
            if saved is not None:
                identity = context.repository.node_identity(run_id, node, attempt)
                recorded = identity[1] if identity else None
                if inputs_sha256 and recorded and recorded != inputs_sha256:
                    raise InputsChanged(
                        f"{node} (attempt {attempt}) read other inputs than it now has; "
                        "a change needs a new scenario revision"
                    )
                return saved
            try:
                update = fn(state)
            except AgentFailure as exc:
                update = {**on_failure(exc), "published": False}
            update = json_payload({**update, "trace": [name]})
            context.repository.upsert_node_result(
                run_id, node, attempt, update, agent_version=version, inputs_sha256=inputs_sha256
            )
            return update

    return run
