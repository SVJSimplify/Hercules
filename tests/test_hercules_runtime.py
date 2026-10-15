import unittest

from hercules_runtime import (
    AgentConfig,
    ModelResponse,
    PermissionPolicy,
    ToolRegistry,
    ToolRequest,
    ToolRisk,
    ToolSpec,
    run_agent,
)
from hercules_runtime.retry import retry_call


class PermissionTests(unittest.TestCase):
    def test_read_is_allowed_by_default(self):
        policy = PermissionPolicy()
        self.assertTrue(policy.authorize(ToolRequest("list", "read", risk=ToolRisk.READ)))

    def test_write_is_denied_without_approval_callback(self):
        policy = PermissionPolicy()
        self.assertFalse(policy.authorize(ToolRequest("write", "write", risk=ToolRisk.WRITE)))

    def test_explicit_approval_allows_write(self):
        policy = PermissionPolicy(approval_callback=lambda request: True)
        self.assertTrue(policy.authorize(ToolRequest("write", "write", risk=ToolRisk.WRITE)))

    def test_audit_log_is_bounded(self):
        policy = PermissionPolicy(mode="deny", audit_limit=2)
        for _ in range(4):
            policy.authorize(ToolRequest("x", "x"))
        self.assertEqual(len(policy.audit_log), 2)


class ToolTests(unittest.TestCase):
    def test_unknown_tool_is_not_executed(self):
        registry = ToolRegistry()
        result = registry.execute("missing", {})
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "unknown_tool")

    def test_invalid_arguments_are_rejected(self):
        registry = ToolRegistry(PermissionPolicy(mode="allow"))
        registry.register(ToolSpec("echo", "echo", lambda args: args["text"], validator=lambda args: isinstance(args.get("text"), str)))
        result = registry.execute("echo", {"text": 7})
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "invalid_arguments")

    def test_output_is_truncated(self):
        registry = ToolRegistry(PermissionPolicy(mode="allow"))
        registry.register(ToolSpec("echo", "echo", lambda args: "x" * 100, max_output_chars=10))
        result = registry.execute("echo", {})
        self.assertTrue(result.ok)
        self.assertLessEqual(len(result.output), 40)


class AgentLoopTests(unittest.TestCase):
    def test_agent_can_finish_without_tools(self):
        result = run_agent("hello", lambda messages: ModelResponse(text="hi"), ToolRegistry())
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.text, "hi")

    def test_agent_runs_registered_tool_and_continues(self):
        registry = ToolRegistry(PermissionPolicy(mode="allow"))
        registry.register(ToolSpec("add", "add numbers", lambda args: str(args["a"] + args["b"])))
        responses = iter([
            ModelResponse(text="Calculating", tool_calls=[{"name": "add", "arguments": {"a": 2, "b": 3}}]),
            ModelResponse(text="5"),
        ])
        result = run_agent("2+3", lambda messages: next(responses), registry)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.tool_calls, 1)
        self.assertTrue(any('"output": "5"' in m["content"] for m in result.messages if m["role"] == "tool"))

    def test_step_budget_stops_tool_loop(self):
        registry = ToolRegistry(PermissionPolicy(mode="allow"))
        registry.register(ToolSpec("noop", "noop", lambda args: "ok"))
        result = run_agent(
            "go",
            lambda messages: ModelResponse(text="again", tool_calls=[{"name": "noop", "arguments": {}}]),
            registry,
            config=AgentConfig(max_steps=1, max_tool_calls=8),
        )
        self.assertEqual(result.status, "budget_exhausted")
        self.assertEqual(result.error, "step_budget_exceeded")

    def test_invalid_input_is_rejected(self):
        result = run_agent(" ", lambda messages: ModelResponse(text="unused"), ToolRegistry())
        self.assertEqual(result.error, "empty_user_message")


class RetryTests(unittest.TestCase):
    def test_retry_succeeds_after_transient_failure(self):
        calls = {"n": 0}
        def operation():
            calls["n"] += 1
            if calls["n"] < 3:
                raise OSError("temporary")
            return "ok"
        self.assertEqual(retry_call(operation, max_attempts=3, sleep_fn=lambda delay: None), "ok")
        self.assertEqual(calls["n"], 3)

    def test_non_retryable_exception_is_not_retried(self):
        calls = {"n": 0}
        def operation():
            calls["n"] += 1
            raise ValueError("bad input")
        with self.assertRaises(ValueError):
            retry_call(operation, max_attempts=5, retry_if=lambda exc: not isinstance(exc, ValueError), sleep_fn=lambda delay: None)
        self.assertEqual(calls["n"], 1)


if __name__ == "__main__":
    unittest.main()
