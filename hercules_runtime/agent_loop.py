"""A bounded, testable tool-calling agent loop.

The model callable receives a list of role/content dictionaries and returns a
ModelResponse (or compatible dictionary). Provider-specific network code stays
outside this module.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from threading import Event
from time import monotonic
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from .tools import ToolRegistry


@dataclass(frozen=True)
class ModelResponse:
    text: str = ""
    tool_calls: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    finish_reason: str = "stop"


@dataclass(frozen=True)
class AgentConfig:
    max_steps: int = 8
    max_tool_calls: int = 16
    max_wall_seconds: float = 120.0
    max_message_chars: int = 24000
    max_tool_argument_chars: int = 16000

    def __post_init__(self) -> None:
        if self.max_steps < 1 or self.max_tool_calls < 0:
            raise ValueError("step/tool budgets are invalid")
        if self.max_wall_seconds <= 0 or self.max_message_chars < 1:
            raise ValueError("time/message budgets are invalid")
        if self.max_tool_argument_chars < 1:
            raise ValueError("tool argument budget must be >= 1")


@dataclass
class AgentResult:
    text: str
    messages: List[Dict[str, str]]
    steps: int
    tool_calls: int
    status: str
    error: Optional[str] = None


ModelCallable = Callable[[List[Dict[str, str]]], Any]


def _coerce_response(value: Any) -> ModelResponse:
    if isinstance(value, ModelResponse):
        return value
    if isinstance(value, Mapping):
        calls = value.get("tool_calls", ()) or ()
        return ModelResponse(
            text=str(value.get("text", "") or ""),
            tool_calls=calls,
            finish_reason=str(value.get("finish_reason", "stop") or "stop"),
        )
    raise TypeError("model must return ModelResponse or a mapping")


def run_agent(
    user_message: str,
    model: ModelCallable,
    tools: ToolRegistry,
    *,
    config: Optional[AgentConfig] = None,
    cancel_event: Optional[Event] = None,
    on_step: Optional[Callable[[int, str], None]] = None,
) -> AgentResult:
    """Run one request while enforcing step, tool-call, output, and wall-clock budgets."""
    cfg = config or AgentConfig()
    cancel = cancel_event or Event()
    if not isinstance(user_message, str) or not user_message.strip():
        return AgentResult("", [], 0, 0, "error", "empty_user_message")
    if len(user_message) > cfg.max_message_chars:
        return AgentResult("", [], 0, 0, "error", "user_message_too_large")

    messages: List[Dict[str, str]] = [{"role": "user", "content": user_message}]
    started = monotonic()
    total_calls = 0
    last_text = ""

    for step in range(1, cfg.max_steps + 1):
        if cancel.is_set():
            return AgentResult(last_text, messages, step - 1, total_calls, "cancelled")
        if monotonic() - started >= cfg.max_wall_seconds:
            return AgentResult(last_text, messages, step - 1, total_calls, "budget_exhausted", "wall_clock_budget_exceeded")
        if on_step:
            try:
                on_step(step, "model")
            except Exception:
                pass

        try:
            response = _coerce_response(model(list(messages)))
        except Exception as exc:
            return AgentResult(last_text, messages, step, total_calls, "error", "model_failed: " + type(exc).__name__)

        text = response.text[: cfg.max_message_chars]
        if text:
            last_text = text
            messages.append({"role": "assistant", "content": text})

        calls = list(response.tool_calls or ())
        if not calls:
            return AgentResult(last_text, messages, step, total_calls, "completed")

        for call in calls:
            if cancel.is_set():
                return AgentResult(last_text, messages, step, total_calls, "cancelled")
            if monotonic() - started >= cfg.max_wall_seconds:
                return AgentResult(last_text, messages, step, total_calls, "budget_exhausted", "wall_clock_budget_exceeded")
            if total_calls >= cfg.max_tool_calls:
                return AgentResult(last_text, messages, step, total_calls, "budget_exhausted", "tool_call_budget_exceeded")

            name = str(call.get("name", "") or "")
            arguments = call.get("arguments", {})
            try:
                encoded = json.dumps(arguments, ensure_ascii=False)
            except (TypeError, ValueError):
                encoded = ""
            if len(encoded) > cfg.max_tool_argument_chars:
                result = {"ok": False, "output": "", "error": "tool_arguments_too_large"}
            else:
                tool_result = tools.execute(name, arguments)
                result = tool_result.to_dict()
            total_calls += 1
            messages.append({
                "role": "tool",
                "content": json.dumps({"name": name, "result": result}, ensure_ascii=False)[: cfg.max_message_chars],
            })

    return AgentResult(last_text, messages, cfg.max_steps, total_calls, "budget_exhausted", "step_budget_exceeded")
