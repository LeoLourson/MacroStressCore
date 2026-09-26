from typing import Protocol

from pydantic import JsonValue

from msa.contracts.api import Violation
from msa.contracts.common import Contract


class Verdict(Violation):
    ok: bool

    def violation(self) -> Violation | None:
        return None if self.ok else Violation(**self.model_dump(exclude={"ok"}))


class Validator(Protocol):
    def check(self, payload: JsonValue | Contract) -> list[Verdict]: ...
