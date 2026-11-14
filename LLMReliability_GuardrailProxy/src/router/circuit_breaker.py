from dataclasses import dataclass
import time
from typing import Dict, Literal

CircuitState = Literal["CLOSED", "OPEN", "HALF_OPEN"]

@dataclass
class CircuitBreakerInfo:
    model_id: str
    state: CircuitState
    consecutive_failures: int
    recovery_in_sec: float

class CircuitBreakerManager:
    """
    Per-model Circuit Breaker protecting upstream LLM endpoints from cascading failures.
    States:
      - CLOSED: Normal operation
      - OPEN: Tripped after `failure_threshold` consecutive errors; rejects traffic for `recovery_timeout_sec`
      - HALF_OPEN: Allows probe request after recovery timeout; closes on success, re-opens on failure
    """
    def __init__(self, failure_threshold: int = 3, recovery_timeout_sec: float = 12.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout_sec = recovery_timeout_sec
        self._states: Dict[str, CircuitState] = {}
        self._failures: Dict[str, int] = {}
        self._opened_at: Dict[str, float] = {}

    def register_model(self, model_id: str) -> None:
        self._states.setdefault(model_id, "CLOSED")
        self._failures.setdefault(model_id, 0)
        self._opened_at.setdefault(model_id, 0.0)

    def can_execute(self, model_id: str) -> bool:
        info = self.get_info(model_id)
        return info.state in ("CLOSED", "HALF_OPEN")

    def record_success(self, model_id: str) -> None:
        self._failures[model_id] = 0
        self._states[model_id] = "CLOSED"
        self._opened_at[model_id] = 0.0

    def record_failure(self, model_id: str) -> None:
        count = self._failures.get(model_id, 0) + 1
        self._failures[model_id] = count
        current_state = self._states.get(model_id, "CLOSED")
        if current_state == "HALF_OPEN" or count >= self.failure_threshold:
            self._states[model_id] = "OPEN"
            self._opened_at[model_id] = time.monotonic()

    def force_state(self, model_id: str, state: CircuitState) -> None:
        self._states[model_id] = state
        if state == "OPEN":
            self._opened_at[model_id] = time.monotonic()
            self._failures[model_id] = self.failure_threshold
        elif state == "CLOSED":
            self._failures[model_id] = 0
            self._opened_at[model_id] = 0.0

    def get_info(self, model_id: str) -> CircuitBreakerInfo:
        state = self._states.get(model_id, "CLOSED")
        failures = self._failures.get(model_id, 0)
        opened_at = self._opened_at.get(model_id, 0.0)
        recovery_in = 0.0
        if state == "OPEN":
            elapsed = time.monotonic() - opened_at
            if elapsed >= self.recovery_timeout_sec:
                state = "HALF_OPEN"
                self._states[model_id] = "HALF_OPEN"
            else:
                recovery_in = round(self.recovery_timeout_sec - elapsed, 2)
        return CircuitBreakerInfo(
            model_id=model_id,
            state=state,
            consecutive_failures=failures,
            recovery_in_sec=recovery_in,
        )
