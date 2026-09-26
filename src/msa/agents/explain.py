"""Explaining a calculated run: an LLM reads the run through MCP tools, within limits.

The agent is a LangGraph subgraph with its own state:

- ``ask`` gives the model the conversation and the ``mcp-runs`` tools (without ``run_id``:
  the agent adds it, so the model cannot read another run);
- ``act`` executes the calls the model chose, each an audited MCP call whose initiator is
  the LLM; at most ``MAX_TOOL_CALLS`` calls in all, at most ``MAX_ROUNDS`` model turns;
- ``check`` looks for every number of the answer in what the tools returned (as given,
  rounded, or times 100 when the answer shows a share in percent); one repair turn is
  allowed.

When the provider does not call tools, the model fails, the limits are reached or numbers
stay unverified, ``fallback`` assembles the answer from the run summary without a model and
says why. The explanation never changes the run: the tools only read.
"""

import json
import re
from decimal import Decimal
from hashlib import sha256
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from msa.contracts.explanation import CheckedNumber, Explanation, ExplanationSection, ToolUse
from msa.integrations.llm.client import ToolCallingUnsupported
from msa.prompts.registry import current_version
from msa.prompts.registry import get as prompt
from msa.reporting.builder import unit_words
from msa.reporting.numbers import extract_numbers, rounded
from msa.reporting.wording import EXECUTION, STATUSES

from .base import AgentFailure

MAX_ROUNDS = 6
MAX_TOOL_CALLS = 12
SERVER = "runs"
TOOLS = ("get_run_summary", "get_position_metrics", "get_metric_provenance", "describe_model")
#: Positions the structured answer names; the summary orders them by their weight in slices.
FALLBACK_POSITIONS = 10

_PATHS = re.compile(r"\[/[^\]]*\]")
_LIST_MARKERS = re.compile(r"^\s*\d+[.)]\s", re.MULTILINE)


class ExplainState(TypedDict, total=False):
    run_id: str
    question: str
    messages: list[dict]
    rounds: int
    pending: list[dict]
    calls: list[dict]
    #: Numbers each tool answer contained: ``{"tool": name, "values": [...]}``.
    sources: list[dict]
    answer: str | None
    repaired: bool
    checked: list[dict]
    unverified: list[str]
    fallback: str | None


class ExplainAgent:
    def __init__(self, *, llm, tools, max_rounds=MAX_ROUNDS, max_tool_calls=MAX_TOOL_CALLS):
        """``llm``: a client with ``complete_with_tools`` or ``None``; ``tools``: the
        namespace's ``ToolGateway``."""
        self.llm, self.tools = llm, tools
        self.max_rounds, self.max_tool_calls = max_rounds, max_tool_calls
        self.graph = self._build()

    # The subgraph ----------------------------------------------------------------------

    def _build(self):
        builder = StateGraph(ExplainState)
        builder.add_node("ask", self._ask)
        builder.add_node("act", self._act)
        builder.add_node("check", self._check)
        builder.add_edge(START, "ask")
        builder.add_conditional_edges("ask", self._after_ask, ["act", "check", END])
        builder.add_edge("act", "ask")
        builder.add_conditional_edges("check", self._after_check, ["ask", END])
        return builder.compile()

    def run(self, payload: dict) -> Explanation:
        run_id, question = payload["run_id"], payload["question"]
        state = {
            "run_id": run_id,
            "question": question,
            "messages": [
                {"role": "system", "content": prompt("explain")},
                {"role": "user", "content": question},
            ],
            "rounds": 0,
            "pending": [],
            "calls": [],
            "sources": [{"tool": "question", "values": _numbers_in(question)}],
            "answer": None,
            "repaired": False,
            "checked": [],
            "unverified": [],
            "fallback": None,
        }
        if self.llm is None or not getattr(self.llm, "tool_calling", False):
            state["fallback"] = "tool_calling_unsupported"
        else:
            # Each turn is bounded by the node count; the subgraph never loops past it.
            limit = 3 * (self.max_rounds + 2)
            state = self.graph.invoke(state, config={"recursion_limit": limit})
        if state.get("fallback"):
            return self._structured(state)
        return Explanation(
            run_id=run_id,
            question=question,
            mode="llm",
            text=state["answer"],
            numbers=[CheckedNumber.model_validate(n) for n in state["checked"]],
            tool_calls=[ToolUse.model_validate(c) for c in state["calls"]],
            rounds=state["rounds"],
            model=getattr(self.llm, "model", None),
            prompt_version=current_version("explain"),
        )

    def _ask(self, state):
        if state["rounds"] >= self.max_rounds:
            return {"fallback": "round_limit"}
        try:
            turn = self.llm.complete_with_tools(
                state["messages"], self._tool_specs(), seed=_seed(state["question"])
            )
        except ToolCallingUnsupported:
            return {"fallback": "tool_calling_unsupported"}
        except Exception as exc:  # noqa: BLE001 - any model failure falls back to structure
            return {"fallback": f"llm_failed: {type(exc).__name__}: {str(exc)[:200]}"}
        update = {
            "rounds": state["rounds"] + 1,
            "messages": [*state["messages"], turn.message()],
            "pending": [
                {"call_id": c.call_id, "name": c.name, "arguments": c.arguments}
                for c in turn.tool_calls
            ],
        }
        if not turn.tool_calls:
            update["answer"] = turn.content
        return update

    @staticmethod
    def _after_ask(state):
        if state.get("fallback"):
            return END
        return "act" if state["pending"] else "check"

    def _act(self, state):
        messages, calls = list(state["messages"]), list(state["calls"])
        sources = list(state["sources"])
        exhausted = False
        for call in state["pending"]:
            arguments = {k: v for k, v in call["arguments"].items() if k != "run_id"}
            if call["name"] not in TOOLS:
                answer, error = None, f"неизвестный инструмент {call['name']}"
            elif len(calls) >= self.max_tool_calls:
                answer, error, exhausted = None, "лимит вызовов инструментов исчерпан", True
            else:
                try:
                    answer = self.tools.call_as(
                        SERVER,
                        call["name"],
                        {**arguments, "run_id": state["run_id"]},
                        initiator="llm",
                        call_id=call["call_id"],
                    )
                    error = None
                except Exception as exc:  # noqa: BLE001 - the model reads the error
                    answer, error = None, str(exc)[:500]
            calls.append(
                {
                    "call_id": call["call_id"],
                    "name": call["name"],
                    "arguments": arguments,
                    "ok": error is None,
                    "error": error,
                }
            )
            if answer is not None:
                sources.append({"tool": call["name"], "values": _numbers_in(answer)})
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["call_id"],
                    "content": json.dumps(
                        answer if error is None else {"error": error}, ensure_ascii=False
                    ),
                }
            )
        if exhausted:
            messages.append(
                {
                    "role": "user",
                    "content": "Лимит вызовов инструментов исчерпан. Ответь по уже "
                    "полученным данным.",
                }
            )
        return {"messages": messages, "calls": calls, "sources": sources, "pending": []}

    def _check(self, state):
        checked, unverified = verify(state["answer"], state["sources"])
        if not unverified:
            return {"checked": checked, "unverified": []}
        if state["repaired"]:
            return {"checked": checked, "unverified": unverified, "fallback": "unverified_numbers"}
        repair = (
            "В ответе есть числа, которых нет в ответах инструментов: "
            + ", ".join(unverified)
            + ". Исправь ответ: используй только числа из ответов инструментов "
            "или вызови инструмент, который их даёт."
        )
        return {
            "repaired": True,
            "unverified": unverified,
            "messages": [*state["messages"], {"role": "user", "content": repair}],
        }

    @staticmethod
    def _after_check(state):
        if state.get("fallback") or not state.get("unverified"):
            return END
        return "ask"

    def _tool_specs(self) -> list[dict]:
        """The ``mcp-runs`` tools as the model sees them: without ``run_id`` and audit."""
        specs = []
        for item in self.tools.tools(SERVER):
            if item["name"] not in TOOLS:
                continue
            schema = dict(item["input_schema"] or {})
            properties = {
                k: v
                for k, v in (schema.get("properties") or {}).items()
                if k not in {"run_id", "audit"}
            }
            required = [k for k in schema.get("required", []) if k in properties]
            specs.append(
                {
                    "type": "function",
                    "function": {
                        "name": item["name"],
                        "description": item["description"],
                        "parameters": {
                            "type": "object",
                            "properties": properties,
                            "required": required,
                        },
                    },
                }
            )
        return specs

    # Without a model -------------------------------------------------------------------

    def _structured(self, state) -> Explanation:
        run_id = state["run_id"]
        try:
            summary = self.tools.call_as(
                SERVER, "get_run_summary", {"run_id": run_id}, initiator="workflow"
            )
        except Exception as exc:  # noqa: BLE001 - nothing to explain from
            raise AgentFailure([f"run summary is unavailable: {exc}"]) from exc
        sections = structured_sections(summary)
        reason = state["fallback"]
        lead = (
            "Ответ собран из сводки прогона без языковой модели: "
            + FALLBACK_REASONS.get(reason.partition(":")[0], reason)
            + "."
        )
        text = "\n\n".join(
            [lead] + [s.title + "\n" + "\n".join(f"— {line}" for line in s.lines) for s in sections]
        )
        return Explanation(
            run_id=run_id,
            question=state["question"],
            mode="structured",
            text=text,
            sections=sections,
            unverified=state.get("unverified") or [],
            tool_calls=[ToolUse.model_validate(c) for c in state.get("calls") or []],
            rounds=state.get("rounds") or 0,
            fallback_reason=reason,
            model=getattr(self.llm, "model", None),
            prompt_version=current_version("explain"),
        )


FALLBACK_REASONS = {
    "tool_calling_unsupported": "подключённая модель не вызывает инструменты",
    "round_limit": f"модель не ответила за {MAX_ROUNDS} шагов",
    "unverified_numbers": "в ответе модели остались числа, которых нет в данных прогона",
    "llm_failed": "модель не ответила",
}


def _seed(question: str) -> int:
    return int(sha256(question.encode("utf-8")).hexdigest()[:8], 16)


def _numbers_in(value) -> list[str]:
    """Every number a tool answer carries: numeric fields and numbers inside its texts."""
    found: list[str] = []

    def walk(item):
        if isinstance(item, bool) or item is None:
            return
        if isinstance(item, int | float):
            found.append(repr(float(item)))
        elif isinstance(item, str):
            found.extend(str(number) for number, _ in extract_numbers(item))
        elif isinstance(item, dict):
            for inner in item.values():
                walk(inner)
        elif isinstance(item, list | tuple):
            for inner in item:
                walk(inner)

    walk(value)
    return found


def _answer_numbers(text: str):
    """Numbers of an answer, without cited metric paths and list markers."""
    text = _PATHS.sub(" ", text or "")
    text = _LIST_MARKERS.sub(" ", text)
    # "1 234,5": digits grouped by spaces are one number.
    text = re.sub(r"(?<=\d)[   ](?=\d{3}(?!\d))", "", text)
    return extract_numbers(text)


def verify(answer: str, sources: list[dict]):
    """Which numbers of ``answer`` are found in the tools' answers, and which are not."""
    checked, unverified = [], []
    for number, places in _answer_numbers(answer):
        match = _find(number, places, sources)
        if match is None:
            unverified.append(format(number, "f"))
        else:
            checked.append(match)
    return checked, list(dict.fromkeys(unverified))


def _find(number: Decimal, places: int, sources):
    target = abs(number)
    for source in sources:
        for raw in source["values"]:
            value = abs(float(raw))
            for scaled, candidate in ((False, value), (True, value * 100)):
                if rounded(candidate, places) == target:
                    return {
                        "text": format(number, "f"),
                        "tool": source["tool"],
                        "source_value": float(raw),
                        "scaled": scaled,
                    }
    return None


def _num(value) -> str:
    if value is None:
        return "—"
    return f"{value:,.2f}".replace(",", " ").replace(".", ",")


def _triple(item) -> str:
    return f"P5 / P50 / P95 = {_num(item['p05'])} / {_num(item['p50'])} / {_num(item['p95'])}"


def structured_sections(summary: dict) -> list[ExplanationSection]:
    counts = summary["counts"]
    currency = summary.get("base_currency") or ""
    run = [
        f"Портфель {summary.get('portfolio_id')}, дата оценки {summary.get('as_of')}, "
        f"горизонт {summary.get('horizon_months')} мес., базовая валюта {currency}.",
        f"Позиций: {counts['positions']}; рассчитано: {counts['completed']}; "
        f"не рассчитано: {counts['not_run']}; с ошибкой: {counts['failed']}.",
    ]
    slices = []
    for item in summary.get("slices", []):
        status = STATUSES.get(item["status"], item["status"])
        if "p50" in item:
            slices.append(
                f"{item['label']} ({item['measure']}): {_triple(item)} {unit_words(item['unit'])}; "
                f"ES95 = {_num(item.get('es95'))}; покрытие {_num(item['covered_percent'])} %; "
                f"статус: {status}."
            )
        else:
            slices.append(f"{item['label']}: итог не рассчитан; статус: {status}.")
        for excluded in item.get("excluded", []):
            slices.append(
                f"{item['label']}: {excluded['position_id']} исключена — {excluded['reason']}."
            )
    positions = []
    for item in summary.get("positions", [])[:FALLBACK_POSITIONS]:
        name = f"{item['position_id']} {item['name']}".strip()
        if item["execution"] != "completed":
            positions.append(f"{name} ({item['type_label']}): {EXECUTION[item['execution']]}.")
            continue
        parts = []
        for metric in item["metrics"]:
            unit = unit_words(metric["unit"])
            if "p50" in metric:
                parts.append(f"{metric['label']}: {_triple(metric)} {unit}".rstrip())
            elif "value" in metric:
                parts.append(f"{metric['label']}: {_num(metric['value'])} {unit}".rstrip())
        status = STATUSES.get(item["status"], item["status"])
        positions.append(f"{name} ({item['type_label']}, {status}): " + "; ".join(parts) + ".")
    shown = summary.get("positions_shown", len(positions))
    if counts["positions"] > min(shown, FALLBACK_POSITIONS):
        positions.append(
            f"Показаны {min(shown, FALLBACK_POSITIONS)} позиций из {counts['positions']}, "
            "по вкладу в срезы портфеля."
        )
    scenario = [
        f"{item.get('label') or item['name']}: "
        + (
            f"{_num(item['low'])} … {_num(item['mode'])} … {_num(item['high'])}"
            if item.get("kind") == "triangular"
            else _num(item.get("value", item.get("mean")))
        )
        + f" ({item.get('unit', '')})"
        for item in summary.get("scenario", [])
    ]
    sections = [ExplanationSection(title="Прогон", lines=run)]
    if slices:
        sections.append(ExplanationSection(title="Срезы портфеля", lines=slices))
    if positions:
        sections.append(ExplanationSection(title="Позиции", lines=positions))
    if scenario:
        sections.append(ExplanationSection(title="Сценарий", lines=scenario))
    return sections
