import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, PostgresDsn


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)
    database_url: PostgresDsn = "postgresql://msa:local@127.0.0.1:5432/msa"
    demo_database_url: PostgresDsn | None = None
    storage_root: Path = Path(".data/objects")
    # Which LLM answers (msa.integrations.llm.providers): local | deepseek | mock.
    llm_provider: str = Field(default="local", pattern=r"^(local|deepseek|mock)$")
    # Overrides of the provider profile; unset, the profile default applies.
    llm_base_url: HttpUrl | None = None
    llm_model: str | None = None
    # json_object: for APIs without strict json_schema support (e.g. DeepSeek).
    llm_json_mode: str | None = Field(default=None, pattern=r"^(json_schema|json_object)$")
    llm_timeout: float | None = Field(default=None, gt=0)
    # Output budget per LLM answer, reasoning included; a cut answer counts as an attempt.
    # Unset, the server decides: vLLM fills the rest of its context window.
    llm_max_tokens: int | None = Field(default=None, gt=0)
    # Native demonstration only: propose clearly attributed, unapproved scenario assumptions.
    demo_estimate_scenario: bool = False


def settings() -> Settings:
    """Read MSA_* on every call; no mutable process-wide settings singleton."""
    values = {
        name: os.environ[f"MSA_{name.upper()}"]
        for name in Settings.model_fields
        if f"MSA_{name.upper()}" in os.environ
    }
    if "llm_max_tokens" in values:
        values["llm_max_tokens"] = int(values["llm_max_tokens"])
    return Settings.model_validate(values)
