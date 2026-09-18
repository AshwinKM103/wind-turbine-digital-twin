"""
Operating state tracking and debouncing for turbine state timelines.

Tracks operational state sequences (IDLE, RAMP_UP, STEADY_STATE, RAMP_DOWN, DOWN)
and debounces transient spikes to produce stable state transition timelines.

The implementation supports:

    - Window-based candidate state debouncing
    - Stale turbine timeout detection producing DOWN state transitions
    - Idempotent and monotonic timestamp timeline validation

Key classes / functions:

    - StateTransition: Immutable confirmed state transition record.
    - StateTracker: Multi-turbine state debouncer and silence monitor.

"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

DOWN_STATE = "DOWN"
KNOWN_STATES = frozenset({"IDLE", "RAMP_UP", "STEADY_STATE", "RAMP_DOWN", DOWN_STATE})


@dataclass(frozen=True, slots=True)
class StateTransition:
    """
    Confirmed transition between two stable turbine operating states.

    Args:
        customer_id (str): Identifier of customer owning the turbine.
        turbine_id (str): Identifier of the turbine.
        device_path (str): Fully qualified IoTDB device path.
        previous_state (str | None): Prior confirmed operational state, or None.
        new_state (str): Newly confirmed operational state.
        changed_at_ms (int): Millisecond epoch timestamp when new state began.

    """

    customer_id: str
    turbine_id: str
    device_path: str
    previous_state: str | None
    new_state: str
    changed_at_ms: int

    @property
    def key(self) -> tuple[str, str]:
        """
        Return (customer_id, turbine_id) identification tuple.

        Returns:
            tuple[str, str]: Compound customer and turbine identifier key.

        """
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
    """
    Debounce per-sample state inferences into stable operating state transitions.

    Buffers state observations until they persist across a stability window
    before confirming transitions. Monitors quiet periods to generate DOWN states.

    Args:
        stability_seconds (float, optional): Duration a state must persist before confirmation. Defaults to 30.0.
        stale_seconds (float, optional): Maximum silence duration before declaring DOWN. Defaults to 120.0.

    """

    def __init__(self, stability_seconds: float = 30.0, stale_seconds: float = 120.0) -> None:
        if stability_seconds < 0:
            raise ValueError(f"stability_seconds must be >= 0, got {stability_seconds}")
        if stale_seconds <= stability_seconds:
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
        """
        Ingest a raw state observation and yield transitions when confirmed.

        Args:
            customer_id (str): Customer identifier.
            turbine_id (str): Turbine identifier.
            device_path (str): IoTDB device path string.
            state (str): Observed state candidate ('IDLE', 'RAMP_UP', etc.).
            timestamp_ms (int): Observation millisecond timestamp.

        Yields:
            StateTransition: Confirmed state transition event when candidate stabilizes.

        Raises:
            ValueError: If observed state is not in KNOWN_STATES.

        Example:
            >>> tracker = StateTracker(stability_seconds=10.0)
            >>> list(tracker.observe("c1", "t1", "root.c1.s1.t1", "RAMP_UP", 1000))
            []

        """
        if state not in KNOWN_STATES:
            raise ValueError(f"unknown turbine state: {state!r}")

        key = (customer_id, turbine_id)
        timeline = self._timelines.get(key)
        if timeline is None:
            timeline = _TurbineTimeline(device_path=device_path)
            self._timelines[key] = timeline

        timeline.device_path = device_path
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
        """
        Check for silent turbines and yield DOWN state transitions.

        Args:
            now_ms (int): Current millisecond timestamp.

        Yields:
            StateTransition: Transition to DOWN state for expired turbines.

        Example:
            >>> tracker = StateTracker(stale_seconds=60.0)
            >>> list(tracker.tick(1000000))
            []

        """
        for key, timeline in self._timelines.items():
            if timeline.confirmed_state == DOWN_STATE:
                continue
            if now_ms - timeline.last_seen_ms < self._stale_ms:
                continue
            yield self._confirm(key, timeline, DOWN_STATE, timeline.last_seen_ms)

    def current_state(self, customer_id: str, turbine_id: str) -> str | None:
        """
        Return the last confirmed stable state for a turbine.

        Args:
            customer_id (str): Customer identifier.
            turbine_id (str): Turbine identifier.

        Returns:
            str | None: Name of current stable state or None if not yet confirmed.

        Example:
            >>> tracker = StateTracker()
            >>> tracker.current_state("c1", "t1") is None
            True

        """
        timeline = self._timelines.get((customer_id, turbine_id))
        return timeline.confirmed_state if timeline else None

    def _confirm(
        self,
        key: tuple[str, str],
        timeline: _TurbineTimeline,
        state: str,
        changed_at_ms: int,
    ) -> StateTransition:
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

