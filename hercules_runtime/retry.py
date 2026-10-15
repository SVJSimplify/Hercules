"""Bounded retry helper with explicit retry classification."""
from __future__ import annotations

from time import sleep
from typing import Callable, TypeVar

T = TypeVar("T")


def retry_call(
    operation: Callable[[], T],
    *,
    max_attempts: int = 3,
    initial_delay: float = 0.25,
    backoff_factor: float = 2.0,
    max_delay: float = 2.0,
    retry_if: Callable[[Exception], bool] = lambda exc: True,
    sleep_fn: Callable[[float], None] = sleep,
) -> T:
    """Retry transient failures only, with finite attempts and capped backoff."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    if initial_delay < 0 or max_delay < 0 or backoff_factor < 1:
        raise ValueError("invalid backoff configuration")

    delay = min(initial_delay, max_delay)
    for attempt in range(max_attempts):
        try:
            return operation()
        except Exception as exc:
            if attempt + 1 >= max_attempts or not retry_if(exc):
                raise
            if delay:
                sleep_fn(delay)
            delay = min(delay * backoff_factor, max_delay)
    raise RuntimeError("unreachable retry state")
