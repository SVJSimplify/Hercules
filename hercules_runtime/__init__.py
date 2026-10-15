"""Hardened, framework-neutral runtime primitives for Hercules."""

from .agent_loop import AgentConfig, AgentResult, ModelResponse, run_agent
from .permissions import PermissionDecision, PermissionPolicy, ToolRequest, ToolRisk
from .tools import ToolRegistry, ToolResult, ToolSpec

__all__ = [
    "AgentConfig", "AgentResult", "ModelResponse", "run_agent",
    "PermissionDecision", "PermissionPolicy", "ToolRequest", "ToolRisk",
    "ToolRegistry", "ToolResult", "ToolSpec",
]
