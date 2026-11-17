from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from types import SimpleNamespace

import pytest

from agent.llm import _rate_limit_delay
from agent import llm as llm_module


def rate_limit_error(retry_after):
    error = RuntimeError("rate limited")
    error.response = SimpleNamespace(headers={"retry-after": retry_after})
    return error


def test_rate_limit_delay_uses_retry_after_seconds():
    assert _rate_limit_delay(rate_limit_error("3.5"), 0) == 3.5


def test_rate_limit_delay_accepts_retry_after_http_date():
    retry_at = datetime.now(timezone.utc) + timedelta(seconds=5)

    delay = _rate_limit_delay(rate_limit_error(format_datetime(retry_at)), 0)

    assert delay == pytest.approx(5, abs=1)


def test_rate_limit_delay_falls_back_to_exponential_backoff():
    error = RuntimeError("rate limited")

    assert _rate_limit_delay(error, 0) == 2
    assert _rate_limit_delay(error, 4) == 30


def test_rate_limit_retry_honors_retry_after_and_retries(monkeypatch):
    class FakeRateLimitError(Exception):
        pass

    error = FakeRateLimitError("rate limited")
    error.response = SimpleNamespace(headers={"retry-after": "4"})
    delays = []
    calls = 0

    def call():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise error
        return "ok"

    monkeypatch.setattr(llm_module.groq, "RateLimitError", FakeRateLimitError)
    monkeypatch.setattr(llm_module.time, "sleep", delays.append)

    assert llm_module._with_backoff(call) == "ok"
    assert calls == 2
    assert delays == [4.0]
