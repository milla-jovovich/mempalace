"""CircuitBreaker base class for the walker subsystem."""

import threading
import time
from enum import Enum


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    """Raised when a call is attempted on an OPEN circuit breaker."""


class CircuitBreaker:
    """Thread-safe circuit breaker with HALF_OPEN single-shot probe.

    States:
      CLOSED    — calls pass through normally
      OPEN      — calls are rejected immediately with CircuitOpenError
      HALF_OPEN — exactly one probe call is allowed; success → CLOSED,
                  failure → OPEN again
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int,
        recovery_timeout_secs: float,
    ) -> None:
        self._name = name
        self._failure_threshold = failure_threshold
        self._recovery_timeout_secs = recovery_timeout_secs

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._probe_in_flight = False
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            return self._state

    def call(self, fn):
        """Execute *fn* according to the current circuit state.

        Raises:
            CircuitOpenError: if the circuit is OPEN and recovery timeout
                has not elapsed, or if another probe is already in flight
                during HALF_OPEN.
            Exception: any exception raised by *fn* itself (re-raised after
                updating failure bookkeeping).
        """
        with self._lock:
            if self._state == CircuitState.OPEN:
                elapsed = time.monotonic() - self._last_failure_time
                if elapsed >= self._recovery_timeout_secs:
                    # Transition to HALF_OPEN and allow this thread to probe
                    self._state = CircuitState.HALF_OPEN
                    self._probe_in_flight = True
                    allow_probe = True
                else:
                    raise CircuitOpenError(
                        f"Circuit '{self._name}' is OPEN "
                        f"(retry after {self._recovery_timeout_secs}s)"
                    )
            elif self._state == CircuitState.HALF_OPEN:
                if self._probe_in_flight:
                    raise CircuitOpenError(
                        f"Circuit '{self._name}' is HALF_OPEN — probe already in flight"
                    )
                # Should not normally reach here, but handle gracefully
                self._probe_in_flight = True
                allow_probe = True
            else:
                allow_probe = False  # CLOSED — normal call

        # Execute outside the lock so we don't block other threads
        try:
            result = fn()
        except Exception:
            with self._lock:
                if allow_probe:
                    # Probe failed — reopen
                    self._state = CircuitState.OPEN
                    self._last_failure_time = time.monotonic()
                    self._probe_in_flight = False
                else:
                    # Normal CLOSED failure
                    self._failure_count += 1
                    self._last_failure_time = time.monotonic()
                    if self._failure_count >= self._failure_threshold:
                        self._state = CircuitState.OPEN
            raise

        # Success
        with self._lock:
            if allow_probe:
                # Probe succeeded — reset and close
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                self._probe_in_flight = False

        return result

    async def call_async(self, afn):
        """Async analog of .call(): awaits afn() under the same state machine.

        afn must be a zero-arg callable returning an awaitable.
        The breaker wraps ONLY the awaited call — any post-processing the
        caller does with the result is NOT counted as a failure.
        """
        with self._lock:
            if self._state == CircuitState.OPEN:
                elapsed = time.monotonic() - self._last_failure_time
                if elapsed >= self._recovery_timeout_secs:
                    self._state = CircuitState.HALF_OPEN
                    self._probe_in_flight = True
                    allow_probe = True
                else:
                    raise CircuitOpenError(
                        f"Circuit '{self._name}' is OPEN "
                        f"(retry after {self._recovery_timeout_secs}s)"
                    )
            elif self._state == CircuitState.HALF_OPEN:
                if self._probe_in_flight:
                    raise CircuitOpenError(
                        f"Circuit '{self._name}' is HALF_OPEN — probe already in flight"
                    )
                self._probe_in_flight = True
                allow_probe = True
            else:
                allow_probe = False

        try:
            result = await afn()
        except Exception:
            with self._lock:
                if allow_probe:
                    self._state = CircuitState.OPEN
                    self._last_failure_time = time.monotonic()
                    self._probe_in_flight = False
                else:
                    self._failure_count += 1
                    self._last_failure_time = time.monotonic()
                    if self._failure_count >= self._failure_threshold:
                        self._state = CircuitState.OPEN
            raise

        with self._lock:
            if allow_probe:
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                self._probe_in_flight = False

        return result
