"""Which LLM answers: one named profile instead of hand-set endpoint variables.

- ``local`` — any OpenAI-compatible server inside the perimeter: LM Studio on this host in
  the pre-product stand, vLLM in Compose (``MSA_LLM_BASE_URL``/``MSA_LLM_MODEL``).
- ``deepseek`` — the external DeepSeek API, a stand-in while no local model is available.
  It lies outside the bank perimeter, so runs are limited to synthetic demo portfolios.
- ``mock`` — deterministic fixtures, no network.

``MSA_LLM_PROVIDER`` selects the profile; the ``MSA_LLM_*`` settings override its fields.
"""

import os
from dataclasses import dataclass

from msa.config import settings

from .network import on_prem_url


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str | None
    model: str
    api_key: str
    json_mode: str
    timeout: float
    max_tokens: int | None
    external: bool
    #: Whether the endpoint answers with ``tool_calls`` (OpenAI function calling).
    tool_calling: bool = False
    #: A slower model of the same endpoint that a run may choose for a hard event.
    strong_model: str | None = None

    def describe(self) -> dict:
        """What the screens show: never the key."""
        return {
            "provider": self.name,
            "model": self.model,
            "base_url": self.base_url,
            "external": self.external,
            "tool_calling": self.tool_calling,
            "strong_model": self.strong_model,
        }


_PROFILES = {
    "local": {
        "base_url": "http://127.0.0.1:1234/v1",  # LM Studio's default server port.
        "model": "msa-local",
        "keys": ("MSA_LLM_API_KEY", "VLLM_API_KEY"),
        "json_mode": "json_schema",
        # Local models on a workstation answer slowly; a cut answer is still an attempt.
        "timeout": 300.0,
        "max_tokens": None,
        "external": False,
        # LM Studio and vLLM serve function calling for models that support it.
        "tool_calling": True,
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-flash",
        "keys": ("DEEPSEEK_API_KEY",),
        # No strict json_schema: the schema goes into the prompt (DeepSeek JSON mode).
        "json_mode": "json_object",
        # deepseek-v4-pro answers a causal prompt in two to four minutes.
        "timeout": 420.0,
        # deepseek-flash reasons for 7-8k tokens before an ~4k-token causal answer.
        "max_tokens": 64000,
        "external": True,
        "tool_calling": True,
        "strong_model": "deepseek-v4-pro",
    },
    "mock": {
        "base_url": None,
        "model": "mock",
        "keys": (),
        "json_mode": "json_schema",
        "timeout": 1.0,
        "max_tokens": None,
        "external": False,
        # Deterministic fixtures do not choose tools: explanations fall back to structure.
        "tool_calling": False,
    },
}


def active(config=None) -> Provider:
    config = config or settings()
    name = config.llm_provider
    profile = _PROFILES[name]
    base_url = str(config.llm_base_url) if config.llm_base_url else profile["base_url"]
    if name == "local":
        # A local profile pointed outside the perimeter is a configuration error, not a mode.
        base_url = on_prem_url(base_url)
    model = profile["model"]
    if name == "local":
        # Compose names the vLLM model in VLLM_SERVED_MODEL_NAME.
        model = os.getenv("VLLM_SERVED_MODEL_NAME", model)
    model = config.llm_model or model
    key = next((os.environ[k] for k in profile["keys"] if os.getenv(k)), "")
    return Provider(
        name=name,
        base_url=base_url,
        model=model,
        api_key=key,
        json_mode=config.llm_json_mode or profile["json_mode"],
        timeout=config.llm_timeout or profile["timeout"],
        max_tokens=config.llm_max_tokens or profile["max_tokens"],
        external=profile["external"],
        tool_calling=_tool_calling(profile),
        strong_model=profile.get("strong_model"),
    )


def _tool_calling(profile) -> bool:
    """The profile's default, unless ``MSA_LLM_TOOL_CALLING`` says otherwise."""
    value = os.getenv("MSA_LLM_TOOL_CALLING")
    if value is None:
        return profile["tool_calling"]
    return value.strip().lower() in {"1", "true", "yes"}
