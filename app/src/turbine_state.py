"""Operating state tracking and debouncing for turbine state timelines."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

# State assigned when a turbine stops reporting telemetry beyond timeout
DOWN_STATE = "DOWN"

# Allowed states matching database schema constraints
KNOWN_STATES = frozenset({"IDLE", "RAMP_UP", "STEADY_STATE", "RAMP_DOWN", DOWN_STATE})


@dataclass(frozen=True, slots=True)
class StateTransition:
    """Confirmed transition between two stable turbine operating states."""

    customer_id: str
    turbine_id: str
    device_path: str
    previous_state: str | None
    new_state: str
    changed_at_ms: int

    @property
    def key(self) -> tuple[str, str]:
        """Return (customer_id, turbine_id) key tuple."""
        return (self.customer_id, self.turbine_id)


@dataclass(slots=True)
class _TurbineTimeline:
    """Per-turbine mutable bookkeeping. Not part of the public API."""

    device_path: str
    confirmed_state: str | None = None
    candidate_state: str | None = None
    candidate_since_ms: int = 0
    last_seen_ms: int = 0


class StateTracker:
    """Debounces per-sample state inferences into stable operating state transitions."""

    def __init__(self, stability_seconds: float = 30.0, stale_seconds: float = 120.0) -> None:
        """Initialize debouncer with stability window and stale timeout."""
        if stability_seconds < 0:
            raise ValueError(f"stability_seconds must be >= 0, got {stability_seconds}")
        if stale_seconds <= stability_seconds:
            # Stale timeout must exceed stability window to prevent premature DOWN states
            raise ValueError(
                f"stale_seconds ({stale_seconds}) must exceed "
                f"stability_seconds ({stability_seconds})"
            )
        self._stability_ms = int(stability_seconds * 1000)
        self._stale_ms = int(stale_seconds * 1000)
        self._timelines: dict[tuple[str, str], _TurbineTimeline] = {}

    def observe(
        self,
        customer_id: str,
        turbine_id: str,
        device_path: str,
        state: str,
        timestamp_ms: int,
    ) -> Iterator[StateTransition]:
        """Yield transitions when a candidate state has persisted past stability_seconds."""
        if state not in KNOWN_STATES:
            raise ValueError(f"unknown turbine state: {state!r}")

        key = (customer_id, turbine_id)
        timeline = self._timelines.get(key)
        if timeline is None:
            timeline = _TurbineTimeline(device_path=device_path)
            self._timelines[key] = timeline

        timeline.device_path = device_path
        # Prevent replayed readings from rewinding the stability clock
        timeline.last_seen_ms = max(timeline.last_seen_ms, timestamp_ms)

        if state != timeline.candidate_state:
            timeline.candidate_state = state
            timeline.candidate_since_ms = timestamp_ms
            return

        if state == timeline.confirmed_state:
            return

        if timestamp_ms - timeline.candidate_since_ms < self._stability_ms:
            return

        yield self._confirm(key, timeline, state, timeline.candidate_since_ms)

    def tick(self, now_ms: int) -> Iterator[StateTransition]:
        """Yield DOWN transitions for turbines silent longer than stale_seconds."""
        for key, timeline in self._timelines.items():
            if timeline.confirmed_state == DOWN_STATE:
                continue
            if now_ms - timeline.last_seen_ms < self._stale_ms:
                continue
            # Timestamp from last received sample rather than current wall-clock time
            yield self._confirm(key, timeline, DOWN_STATE, timeline.last_seen_ms)

    def current_state(self, customer_id: str, turbine_id: str) -> str | None:
        """Return the last confirmed stable state for a turbine, or None if unconfirmed."""
        timeline = self._timelines.get((customer_id, turbine_id))
        return timeline.confirmed_state if timeline else None

    def _confirm(
        self,
        key: tuple[str, str],
        timeline: _TurbineTimeline,
        state: str,
        changed_at_ms: int,
    ) -> StateTransition:
        """Record confirmed state and return a StateTransition."""
        transition = StateTransition(
            customer_id=key[0],
            turbine_id=key[1],
            device_path=timeline.device_path,
            previous_state=timeline.confirmed_state,
            new_state=state,
            changed_at_ms=changed_at_ms,
        )
        timeline.confirmed_state = state
        timeline.candidate_state = state
        timeline.candidate_since_ms = changed_at_ms
        return transition
