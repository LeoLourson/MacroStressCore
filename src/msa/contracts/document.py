from hashlib import sha256
from typing import Literal

from pydantic import Field, model_validator

from .common import Contract, Identifier, Sha256


class Fragment(Contract):
    locator: Identifier
    text: str
    sha256: Sha256

    @model_validator(mode="after")
    def hash_matches_text(self):
        if sha256(self.text.encode("utf-8")).hexdigest() != self.sha256:
            raise ValueError("Fragment SHA-256 must match its UTF-8 text")
        return self


class Table(Contract):
    page: int = Field(ge=1, strict=True)
    index: int = Field(ge=1, strict=True)
    cells: list[list[str]]


class SourceDocument(Contract):
    doc_id: Identifier
    sha256: Sha256
    mime: Identifier
    fragments: list[Fragment]
    tables: list[Table] = Field(default_factory=list)
    status: Literal["parsed", "unparsed"] = "parsed"

    @model_validator(mode="after")
    def addressable(self):
        locators = [fragment.locator for fragment in self.fragments]
        if len(locators) != len(set(locators)):
            raise ValueError("Fragment locators must be unique")
        positions = [(table.page, table.index) for table in self.tables]
        if len(positions) != len(set(positions)):
            raise ValueError("Table positions must be unique")
        if self.status == "parsed" and not (self.fragments or self.tables):
            raise ValueError("Parsed documents require text or tables")
        return self

    def by_locator(self, locator: str) -> Fragment:
        for fragment in self.fragments:
            if fragment.locator == locator:
                return fragment
        raise KeyError(locator)
