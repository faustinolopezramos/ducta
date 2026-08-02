import threading

from ducta.gate.gateway.circuit_breaker import CircuitBreaker, CircuitState


class _FakeClock:
    def __init__(self, start: float = 0.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class TestCircuitBreakerClosed:
    def test_starts_closed(self):
        breaker = CircuitBreaker()
        assert breaker.is_open() is False
        assert breaker.state_dict()["state"] == CircuitState.CLOSED.value

    def test_failures_below_threshold_stay_closed(self):
        breaker = CircuitBreaker(failure_threshold=3)
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.is_open() is False

    def test_success_resets_failure_count(self):
        breaker = CircuitBreaker(failure_threshold=3)
        breaker.record_failure()
        breaker.record_failure()
        breaker.record_success()
        assert breaker.state_dict()["consecutive_failures"] == 0
        assert breaker.is_open() is False


class TestCircuitBreakerOpens:
    def test_opens_at_threshold(self):
        breaker = CircuitBreaker(failure_threshold=3)
        breaker.record_failure()
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.is_open() is True
        assert breaker.state_dict()["state"] == CircuitState.OPEN.value

    def test_stays_open_before_cooldown(self):
        clock = _FakeClock()
        breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=60.0, clock=clock)
        breaker.record_failure()
        clock.advance(30.0)
        assert breaker.is_open() is True


class TestCircuitBreakerHalfOpen:
    def test_transitions_to_half_open_after_cooldown(self):
        clock = _FakeClock()
        breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=60.0, clock=clock)
        breaker.record_failure()
        clock.advance(60.0)
        assert breaker.is_open() is False  # trial call allowed
        assert breaker.state_dict()["state"] == CircuitState.HALF_OPEN.value

    def test_half_open_success_closes(self):
        clock = _FakeClock()
        breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=60.0, clock=clock)
        breaker.record_failure()
        clock.advance(60.0)
        breaker.is_open()  # move to half-open
        breaker.record_success()
        assert breaker.state_dict()["state"] == CircuitState.CLOSED.value
        assert breaker.is_open() is False

    def test_half_open_failure_reopens(self):
        clock = _FakeClock()
        breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=60.0, clock=clock)
        breaker.record_failure()
        clock.advance(60.0)
        breaker.is_open()  # move to half-open
        breaker.record_failure()
        assert breaker.state_dict()["state"] == CircuitState.OPEN.value
        assert breaker.is_open() is True

    def test_only_one_thread_gets_the_trial_call(self):
        """Regression: without a lock around the OPEN -> HALF_OPEN transition,
        multiple threads calling is_open() at once (once the cooldown has
        elapsed) could all observe OPEN + elapsed cooldown and all get
        `False` (proceed) — several concurrent trial calls instead of
        exactly one, defeating half-open's entire purpose."""
        clock = _FakeClock()
        breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=60.0, clock=clock)
        breaker.record_failure()
        clock.advance(60.0)

        results = []
        results_lock = threading.Lock()
        start_barrier = threading.Barrier(20)

        def _check():
            start_barrier.wait()
            allowed = not breaker.is_open()
            with results_lock:
                results.append(allowed)

        threads = [threading.Thread(target=_check) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert results.count(True) == 1
