"""Every MCP tool call lands in ``audit_log``: who asked, for which run and node, how long.

``initiator`` says whether the workflow called the tool itself or an LLM chose it; the
digests identify the arguments and the answer without storing them.
"""

import asyncio
import inspect
import json
import time
from functools import wraps
from hashlib import sha256
from typing import Literal

from pydantic import Field, model_validator

from msa.contracts.common import Contract, Identifier


class CallContext(Contract):
    run_id: Identifier | None = None
    node: Identifier
    attempt: int = Field(ge=1, strict=True)
    standalone: bool = False
    initiator: Literal["workflow", "llm"] = "workflow"
    #: The LLM's id of the call, when an LLM made it.
    call_id: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def ownership(self):
        if self.standalone == (self.run_id is not None):
            raise ValueError("Provide run_id, or standalone=true without run_id")
        return self


def audited(tool, services):
    def decorate(fn):
        @wraps(fn)
        async def invoke(*args, **kwargs):
            # The calculation and the audit writes are blocking; off the gateway's event loop
            # they run in parallel across the run's branches.
            return await asyncio.to_thread(call, *args, **kwargs)

        def call(*args, **kwargs):
            bound = inspect.signature(fn).bind(*args, **kwargs)
            context = CallContext.model_validate(bound.arguments["audit"])
            # A caller cannot attribute a tool call to a run outside the server's data scope.
            if context.run_id:
                services.db.get(services.scope, "run", {"run_id": context.run_id})
            status = "completed"
            details = {
                "initiator": context.initiator,
                "call_id": context.call_id,
                "input_sha256": _digest({k: v for k, v in bound.arguments.items() if k != "audit"}),
            }
            started = time.perf_counter()
            try:
                result = fn(*args, **kwargs)
                details["output_sha256"] = _digest(result)
                return result
            except Exception as exc:
                status = "failed"
                details["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
                raise
            finally:
                details["duration_ms"] = round((time.perf_counter() - started) * 1000)
                services.db.audit(
                    services.scope,
                    services.actor,
                    "tool." + status,
                    run_id=context.run_id,
                    node=context.node,
                    attempt=context.attempt,
                    tool=tool,
                    standalone=context.standalone,
                    details=details,
                )

        return invoke

    return decorate


def _digest(value) -> str:
    text = json.dumps(value, sort_keys=True, default=str, ensure_ascii=False)
    return sha256(text.encode("utf-8")).hexdigest()
