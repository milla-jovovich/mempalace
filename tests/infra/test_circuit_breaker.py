"""Tests for the CircuitBreaker base class used by the walker subsystem."""

import threading
import time

import pytest

from mempalace.infra.circuit_breaker import CircuitBreaker, CircuitState


def test_closed_lets_calls_through():
    cb = CircuitBreaker(name="test", failure_threshold=3, recovery_timeout_secs=60)
    assert cb.state == CircuitState.CLOSED

    calls = []

    def op():
        calls.append(1)
        return "ok"

    result = cb.call(op)
    assert result == "ok"
    assert len(calls) == 1


def test_opens_after_threshold_failures():
    cb = CircuitBreaker(name="test", failure_threshold=3, recovery_timeout_secs=60)

    def failing_op():
        raise RuntimeError("boom")

    for _ in range(3):
        with pytest.raises(RuntimeError):
            cb.call(failing_op)

    assert cb.state == CircuitState.OPEN


def test_open_rejects_calls_immediately():
    cb = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout_secs=60)

    with pytest.raises(RuntimeError):
        cb.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))

    assert cb.state == CircuitState.OPEN

    call_count = 0

    def probe():
        nonlocal call_count
        call_count += 1
        return "x"

    with pytest.raises(Exception):  # CircuitOpenError or similar
        cb.call(probe)

    assert call_count == 0, "OPEN circuit must not call the operation"


def test_half_open_single_probe_on_timeout():
    """After recovery_timeout_secs, exactly one probe is allowed (HALF_OPEN)."""
    cb = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout_secs=0.05)

    with pytest.raises(RuntimeError):
        cb.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))

    assert cb.state == CircuitState.OPEN
    time.sleep(0.1)  # wait past recovery timeout

    probe_count = 0

    def probe():
        nonlocal probe_count
        probe_count += 1
        return "ok"

    result = cb.call(probe)
    assert result == "ok"
    assert cb.state == CircuitState.CLOSED
    assert probe_count == 1


def test_half_open_probe_failure_reopens():
    cb = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout_secs=0.05)

    with pytest.raises(RuntimeError):
        cb.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))

    time.sleep(0.1)

    with pytest.raises(RuntimeError):
        cb.call(lambda: (_ for _ in ()).throw(RuntimeError("still broken")))

    assert cb.state == CircuitState.OPEN


def test_concurrent_open_check_is_thread_safe():
    """Many threads hitting an OPEN circuit must all be rejected without deadlock."""
    cb = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout_secs=60)

    with pytest.raises(RuntimeError):
        cb.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))

    errors = []

    def worker():
        try:
            cb.call(lambda: None)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=2)

    assert len(errors) == 20, "All 20 threads must be rejected by OPEN circuit"
