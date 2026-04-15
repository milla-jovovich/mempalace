import asyncio
import pytest
from mempalace.infra.circuit_breaker import CircuitBreaker, CircuitOpenError, CircuitState


async def _ok(v): return v
async def _fail(): raise RuntimeError("boom")


async def test_async_closed_passes_through():
    cb = CircuitBreaker("t", failure_threshold=3, recovery_timeout_secs=1.0)
    assert await cb.call_async(lambda: _ok("hi")) == "hi"
    assert cb.state == CircuitState.CLOSED


async def test_async_opens_after_threshold():
    cb = CircuitBreaker("t", failure_threshold=2, recovery_timeout_secs=1.0)
    for _ in range(2):
        with pytest.raises(RuntimeError):
            await cb.call_async(lambda: _fail())
    assert cb.state == CircuitState.OPEN


async def test_async_open_rejects_immediately():
    cb = CircuitBreaker("t", failure_threshold=1, recovery_timeout_secs=10.0)
    with pytest.raises(RuntimeError):
        await cb.call_async(lambda: _fail())
    with pytest.raises(CircuitOpenError):
        await cb.call_async(lambda: _ok("x"))


async def test_async_half_open_success_closes():
    cb = CircuitBreaker("t", failure_threshold=1, recovery_timeout_secs=0.1)
    with pytest.raises(RuntimeError):
        await cb.call_async(lambda: _fail())
    await asyncio.sleep(0.15)
    assert await cb.call_async(lambda: _ok("probe")) == "probe"
    assert cb.state == CircuitState.CLOSED


async def test_async_half_open_failure_reopens():
    cb = CircuitBreaker("t", failure_threshold=1, recovery_timeout_secs=0.1)
    with pytest.raises(RuntimeError):
        await cb.call_async(lambda: _fail())
    await asyncio.sleep(0.15)
    with pytest.raises(RuntimeError):
        await cb.call_async(lambda: _fail())
    assert cb.state == CircuitState.OPEN


async def test_async_concurrent_probe_guard():
    cb = CircuitBreaker("t", failure_threshold=1, recovery_timeout_secs=0.05)
    with pytest.raises(RuntimeError):
        await cb.call_async(lambda: _fail())
    await asyncio.sleep(0.1)

    async def slow():
        await asyncio.sleep(0.05)
        return "slow"

    async def runner():
        try:
            return await cb.call_async(slow)
        except CircuitOpenError:
            return "blocked"

    results = await asyncio.gather(runner(), runner())
    assert results.count("slow") == 1
    assert results.count("blocked") == 1
