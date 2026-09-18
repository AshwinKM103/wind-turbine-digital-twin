"""
Durable, asynchronous PostgreSQL store for alerts and turbine state history.

Provides background-threaded, best-effort database persistence for threshold
breaches, confirmed alerts, and operational state transitions.

The implementation supports:

    - Non-blocking internal work queues with bounded capacity
    - Resilient reconnection with exponential backoff
    - Automatic retention pruning of aged records

Key classes / functions:

    - StoreMetrics: Counters tracking queued, written, and dropped work.
    - PostgresStore: Asynchronous background worker persisting telemetry events.

"""

from __future__ import annotations

import json
import queue
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from infrastructure import configure_logging
from turbine_state import StateTransition

log = configure_logging("postgres-store")

Statement = tuple[str, tuple[Any, ...]]
WorkUnit = list[Statement]

_SHUTDOWN = object()

_INSERT_ALERT = """
    INSERT INTO alerts (
        alert_id, customer_id, turbine_id, device_path, sensor,
        detection_type, severity, value, reason, threshold_info,
        start_time, event_time, logged_time
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (alert_id) DO NOTHING
"""

_LINK_BREACHES = """
    UPDATE alert_breaches
       SET alert_id = %s
     WHERE alert_id IS NULL
       AND customer_id = %s
       AND turbine_id = %s
       AND sensor = %s
       AND detection_type = %s
       AND event_time BETWEEN %s AND %s
"""

_INSERT_BREACH = """
    INSERT INTO alert_breaches (
        customer_id, turbine_id, sensor, detection_type, severity,
        value, turbine_state, confirmation_no, event_time, logged_time
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

_CLOSE_STATE = """
    UPDATE turbine_states
       SET end_time = %s
     WHERE customer_id = %s
       AND turbine_id = %s
       AND end_time IS NULL
       AND start_time <= %s
"""

_OPEN_STATE = """
    INSERT INTO turbine_states (
        customer_id, turbine_id, device_path, state, start_time
    ) VALUES (%s, %s, %s, %s, %s)
    ON CONFLICT (customer_id, turbine_id) WHERE end_time IS NULL DO NOTHING
"""

_PRUNE = "SELECT * FROM prune_retention(%s)"


@dataclass
class StoreMetrics:
    """
    Performance and operational metrics for PostgresStore.

    Args:
        enqueued (int): Total work items enqueued. Defaults to 0.
        written (int): Total work items written to database. Defaults to 0.
        dropped (int): Work items dropped due to queue saturation. Defaults to 0.
        failed (int): Database write transactions that failed. Defaults to 0.
        reconnects (int): Successful database reconnection attempts. Defaults to 0.

    """

    enqueued: int = 0
    written: int = 0
    dropped: int = 0
    failed: int = 0
    reconnects: int = 0

    def as_dict(self) -> dict[str, int]:
        """
        Return metrics counters as a dictionary.

        Returns:
            dict[str, int]: Key-value mapping of current metric counters.

        """
        return {
            "enqueued": self.enqueued,
            "written": self.written,
            "dropped": self.dropped,
            "failed": self.failed,
            "reconnects": self.reconnects,
        }


def _to_utc(timestamp_ms: int) -> datetime:
    return datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc)


class PostgresStore:
    """
    Background-threaded, best-effort writer for relational event history.

    Buffers database writes in an internal queue and flushes them asynchronously,
    preventing PostgreSQL latency or transient downtime from stalling the telemetry pipeline.

    Args:
        dsn (str): PostgreSQL connection DSN URI string.
        retention_days (int, optional): Days of historical data to retain. Defaults to 30.
        queue_size (int, optional): In-memory buffer queue limit. Defaults to 10000.
        prune_interval_s (float, optional): Seconds between retention pruning runs. Defaults to 3600.0.
        connect_backoff_max_s (float, optional): Maximum backoff seconds between retries. Defaults to 30.0.

    """

    def __init__(
        self,
        dsn: str,
        *,
        retention_days: int = 30,
        queue_size: int = 10_000,
        prune_interval_s: float = 3600.0,
        connect_backoff_max_s: float = 30.0,
    ) -> None:
        self._dsn = dsn
        self._retention_days = retention_days
        self._prune_interval_s = prune_interval_s
        self._connect_backoff_max_s = connect_backoff_max_s
        self._queue: queue.Queue[Any] = queue.Queue(maxsize=queue_size)
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()
        self._connection: Any = None
        self._connected = threading.Event()
        self.metrics = StoreMetrics()

    def start(self) -> None:
        """
        Start the background worker thread.

        Launches the background daemon thread if not already running.

        """
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="postgres-writer", daemon=True
        )
        self._thread.start()
        log.info("Postgres writer started", extra={"retention_days": self._retention_days})

    def close(self, timeout_s: float = 10.0) -> None:
        """
        Drain queued work and shut down the background thread.

        Args:
            timeout_s (float, optional): Maximum seconds to wait for worker to terminate. Defaults to 10.0.

        """
        if self._thread is None:
            return
        self._stopping.set()
        try:
            self._queue.put_nowait(_SHUTDOWN)
        except queue.Full:
            pass
        self._thread.join(timeout=timeout_s)
        if self._connection is not None:
            try:
                self._connection.close()
            except Exception as exc:  # noqa: BLE001 - shutdown must not raise
                log.warning("Error closing Postgres connection", extra={"error": str(exc)})
        log.info("Postgres writer stopped", extra=self.metrics.as_dict())

    @property
    def is_connected(self) -> bool:
        """
        Return whether the background worker currently has an active connection.

        Returns:
            bool: True if connected to PostgreSQL, False otherwise.

        """
        return self._connected.is_set()


    # -- public write API --------------------------------------------------

    def record_alert(
        self,
        alert: Any,
        *,
        start_time_ms: int,
        confirmation_window_start_ms: int,
    ) -> None:
        """
        Persist a confirmed alert and link prior breach records.

        Args:
            alert (Any): The confirmed Alert instance.
            start_time_ms (int): Millisecond epoch timestamp when anomaly condition started.
            confirmation_window_start_ms (int): Start time of confirmation window for linking breaches.

        """
        logged_time = datetime.now(timezone.utc)
        start_time = _to_utc(start_time_ms)
        event_time = _to_utc(alert.timestamp_ms)
        start_time = min(start_time, logged_time)

        threshold_info = (
            json.dumps(alert.threshold_info) if alert.threshold_info is not None else None
        )
        work: WorkUnit = [
            (
                _INSERT_ALERT,
                (
                    alert.alert_id,
                    alert.customer_id,
                    alert.turbine_id,
                    alert.device_path,
                    alert.sensor,
                    alert.detection_type,
                    alert.severity,
                    alert.value,
                    alert.reason,
                    threshold_info,
                    start_time,
                    event_time,
                    logged_time,
                ),
            ),
            (
                _LINK_BREACHES,
                (
                    alert.alert_id,
                    alert.customer_id,
                    alert.turbine_id,
                    alert.sensor,
                    alert.detection_type,
                    _to_utc(confirmation_window_start_ms),
                    event_time,
                ),
            ),
        ]
        self._enqueue(work, "alert")

    def record_breach(
        self,
        *,
        customer_id: str,
        turbine_id: str,
        sensor: str,
        detection_type: str,
        severity: str,
        value: float,
        turbine_state: str | None,
        confirmation_no: int,
        event_time_ms: int,
    ) -> None:
        """
        Persist an individual threshold breach observation.

        Args:
            customer_id (str): Identifier of customer.
            turbine_id (str): Identifier of turbine.
            sensor (str): Telemetry sensor measurement name.
            detection_type (str): Type of anomaly detection triggered.
            severity (str): Severity classification ('info', 'warning', 'critical').
            value (float): Observed telemetry value.
            turbine_state (str | None): Turbine operational state at breach time.
            confirmation_no (int): Progressive confirmation sequence counter.
            event_time_ms (int): Millisecond epoch timestamp of reading.

        """
        work: WorkUnit = [
            (
                _INSERT_BREACH,
                (
                    customer_id,
                    turbine_id,
                    sensor,
                    detection_type,
                    severity,
                    value,
                    turbine_state,
                    confirmation_no,
                    _to_utc(event_time_ms),
                    datetime.now(timezone.utc),
                ),
            )
        ]
        self._enqueue(work, "breach")

    def record_state_transition(self, transition: StateTransition) -> None:
        """
        Record a state transition by closing prior state and opening the new state.

        Args:
            transition (StateTransition): Confirmed state transition event.

        """
        changed_at = _to_utc(transition.changed_at_ms)
        work: WorkUnit = [
            (
                _CLOSE_STATE,
                (changed_at, transition.customer_id, transition.turbine_id, changed_at),
            ),
            (
                _OPEN_STATE,
                (
                    transition.customer_id,
                    transition.turbine_id,
                    transition.device_path,
                    transition.new_state,
                    changed_at,
                ),
            ),
        ]
        self._enqueue(work, "state_transition")


    # -- internals ---------------------------------------------------------

    def _enqueue(self, work: WorkUnit, kind: str) -> None:
        """Enqueue work unit, dropping oldest item if queue is full."""
        if self._stopping.is_set():
            return
        try:
            self._queue.put_nowait(work)
            self.metrics.enqueued += 1
            return
        except queue.Full:
            pass

        # Queue full: drop oldest unit to preserve recent records
        try:
            self._queue.get_nowait()
            self.metrics.dropped += 1
            self._queue.put_nowait(work)
            self.metrics.enqueued += 1
        except (queue.Empty, queue.Full):
            self.metrics.dropped += 1
        if self.metrics.dropped % 100 == 1:
            log.warning(
                "Postgres write queue full; dropping oldest work",
                extra={"kind": kind, "dropped_total": self.metrics.dropped},
            )

    def _run(self) -> None:
        """Main loop processing queued writes and running retention pruning."""
        next_prune = time.monotonic() + self._prune_interval_s
        while True:
            # Timeout allows periodic retention pruning on an idle queue
            try:
                work = self._queue.get(timeout=1.0)
            except queue.Empty:
                work = None

            if work is _SHUTDOWN:
                self._drain()
                return
            if work is not None:
                self._execute(work)
            if time.monotonic() >= next_prune:
                self._prune()
                next_prune = time.monotonic() + self._prune_interval_s

    def _drain(self) -> None:
        """Flush remaining queued work units during shutdown."""
        while True:
            try:
                work = self._queue.get_nowait()
            except queue.Empty:
                return
            if work is _SHUTDOWN or work is None:
                continue
            self._execute(work)

    def _connect(self) -> Any:
        """Return an active connection, reconnecting with exponential backoff if needed."""
        if self._connection is not None and not self._connection.closed:
            return self._connection

        import psycopg

        # Attempt connection before checking stop event to allow shutdown draining
        backoff = 1.0
        attempts = 0
        while True:
            attempts += 1
            if attempts > 5:
                raise RuntimeError("Failed to connect to Postgres after 5 attempts")
            try:
                self._connection = psycopg.connect(self._dsn, connect_timeout=5)
                self._connection.autocommit = False
                self._connected.set()
                log.info("Connected to Postgres")
                return self._connection
            except psycopg.Error as exc:
                self._connected.clear()
                self.metrics.reconnects += 1
                log.error(
                    "Postgres connect failed; retrying",
                    extra={"error": str(exc).strip(), "retry_in_s": backoff},
                )
                if self._stopping.is_set() or self._stopping.wait(backoff):
                    raise ConnectionError("Postgres writer is shutting down") from exc
                backoff = min(backoff * 2, self._connect_backoff_max_s)

    def _execute(self, work: WorkUnit) -> None:
        """Execute a work unit with a single retry attempt on connection error."""
        for attempt in (1, 2):
            try:
                connection = self._connect()
                with connection.cursor() as cursor:
                    for statement, params in work:
                        cursor.execute(statement, params)
                connection.commit()
                self.metrics.written += 1
                return
            except ConnectionError:
                return
            except Exception as exc:
                self._rollback()
                if attempt == 1:
                    self._discard_connection()
                    continue
                self.metrics.failed += 1
                log.exception(
                    "Postgres write failed; dropping work unit",
                    extra={
                        "error": str(exc).strip(),
                        "statements": len(work),
                        "first_statement": work[0][0].split()[0:3],
                    },
                )
                return

    def _prune(self) -> None:
        """Prune historical data older than configured retention period."""
        try:
            connection = self._connect()
            with connection.cursor() as cursor:
                cursor.execute(_PRUNE, (self._retention_days,))
                deleted: Sequence[tuple[str, int]] = cursor.fetchall()
            connection.commit()
            summary = {table: rows for table, rows in deleted}
            if any(summary.values()):
                log.info(
                    "Retention prune complete",
                    extra={"retention_days": self._retention_days, **summary},
                )
        except ConnectionError:
            return
        except Exception as exc:  # noqa: BLE001 - retention must not kill the thread
            self._rollback()
            self._discard_connection()
            log.error("Retention prune failed", extra={"error": str(exc).strip()})

    def _rollback(self) -> None:
        """Perform best-effort transaction rollback without propagating errors."""
        if self._connection is None:
            return
        try:
            self._connection.rollback()
        except Exception:  # noqa: BLE001, S110
            pass

    def _discard_connection(self) -> None:
        """Discard broken database connection so subsequent writes reconnect."""
        self._connected.clear()
        if self._connection is None:
            return
        try:
            self._connection.close()
        except Exception:  # noqa: BLE001, S110
            pass
        self._connection = None
