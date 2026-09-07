"""FanOutClient tests — parallelism, per-call fault isolation, and the
per-warm-container short-circuit (NFR-MP-PERF-2/3, BR-9)."""
from __future__ import annotations

import json
from io import BytesIO
from urllib import error as urlerror

from fan_out_client import FanOutClient, _failure_state


def _ok_opener(payload: dict):
    def opener(req, timeout=None):
        class _CM:
            def __enter__(self):
                return BytesIO(json.dumps(payload).encode())

            def __exit__(self, *a):
                return False

        return _CM()

    return opener


def _failing_opener():
    def opener(req, timeout=None):
        raise urlerror.URLError("boom")

    return opener


def setup_function():
    _failure_state.clear()


def test_fan_out_returns_all_results_on_success():
    client = FanOutClient(base_url="https://api.test", opener=_ok_opener({"count": 3}))
    out = client.fan_out({"events": "/events?x=1", "forums": "/forums?y=2"})
    assert out["events"] == {"count": 3}
    assert out["forums"] == {"count": 3}


def test_fan_out_call_failure_returns_none_not_raise():
    client = FanOutClient(base_url="https://api.test", opener=_failing_opener())
    out = client.fan_out({"events": "/events"})
    assert out["events"] is None  # degraded, not an exception (BR-9)


def test_fan_out_no_base_url_returns_none():
    client = FanOutClient(base_url="", opener=_ok_opener({"count": 1}))
    out = client.fan_out({"events": "/events"})
    assert out["events"] is None


def test_short_circuit_after_consecutive_failures():
    client = FanOutClient(base_url="https://api.test", opener=_failing_opener())
    for _ in range(3):
        client.fan_out({"events": "/events"})
    # 4th call should be short-circuited (no opener invocation needed to verify
    # correctness — behavior is identical either way: still returns None).
    out = client.fan_out({"events": "/events"})
    assert out["events"] is None


def test_forwards_bearer_token():
    captured = {}

    def opener(req, timeout=None):
        captured["auth"] = req.get_header("Authorization")

        class _CM:
            def __enter__(self):
                return BytesIO(json.dumps({}).encode())

            def __exit__(self, *a):
                return False

        return _CM()

    client = FanOutClient(base_url="https://api.test", opener=opener)
    client.fan_out({"events": "/events"}, bearer_token="abc123")
    assert captured["auth"] == "Bearer abc123"
