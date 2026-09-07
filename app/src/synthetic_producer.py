#!/usr/bin/env python3
"""
synthetic_producer.py - Per-turbine synthetic telemetry generator -> Kafka.

The sole telemetry source for the stack. An earlier design replayed one
fixed recording, so every turbine running that image emitted byte-identical
data -- useless for a fleet view and for anomaly detection, which cannot
distinguish a real deviation from a replay artefact. This
generator instead synthesises each of the 61 channels from the physical
profiles in sensor_profiles.py, driven by an operating-state machine, so
turbines differ from each other, drift over time, and stay internally
correlated (RPM, torque, bearing temperature and vibration rise together).

One container = one turbine. Identity, cadence and state-machine timings
all come from environment variables (see config.py / .env.example), so the
same image serves every turbine in docker-compose.yml with only env vars
changing.

The Kafka payload shape is stable for consumers -- topic
`turbine.telemetry.raw.v1`, key `customer_id:turbine_id`, plus an
additive `operating_state` field that consumers are free to ignore.

Run with:
    python synthetic_producer.py
"""

from __future__ import annotations

import json
import math
import random
import signal
import sys
import time
import uuid
from dataclasses import dataclass
from enum import StrEnum
from types import FrameType

from config import Config
from confluent_kafka import Producer
from health_server import start_health_server
from logging_config import configure_logging
from sensor_profiles import (
    IDLE_NOISE_FRACTION,
    SENSOR_PROFILES,
    TURBINE_BIAS_FRACTION,
    SensorProfile,
)

log = configure_logging("synthetic-producer")

SECONDS_PER_HOUR = 3600.0


class OperatingState(StrEnum):
    """Turbine operating states, matching config/anomaly_thresholds.json."""

    IDLE = "IDLE"
    RAMP_UP = "RAMP_UP"
    STEADY_STATE = "STEADY_STATE"
    RAMP_DOWN = "RAMP_DOWN"


# Depth of the slow load swing during STEADY_STATE, as a fraction of each
# channel's idle->load span. A real machine holding load still breathes with
# grid demand and governor action; pinning the load factor at exactly 1.0
# drew a dead flat line instead.
#
# The ceiling on this number is set by config/anomaly_thresholds.json, not by
# taste: TURBINE_SPEED_RPM spans 120->11800, its STEADY_STATE warning band is
# 11500-12000, and per-unit calibration bias (TURBINE_BIAS_FRACTION) already
# moves a turbine +-236 rpm inside that band. 0.01 of span is ~117 rpm of
# swing, which leaves the fleet inside the warning band; doubling it would
# turn normal operation into a permanent warning. See the
# steady-state-headroom check in tools/ for the arithmetic.
STEADY_RIPPLE_AMPLITUDE = 0.01

# Ripple shape: two raised cosines over the steady window. Integer cycle
# counts matter -- a raised cosine is zero *and has zero slope* at both ends
# of the window, so the ripple joins the flat ends of RAMP_UP and RAMP_DOWN
# with no step and no kink in the first derivative. Two incommensurate-
# looking harmonics keep it from reading as an obvious sine wave.
_RIPPLE_HARMONICS: tuple[tuple[int, float], ...] = ((3, 0.7), (7, 0.3))


def _smoothstep(progress: float) -> float:
    """S-curve easing on [0, 1] -- ramps start and end gently, as a real
    machine does, rather than the velocity discontinuity a linear ramp
    would put into every derivative-based anomaly rule."""
    clamped = min(1.0, max(0.0, progress))
    return clamped * clamped * (3.0 - 2.0 * clamped)


def _steady_ripple(progress: float) -> float:
    """Load deficit in [0, 1] at `progress` through the STEADY_STATE window.

    Zero at both ends by construction, so STEADY_STATE still starts and
    finishes at exactly full load and the surrounding ramps need no special
    casing.
    """
    clamped = min(1.0, max(0.0, progress))
    return sum(
        weight * 0.5 * (1.0 - math.cos(2.0 * math.pi * cycles * clamped))
        for cycles, weight in _RIPPLE_HARMONICS
    )


@dataclass(frozen=True, slots=True)
class StateMachineTimings:
    """Duration of each operating state, in seconds."""

    idle_s: float
    ramp_up_s: float
    steady_state_s: float
    ramp_down_s: float

    @classmethod
    def from_config(cls) -> StateMachineTimings:
        return cls(
            idle_s=Config.STATE_IDLE_DURATION_S,
            ramp_up_s=Config.STATE_RAMP_UP_DURATION_S,
            steady_state_s=Config.STATE_STEADY_DURATION_S,
            ramp_down_s=Config.STATE_RAMP_DOWN_DURATION_S,
        )

    def __post_init__(self) -> None:
        for name in ("idle_s", "ramp_up_s", "steady_state_s", "ramp_down_s"):
            if getattr(self, name) <= 0:
                raise ValueError(f"StateMachineTimings.{name} must be > 0")

    @property
    def cycle_s(self) -> float:
        return self.idle_s + self.ramp_up_s + self.steady_state_s + self.ramp_down_s


class OperatingStateMachine:
    """Cycles IDLE -> RAMP_UP -> STEADY_STATE -> RAMP_DOWN -> IDLE forever,
    exposing a single load factor in [0, 1] that drives all 61 channels."""

    def __init__(self, timings: StateMachineTimings, start_offset_s: float = 0.0) -> None:
        self._timings = timings
        self._start_offset_s = start_offset_s

    def state_at(self, elapsed_s: float) -> tuple[OperatingState, float]:
        """Return the (state, load_factor) for a given seconds-since-start."""
        t = (elapsed_s + self._start_offset_s) % self._timings.cycle_s

        if t < self._timings.idle_s:
            return OperatingState.IDLE, 0.0
        t -= self._timings.idle_s

        if t < self._timings.ramp_up_s:
            return OperatingState.RAMP_UP, _smoothstep(t / self._timings.ramp_up_s)
        t -= self._timings.ramp_up_s

        if t < self._timings.steady_state_s:
            deficit = STEADY_RIPPLE_AMPLITUDE * _steady_ripple(t / self._timings.steady_state_s)
            return OperatingState.STEADY_STATE, 1.0 - deficit
        t -= self._timings.steady_state_s

        return OperatingState.RAMP_DOWN, 1.0 - _smoothstep(t / self._timings.ramp_down_s)


def _decay(dt_s: float, time_constant_s: float) -> float:
    """Fraction of a first-order process's state surviving `dt_s`.

    Expressed as exp(-dt/tau) rather than a fixed per-tick coefficient so
    that the physical behaviour is a property of the machine, not of
    SAMPLE_INTERVAL_S: halving the sample rate must not halve how fast a
    bearing heats up.
    """
    if time_constant_s <= 0.0 or dt_s <= 0.0:
        return 0.0
    return math.exp(-dt_s / time_constant_s)


class _FirstOrderLag:
    """Low-pass filter standing in for a channel's physical inertia.

    Output is always a convex combination of past inputs, so a lagged load
    factor stays inside [0, 1] whenever its input does -- the profile bounds
    and every anomaly band therefore hold unchanged.
    """

    def __init__(self, time_constant_s: float) -> None:
        self._time_constant_s = time_constant_s
        self._value: float | None = None

    def update(self, target: float, dt_s: float) -> float:
        if self._value is None:
            # Prime to the current target rather than to zero: a container
            # that restarts mid-STEADY_STATE should resume a hot machine,
            # not replay a cold start it did not have.
            self._value = target
            return target
        retained = _decay(dt_s, self._time_constant_s)
        self._value = retained * self._value + (1.0 - retained) * target
        return self._value


class _CorrelatedNoise:
    """Ornstein-Uhlenbeck (AR(1)) noise: band-limited, not white.

    The stationary distribution is exactly N(0, std), identical to the
    independent Gaussian this replaces, so nothing about a channel's range
    changes. What changes is that consecutive samples are correlated with
    coefficient exp(-dt/tau), which is the difference between a line and a
    hairband on a chart.
    """

    def __init__(self, std: float, time_constant_s: float, rng: random.Random) -> None:
        self._std = std
        self._time_constant_s = time_constant_s
        self._rng = rng
        # Start from the stationary distribution so the first samples are
        # statistically indistinguishable from the thousandth.
        self._value = rng.gauss(0.0, std)

    def update(self, dt_s: float) -> float:
        retained = _decay(dt_s, self._time_constant_s)
        # sqrt(1 - retained^2) is precisely the innovation scale that holds
        # the stationary variance at std^2 for any dt.
        innovation = self._std * math.sqrt(max(0.0, 1.0 - retained * retained))
        self._value = retained * self._value + self._rng.gauss(0.0, innovation)
        return self._value


class SensorSimulator:
    """
    One sensor channel: base + trend + noise.

    base   - linear interpolation from the channel's idle reading to its
             full-load reading, where the full-load endpoint carries this
             unit's fixed calibration bias (see TURBINE_BIAS_FRACTION: two
             turbines read alike at rest and differ under load). The load
             factor is passed through a first-order lag first, so the
             channel approaches its new value at its own physical pace: a
             gearbox bearing keeps warming for minutes after RPM has
             settled, which is both correct and what puts a gentle rise
             into a STEADY_STATE hold instead of a flat line.
    trend  - a bounded random walk standing in for slow sensor drift and
             thermal soak; capped at one hour's worth of drift so a
             long-running container never wanders out of physical range
    noise  - zero-mean Gaussian with a per-family correlation time, scaled
             down at idle where there is little mechanical excitation.
             Correlated rather than white: the amplitude is unchanged, but
             successive readings now move together the way a real
             instrument's do.
    """

    def __init__(self, profile: SensorProfile, rng: random.Random) -> None:
        self._profile = profile
        self._rng = rng
        bias = rng.uniform(-TURBINE_BIAS_FRACTION, TURBINE_BIAS_FRACTION)
        self._biased_load_value = profile.load_value * (1.0 + bias)
        self._drift = 0.0
        self._drift_limit = abs(profile.drift_per_hour)
        self._load_lag = _FirstOrderLag(profile.response_time_s)
        self._noise = _CorrelatedNoise(profile.noise_std, profile.noise_correlation_s, rng)

    @property
    def measurement(self) -> str:
        return self._profile.measurement

    def _advance_drift(self, dt_s: float) -> None:
        step = self._profile.drift_per_hour * (dt_s / SECONDS_PER_HOUR)
        self._drift += self._rng.uniform(-step, step)
        self._drift = min(self._drift_limit, max(-self._drift_limit, self._drift))

    def sample(self, load_factor: float, dt_s: float) -> float:
        """Produce the next reading and advance this channel's internal state."""
        self._advance_drift(dt_s)
        lagged_load = self._load_lag.update(load_factor, dt_s)
        idle = self._profile.idle_value
        base = idle + (self._biased_load_value - idle) * lagged_load
        # Noise is scaled by the lagged load for the same reason the base is:
        # a machine that has not spun up yet is not yet shaking.
        noise_scale = IDLE_NOISE_FRACTION + (1.0 - IDLE_NOISE_FRACTION) * lagged_load
        value = base + self._drift + self._noise.update(dt_s) * noise_scale
        return min(self._profile.max_value, max(self._profile.min_value, value))


class TurbineSimulator:
    """Manages all 61 sensor channels for a single turbine."""

    def __init__(
        self,
        customer_id: str,
        turbine_id: str,
        timings: StateMachineTimings,
        seed: int | None = None,
    ) -> None:
        self.customer_id = customer_id
        self.turbine_id = turbine_id
        # Seed derived from identity (not from os time) so a restarted
        # container resumes the same per-unit character instead of becoming
        # a different-looking machine mid-stream.
        resolved_seed = seed if seed is not None else self._seed_from_identity()
        rng = random.Random(resolved_seed)
        self._sensors = [SensorSimulator(profile, rng) for profile in SENSOR_PROFILES]
        # Stagger turbines around the cycle so a fleet is never uniformly
        # idle or uniformly at full load, which would make dashboards and
        # correlation rules look artificial.
        offset = rng.uniform(0.0, timings.cycle_s)
        self._state_machine = OperatingStateMachine(timings, start_offset_s=offset)
        self._last_elapsed_s = 0.0

    def _seed_from_identity(self) -> int:
        # zlib.crc32 rather than hash(): Python randomises str hashing per
        # process, which would make restarts non-reproducible.
        import zlib

        return zlib.crc32(f"{self.customer_id}:{self.turbine_id}".encode())

    @property
    def sensor_count(self) -> int:
        return len(self._sensors)

    def sample(self, elapsed_s: float) -> tuple[OperatingState, dict[str, float]]:
        """Generate one full 61-channel reading at `elapsed_s` since start."""
        dt_s = max(0.0, elapsed_s - self._last_elapsed_s)
        self._last_elapsed_s = elapsed_s
        state, load_factor = self._state_machine.state_at(elapsed_s)
        metrics = {
            sensor.measurement: round(sensor.sample(load_factor, dt_s), 4)
            for sensor in self._sensors
        }
        return state, metrics


def delivery_report(err, msg) -> None:
    if err is not None:
        log.error("Kafka delivery failed", extra={"key": msg.key(), "error": str(err)})
    # else: successful delivery is high-volume and not logged per-message


def build_producer() -> Producer:
    """Producer tuned for reliability over raw throughput: acks=all with
    idempotence, so a retry cannot silently reorder or duplicate a row."""
    return Producer(
        {
            "bootstrap.servers": Config.KAFKA_BOOTSTRAP_SERVERS,
            "acks": "all",
            "enable.idempotence": True,
            "retries": 2147483647,
            "delivery.timeout.ms": 120000,
            "retry.backoff.ms": 500,
            "linger.ms": 20,
            "batch.size": 65536,
            "compression.type": "lz4",
            "max.in.flight.requests.per.connection": 5,
        }
    )


def build_payload(
    simulator: TurbineSimulator, seq_no: int, elapsed_s: float, event_time_ms: int
) -> dict:
    """Assemble one Kafka message body, including the additive
    `operating_state` field."""
    state, metrics = simulator.sample(elapsed_s)
    return {
        "message_id": str(uuid.uuid4()),
        "customer_id": simulator.customer_id,
        "turbine_id": simulator.turbine_id,
        "seq_no": seq_no,
        "event_time_ms": event_time_ms,
        "operating_state": str(state),
        "metrics": metrics,
    }


class GracefulShutdown:
    """Lets Ctrl+C / SIGTERM flush pending Kafka messages before exiting."""

    def __init__(self) -> None:
        self.shutdown = False
        signal.signal(signal.SIGINT, self._handle)
        signal.signal(signal.SIGTERM, self._handle)

    def _handle(self, signum: int, frame: FrameType | None) -> None:
        log.info("Shutdown signal received, finishing current tick and flushing...")
        self.shutdown = True


def run_generator() -> None:
    health = start_health_server(Config.HEALTH_CHECK_PORT, "synthetic-producer")
    health.set_check("simulator_ready", False, "not yet initialised")
    health.set_check("kafka_reachable", False, "not yet attempted")

    timings = StateMachineTimings.from_config()
    simulator = TurbineSimulator(Config.CUSTOMER_ID, Config.TURBINE_ID, timings)
    health.set_check("simulator_ready", True, f"{simulator.sensor_count} channels")

    producer = build_producer()
    shutdown = GracefulShutdown()
    health.set_ready(True)

    started_monotonic = time.monotonic()
    base_wallclock_ms = int(time.time() * 1000)
    interval_s = Config.SAMPLE_INTERVAL_S
    # Absolute tick schedule rather than "sleep(interval) at the end of the
    # loop": the latter adds each iteration's own work to every period, so
    # the real cadence is always slower than configured and wanders with
    # broker latency. Grafana draws the gaps that produces as visible steps.
    next_tick_monotonic = started_monotonic
    seq_no = 0
    consecutive_produce_failures = 0

    log.info(
        "Starting synthetic generator",
        extra={
            "topic": Config.KAFKA_TOPIC,
            "customer": Config.CUSTOMER_ID,
            "turbine": Config.TURBINE_ID,
            "channels": simulator.sensor_count,
            "sample_interval_s": Config.SAMPLE_INTERVAL_S,
            "cycle_s": timings.cycle_s,
        },
    )

    while not shutdown.shutdown:
        elapsed_s = time.monotonic() - started_monotonic
        event_time_ms = base_wallclock_ms + int(elapsed_s * 1000)
        payload = build_payload(simulator, seq_no, elapsed_s, event_time_ms)

        try:
            producer.produce(
                topic=Config.KAFKA_TOPIC,
                key=f"{Config.CUSTOMER_ID}:{Config.TURBINE_ID}".encode(),
                value=json.dumps(payload).encode("utf-8"),
                callback=delivery_report,
            )
            consecutive_produce_failures = 0
            health.set_check("kafka_reachable", True, "producing")
        except BufferError:
            # Local producer queue full -- broker likely unreachable/slow.
            # Poll to service delivery callbacks and retry rather than
            # dropping the sample.
            log.warning("Producer queue full, backing off before retry")
            producer.poll(1.0)
            continue
        except Exception as exc:  # broker down, DNS failure, etc.
            consecutive_produce_failures += 1
            backoff_s = min(30.0, 1.0 * (2 ** min(consecutive_produce_failures, 5)))
            log.error(
                "Produce failed, retrying with backoff",
                extra={
                    "error": str(exc),
                    "backoff_s": backoff_s,
                    "consecutive_failures": consecutive_produce_failures,
                },
            )
            health.set_check("kafka_reachable", False, str(exc))
            time.sleep(backoff_s)
            continue

        producer.poll(0)  # serve delivery callbacks without blocking
        seq_no += 1
        if seq_no % Config.PRODUCE_LOG_EVERY_N == 0:
            log.info(
                "Produced telemetry",
                extra={
                    "messages": seq_no,
                    "state": payload["operating_state"],
                    "turbine": Config.TURBINE_ID,
                    "customer": Config.CUSTOMER_ID,
                },
            )

        next_tick_monotonic += interval_s
        sleep_s = next_tick_monotonic - time.monotonic()
        if sleep_s > 0:
            time.sleep(sleep_s)
        else:
            # Fell behind (slow broker, or a retry backoff above). Resync to
            # now instead of firing a catch-up burst: a burst would compress
            # several samples into one instant and put a vertical segment in
            # every chart.
            next_tick_monotonic = time.monotonic()

    log.info("Flushing remaining messages before exit...")
    producer.flush(30)
    log.info("Generator stopped cleanly", extra={"total_messages_sent": seq_no})


if __name__ == "__main__":
    try:
        run_generator()
    except Exception:
        log.exception("Synthetic producer crashed")
        sys.exit(1)
