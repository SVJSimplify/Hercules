"""Validated tool registry and uniform result handling."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional

from .permissions import PermissionPolicy, ToolRequest, ToolRisk


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    output: str
    error: Optional[str] = None
    tool: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "output": self.output, "error": self.error, "tool": self.tool}


InputValidator = Callable[[Mapping[str, Any]], bool]
ToolHandler = Callable[[Mapping[str, Any]], Any]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    handler: ToolHandler
    risk: ToolRisk = ToolRisk.READ
    validator: Optional[InputValidator] = None
    max_output_chars: int = 12000


class ToolRegistry:
    """Only registered tools can execute; schemas and permissions are checked first."""

    def __init__(self, permission_policy: Optional[PermissionPolicy] = None) -> None:
        self._tools: Dict[str, ToolSpec] = {}
        self.permission_policy = permission_policy or PermissionPolicy(mode="ask")

    def register(self, spec: ToolSpec) -> None:
        if not spec.name or not spec.name.replace("_", "").replace("-", "").isalnum():
            raise ValueError("tool name must be a non-empty identifier")
        if spec.name in self._tools:
            raise ValueError("tool already registered: " + spec.name)
        if spec.max_output_chars < 1:
            raise ValueError("max_output_chars must be >= 1")
        self._tools[spec.name] = spec

    def names(self):
        return tuple(sorted(self._tools))

    def descriptions(self) -> Dict[str, str]:
        return {name: spec.description for name, spec in self._tools.items()}

    def execute(self, name: str, arguments: Mapping[str, Any]) -> ToolResult:
        spec = self._tools.get(name)
        if spec is None:
            return ToolResult(False, "", "unknown_tool", name)
        if not isinstance(arguments, Mapping):
            return ToolResult(False, "", "arguments_must_be_an_object", name)
        request = ToolRequest(
            tool=name,
            action="invoke",
            target=name,
            risk=spec.risk,
            details=spec.description,
        )
        if not self.permission_policy.authorize(request):
            return ToolResult(False, "", "permission_denied", name)
        if spec.validator is not None:
            try:
                valid = bool(spec.validator(arguments))
            except Exception:
                valid = False
            if not valid:
                return ToolResult(False, "", "invalid_arguments", name)
        try:
            value = spec.handler(arguments)
            if isinstance(value, str):
                output = value
            else:
                output = str(value)
            if len(output) > spec.max_output_chars:
                output = output[: spec.max_output_chars] + "\n[output truncated]"
            return ToolResult(True, output, None, name)
        except Exception as exc:
            # Avoid dumping tracebacks or environment details into the model context.
            return ToolResult(False, "", "tool_failed: " + type(exc).__name__, name)
