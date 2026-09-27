import json
import logging
import time
from dataclasses import dataclass, field, replace
from urllib.error import HTTPError, URLError
from urllib.request import Request

from pydantic import BaseModel

from msa import activity

from .network import on_prem_url, open_without_redirect
from .providers import active
from .structured import decode, schema_instruction, with_schema

# Rate limits and server faults of an external API pass; other HTTP errors do not.
RETRY_STATUS = {429, 500, 502, 503, 504}
RETRIES = 2


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: dict


@dataclass(frozen=True)
class ToolTurn:
    """One answer of a tool-calling conversation: text, tool calls, or both."""

    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str | None = None

    def message(self) -> dict:
        """The assistant message to append to the conversation."""
        message = {"role": "assistant", "content": self.content or ""}
        if self.tool_calls:
            message["tool_calls"] = [
                {
                    "id": call.call_id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments, ensure_ascii=False),
                    },
                }
                for call in self.tool_calls
            ]
        return message


class ToolCallingUnsupported(RuntimeError):
    """The active provider does not answer with tool calls."""


class LLMClient:
    """OpenAI-compatible chat client for the active provider profile.

    ``observer`` receives one record per HTTP answer: provider, model, schema, purpose,
    status, duration and token usage. The API writes these records to ``audit_log``.
    """

    def __init__(
        self,
        *,
        base_url=None,
        api_key=None,
        model=None,
        opener=open_without_redirect,
        provider=None,
        observer=None,
    ):
        profile = provider or active()
        if base_url is not None:
            # An explicit endpoint is an on-prem server under test or evaluation.
            profile = replace(profile, name="local", base_url=on_prem_url(base_url), external=False)
        if profile.base_url is None:
            raise ValueError(f"LLM provider {profile.name!r} has no endpoint")
        self.provider = profile.name
        self.base_url = profile.base_url.rstrip("/")
        self.api_key = profile.api_key if api_key is None else api_key
        self.model = model or profile.model
        self.json_mode = profile.json_mode
        self.timeout = profile.timeout
        self.max_tokens = profile.max_tokens
        self.tool_calling = profile.tool_calling
        self.opener = opener
        self.observer = observer
        self.sleep = time.sleep

    def complete(self, messages: list[dict], schema: type[BaseModel], seed: int):
        content = self._chat(messages, schema, seed, purpose="answer")
        try:
            return decode(content, schema)
        except ValueError as exc:
            # One repair attempt: the model sees its answer and the validation error.
            repair = [
                *messages,
                {"role": "assistant", "content": content},
                {
                    "role": "user",
                    "content": "The json above failed validation. Return the corrected "
                    f"json object in full.\nValidation error:\n{exc}",
                },
            ]
            return decode(self._chat(repair, schema, seed, purpose="repair"), schema)

    def complete_with_tools(self, messages: list[dict], tools: list[dict], seed: int) -> ToolTurn:
        """One turn of a conversation in which the model may call ``tools``.

        ``tools`` are OpenAI function definitions. The provider's own timeout and retries
        apply; the caller runs the loop, executes the calls and bounds the rounds.
        """
        if not self.tool_calling:
            raise ToolCallingUnsupported(f"{self.provider} does not call tools")
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "seed": seed,
            "tools": tools,
            "tool_choice": "auto",
        }
        if self.max_tokens:
            payload["max_tokens"] = self.max_tokens
        if self.json_mode == "json_object":
            payload.pop("seed")
        record = {
            "provider": self.provider,
            "model": self.model,
            "schema": "tools",
            "purpose": "tool_turn",
        }
        started = time.perf_counter()
        try:
            with activity.llm_waiting({k: record[k] for k in ("model", "schema", "purpose")}):
                body = self._post(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            usage = body.get("usage") if isinstance(body, dict) else None
            if isinstance(usage, dict):
                record.update(
                    prompt_tokens=usage.get("prompt_tokens"),
                    completion_tokens=usage.get("completion_tokens"),
                )
            turn = self._turn(body)
            record["tool_calls"] = [call.name for call in turn.tool_calls]
        except Exception as exc:
            record.update(status="failed", error=f"{type(exc).__name__}: {str(exc)[:300]}")
            raise
        else:
            record["status"] = "completed"
            return turn
        finally:
            record["duration_ms"] = round((time.perf_counter() - started) * 1000)
            self._observe(record)

    def _turn(self, body) -> ToolTurn:
        try:
            choice = body["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError(f"LLM answer has no choices: {str(body)[:200]}") from exc
        if choice.get("finish_reason") == "length":
            raise ValueError(
                f"LLM answer was cut at the token limit (max_tokens={self.max_tokens})"
            )
        calls = []
        for index, item in enumerate(message.get("tool_calls") or []):
            function = item.get("function") or {}
            raw = function.get("arguments") or "{}"
            try:
                arguments = json.loads(raw) if isinstance(raw, str) else dict(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"tool call arguments are not JSON: {raw[:200]}") from exc
            calls.append(
                ToolCall(
                    call_id=item.get("id") or f"call-{index}",
                    name=function.get("name", ""),
                    arguments=arguments if isinstance(arguments, dict) else {},
                )
            )
        content = message.get("content")
        if not calls and (not isinstance(content, str) or not content.strip()):
            raise ValueError("LLM answer is empty")
        return ToolTurn(
            content=content, tool_calls=calls, finish_reason=choice.get("finish_reason")
        )

    def _chat(self, messages: list[dict], schema: type[BaseModel], seed: int, *, purpose) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "seed": seed,
            "response_format": with_schema(schema),
        }
        if self.max_tokens:
            payload["max_tokens"] = self.max_tokens
        if self.json_mode == "json_object":
            # No seed or strict schema support: the schema goes into the prompt instead.
            payload.pop("seed")
            payload["messages"] = [schema_instruction(schema), *messages]
            payload["response_format"] = {"type": "json_object"}
        record = {
            "provider": self.provider,
            "model": self.model,
            "schema": schema.__name__,
            "purpose": purpose,
        }
        started = time.perf_counter()
        try:
            with activity.llm_waiting({k: record[k] for k in ("model", "schema", "purpose")}):
                body = self._post(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            usage = body.get("usage") if isinstance(body, dict) else None
            if isinstance(usage, dict):
                details = usage.get("completion_tokens_details") or {}
                record.update(
                    prompt_tokens=usage.get("prompt_tokens"),
                    completion_tokens=usage.get("completion_tokens"),
                    reasoning_tokens=details.get("reasoning_tokens"),
                )
            content = self._content(body)
        except Exception as exc:
            record.update(status="failed", error=f"{type(exc).__name__}: {str(exc)[:300]}")
            raise
        else:
            record["status"] = "completed"
            return content
        finally:
            record["duration_ms"] = round((time.perf_counter() - started) * 1000)
            self._observe(record)

    def _content(self, body) -> str:
        # A cut, empty or malformed answer is a ValueError: it spends one of the caller's
        # attempts like any answer that fails validation.
        try:
            choice = body["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError(f"LLM answer has no choices: {str(body)[:200]}") from exc
        if choice.get("finish_reason") == "length":
            raise ValueError(
                f"LLM answer was cut at the token limit (max_tokens={self.max_tokens})"
            )
        if not isinstance(content, str) or not content.strip():
            raise ValueError("LLM answer is empty")
        return content

    def _observe(self, record):
        if self.observer is None:
            return
        try:
            self.observer(record)
        except Exception:
            # Accounting must never change what the model answered.
            logging.getLogger(__name__).exception("LLM call record was not stored")

    def _post(self, data: bytes) -> dict:
        for attempt in range(RETRIES + 1):
            request = Request(
                f"{self.base_url}/chat/completions",
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
                method="POST",
            )
            try:
                with self.opener(request, timeout=self.timeout) as response:
                    return json.load(response)
            except HTTPError as exc:
                if exc.code not in RETRY_STATUS or attempt == RETRIES:
                    raise
            except URLError:
                if attempt == RETRIES:
                    raise
            self.sleep(2 ** (attempt + 1))
