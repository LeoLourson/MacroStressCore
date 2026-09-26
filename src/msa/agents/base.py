"""Agent boundary shared by standalone calls and graph nodes."""

from functools import wraps
from typing import Protocol, TypeVar

from pydantic import ValidationError

Input = TypeVar("Input", contravariant=True)
Output = TypeVar("Output", covariant=True)


class Agent(Protocol[Input, Output]):
    def run(self, payload: Input) -> Output: ...


class AgentError(Exception):
    """An expected, retryable failure; programming errors are not swallowed."""


class AgentFailure(AgentError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        self.status = "needs_review"
        super().__init__("; ".join(errors))


def on_failure(error: AgentFailure) -> dict:
    return {"status": error.status, "errors": error.errors}


def with_retries(n=3):
    if not 1 <= n <= 3:
        raise ValueError("Agent attempts must be between 1 and 3")

    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            errors = []
            for _ in range(n):
                try:
                    return fn(*args, **kwargs)
                except (AgentError, ValidationError) as exc:
                    errors.append(str(exc))
            raise AgentFailure(errors)

        return wrapped

    return decorate
