"""Explicit, auditable authorization for agent tool actions.

Safe by default: actions requiring approval are denied when no approval callback
is provided. The module intentionally does not execute commands itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from time import time
from typing import Callable, Dict, List, Optional


class ToolRisk(str, Enum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    DELETE = "delete"
    NETWORK = "network"


class PermissionDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


@dataclass(frozen=True)
class ToolRequest:
    tool: str
    action: str
    target: str = ""
    risk: ToolRisk = ToolRisk.READ
    details: str = ""


@dataclass(frozen=True)
class AuditEntry:
    timestamp: float
    request: ToolRequest
    approved: bool
    reason: str


ApprovalCallback = Callable[[ToolRequest], bool]


class PermissionPolicy:
    """A small policy engine; never treats a missing callback as approval."""

    def __init__(
        self,
        mode: str = "ask",
        approval_callback: Optional[ApprovalCallback] = None,
        audit_limit: int = 1000,
    ) -> None:
        if mode not in {"ask", "deny", "allow"}:
            raise ValueError("mode must be one of: ask, deny, allow")
        if audit_limit < 1:
            raise ValueError("audit_limit must be >= 1")
        self.mode = mode
        self.approval_callback = approval_callback
        self.audit_limit = audit_limit
        self.audit_log: List[AuditEntry] = []

    def authorize(self, request: ToolRequest) -> bool:
        if self.mode == "deny":
            return self._record(request, False, "policy_mode_deny")
        if self.mode == "allow":
            # Even in allow mode, destructive actions still require confirmation.
            if request.risk not in {ToolRisk.DELETE, ToolRisk.EXECUTE}:
                return self._record(request, True, "policy_mode_allow")
        if request.risk == ToolRisk.READ:
            return self._record(request, True, "read_only_action")
        if self.approval_callback is None:
            return self._record(request, False, "approval_required_but_no_callback")
        try:
            approved = bool(self.approval_callback(request))
        except Exception:
            return self._record(request, False, "approval_callback_failed")
        return self._record(request, approved, "user_approved" if approved else "user_denied")

    def _record(self, request: ToolRequest, approved: bool, reason: str) -> bool:
        self.audit_log.append(AuditEntry(time(), request, approved, reason))
        if len(self.audit_log) > self.audit_limit:
            del self.audit_log[: len(self.audit_log) - self.audit_limit]
        return approved

    def recent_audit(self, limit: int = 20) -> List[AuditEntry]:
        if limit < 0:
            raise ValueError("limit must be >= 0")
        return list(self.audit_log[-limit:]) if limit else []
