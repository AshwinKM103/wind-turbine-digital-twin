"""Unit tests for the synthetic telemetry generator (no Kafka required)."""

import math
import os
import random
import statistics
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kafka_consumer import MEASUREMENTS
from sensor_profiles import PROFILES_BY_MEASUREMENT, SENSOR_PROFILES
from synthetic_producer import (
    STEADY_RIPPLE_AMPLITUDE,
    OperatingState,
    OperatingStateMachine,
    StateMachineTimings,
    TurbineSimulator,
    _CorrelatedNoise,
    build_payload,
)

TIMINGS = StateMachineTimings(idle_s=60.0, ramp_up_s=120.0, steady_state_s=600.0, ramp_down_s=90.0)


@pytest.fixture
def simulator():
    return TurbineSimulator("customer1", "turbine01", TIMINGS)


class TestSensorProfiles:
    def test_profiles_match_consumer_measurement_list(self):
        """The generator must emit exactly the channels the consumer writes;
        a mismatch would silently null out columns in IoTDB."""
        consumer_sensors = [m for m in MEASUREMENTS if m != "seq_no"]
        assert [p.measurement for p in SENSOR_PROFILES] == consumer_sensors

    def test_load_value_differs_from_idle_for_every_channel(self):
        for profile in SENSOR_PROFILES:
            assert profile.idle_value != profile.load_value, profile.measurement

    def test_bounds_enclose_idle_and_load_values(self):
        for profile in SENSOR_PROFILES:
            assert profile.min_value <= profile.idle_value <= profile.max_value
            assert profile.min_value <= profile.load_value <= profile.max_value

    def test_value_at_interpolates_between_endpoints(self):
        profile = PROFILES_BY_MEASUREMENT["TURBINE_SPEED_RPM"]
        assert profile.value_at(0.0) == pytest.approx(profile.idle_value)
        assert profile.value_at(1.0) == pytest.approx(profile.load_value)
        midpoint = (profile.idle_value + profile.load_value) / 2
        assert profile.value_at(0.5) == pytest.approx(midpoint)


class TestOperatingStateMachine:
    @pytest.mark.parametrize(
        "elapsed_s,expected_state",
        [
            (0.0, OperatingState.IDLE),
            (59.0, OperatingState.IDLE),
            (61.0, OperatingState.RAMP_UP),
            (179.0, OperatingState.RAMP_UP),
            (181.0, OperatingState.STEADY_STATE),
            (779.0, OperatingState.STEADY_STATE),
            (781.0, OperatingState.RAMP_DOWN),
            (869.0, OperatingState.RAMP_DOWN),
        ],
    )
    def test_state_sequence(self, elapsed_s, expected_state):
        machine = OperatingStateMachine(TIMINGS)
        state, _ = machine.state_at(elapsed_s)
        assert state == expected_state

    def test_cycle_repeats(self):
        machine = OperatingStateMachine(TIMINGS)
        first, first_load = machine.state_at(30.0)
        second, second_load = machine.state_at(30.0 + TIMINGS.cycle_s)
        assert first == second
        assert first_load == pytest.approx(second_load)

    def test_load_factor_is_zero_at_idle_and_near_one_at_steady(self):
        machine = OperatingStateMachine(TIMINGS)
        assert machine.state_at(10.0)[1] == 0.0
        # STEADY_STATE breathes rather than sitting at a dead 1.0, but only
        # downward and only by STEADY_RIPPLE_AMPLITUDE.
        steady_load = machine.state_at(400.0)[1]
        assert 1.0 - STEADY_RIPPLE_AMPLITUDE <= steady_load <= 1.0

    def test_steady_state_begins_and_ends_at_full_load(self):
        """The ripple must vanish at both ends of the window, or the joins
        with RAMP_UP and RAMP_DOWN become steps."""
        machine = OperatingStateMachine(TIMINGS)
        steady_start = TIMINGS.idle_s + TIMINGS.ramp_up_s
        steady_end = steady_start + TIMINGS.steady_state_s
        assert machine.state_at(steady_start)[1] == pytest.approx(1.0)
        assert machine.state_at(steady_end - 1e-6)[1] == pytest.approx(1.0, abs=1e-6)

    def test_load_factor_has_no_jump_at_any_state_transition(self):
        """Sample either side of every boundary: a discontinuity here is
        what draws a vertical segment on a Grafana chart."""
        machine = OperatingStateMachine(TIMINGS)
        boundaries = [
            TIMINGS.idle_s,
            TIMINGS.idle_s + TIMINGS.ramp_up_s,
            TIMINGS.idle_s + TIMINGS.ramp_up_s + TIMINGS.steady_state_s,
            TIMINGS.cycle_s,
        ]
        for boundary in boundaries:
            before = machine.state_at(boundary - 0.01)[1]
            after = machine.state_at(boundary + 0.01)[1]
            assert before == pytest.approx(after, abs=1e-3), f"jump at t={boundary}"

    def test_load_factor_stays_in_unit_interval_across_a_full_cycle(self):
        machine = OperatingStateMachine(TIMINGS)
        for tick in range(int(TIMINGS.cycle_s) + 1):
            _, load = machine.state_at(float(tick))
            assert 0.0 <= load <= 1.0

    def test_ramp_up_is_monotonic(self):
        machine = OperatingStateMachine(TIMINGS)
        loads = [machine.state_at(60.0 + t)[1] for t in range(0, 121, 10)]
        assert loads == sorted(loads)

    def test_rejects_non_positive_duration(self):
        with pytest.raises(ValueError, match="ramp_up_s must be > 0"):
            StateMachineTimings(idle_s=1.0, ramp_up_s=0.0, steady_state_s=1.0, ramp_down_s=1.0)


class TestTurbineSimulator:
    def test_emits_every_sensor_channel(self, simulator):
        _, metrics = simulator.sample(0.0)
        assert set(metrics) == {p.measurement for p in SENSOR_PROFILES}
        assert len(metrics) == 61

    def test_all_values_within_profile_bounds(self, simulator):
        for tick in range(0, 900, 3):
            _, metrics = simulator.sample(float(tick))
            for name, value in metrics.items():
                profile = PROFILES_BY_MEASUREMENT[name]
                assert profile.min_value <= value <= profile.max_value, f"{name}={value}"

    def test_rpm_rises_from_idle_to_steady_state(self, simulator):
        # Sample the same simulator across a full cycle and compare the
        # RPM it reports while idle against the RPM at full load.
        by_state = {}
        for tick in range(int(TIMINGS.cycle_s)):
            state, metrics = simulator.sample(float(tick))
            by_state.setdefault(state, []).append(metrics["TURBINE_SPEED_RPM"])
        idle_max = max(by_state[OperatingState.IDLE])
        steady_min = min(by_state[OperatingState.STEADY_STATE])
        assert idle_max < steady_min

    def test_correlated_channels_rise_together(self, simulator):
        """Torque, bearing temperature and vibration must track RPM -- an
        uncorrelated fleet would make the anomaly rules meaningless."""
        idle_sample = steady_sample = None
        for tick in range(int(TIMINGS.cycle_s)):
            state, metrics = simulator.sample(float(tick))
            if state == OperatingState.IDLE and idle_sample is None:
                idle_sample = metrics
            if state == OperatingState.STEADY_STATE:
                steady_sample = metrics
        for channel in ("TURBINE_SPEED_RPM", "GB_TRQ", "TT_109A", "XT_600"):
            assert steady_sample[channel] > idle_sample[channel], channel

    def test_two_turbines_produce_different_values(self):
        first = TurbineSimulator("customer1", "turbine01", TIMINGS)
        second = TurbineSimulator("customer1", "turbine02", TIMINGS)
        _, first_metrics = first.sample(300.0)
        _, second_metrics = second.sample(300.0)
        assert first_metrics != second_metrics

    def test_same_identity_is_reproducible_across_instances(self):
        """A restarted container must resume the same per-unit character
        rather than becoming a different-looking machine mid-stream."""
        first = TurbineSimulator("customer2", "turbine03", TIMINGS)
        second = TurbineSimulator("customer2", "turbine03", TIMINGS)
        assert first.sample(120.0) == second.sample(120.0)

    def test_explicit_seed_overrides_identity_seed(self):
        first = TurbineSimulator("customer1", "turbine01", TIMINGS, seed=7)
        second = TurbineSimulator("customer3", "turbine09", TIMINGS, seed=7)
        assert first.sample(50.0)[1] == second.sample(50.0)[1]


def _roughness(values):
    """Mean absolute step between consecutive samples, in units of the
    series' own standard deviation. Scale-free, so one threshold works for
    every channel. Independent Gaussian samples score ~1.41; a smooth line
    scores near 0. This is the number that was making charts look
    pixelated."""
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    if variance == 0:
        return 0.0
    steps = [abs(b - a) for a, b in zip(values, values[1:])]
    return (sum(steps) / len(steps)) / math.sqrt(variance)


class TestCorrelatedNoise:
    """The noise model may change a trace's shape but must not change its
    range -- sensor_profiles derives every channel's bounds, and
    anomaly_thresholds.json its bands, from noise_std."""

    def test_preserves_the_requested_standard_deviation(self):
        noise = _CorrelatedNoise(std=2.0, time_constant_s=5.0, rng=random.Random(1))
        samples = [noise.update(1.0) for _ in range(20000)]
        assert statistics.pstdev(samples) == pytest.approx(2.0, rel=0.05)
        assert statistics.fmean(samples) == pytest.approx(0.0, abs=0.15)

    def test_successive_samples_are_correlated(self):
        noise = _CorrelatedNoise(std=1.0, time_constant_s=10.0, rng=random.Random(2))
        samples = [noise.update(1.0) for _ in range(20000)]
        # exp(-1/10) = 0.905 is the correlation the model promises.
        lag1 = sum(a * b for a, b in zip(samples, samples[1:])) / sum(s * s for s in samples)
        assert lag1 == pytest.approx(math.exp(-0.1), abs=0.05)

    def test_correlation_is_a_function_of_time_not_of_sample_rate(self):
        """Two generators sampling the same machine at different rates must
        describe the same physical noise, or SAMPLE_INTERVAL_S silently
        becomes a modelling parameter."""
        fast = _CorrelatedNoise(std=1.0, time_constant_s=20.0, rng=random.Random(3))
        slow = _CorrelatedNoise(std=1.0, time_constant_s=20.0, rng=random.Random(3))
        fast_samples = [fast.update(0.5) for _ in range(40000)][::2]
        slow_samples = [slow.update(1.0) for _ in range(20000)]
        assert statistics.pstdev(fast_samples) == pytest.approx(
            statistics.pstdev(slow_samples), rel=0.05
        )


class TestTraceSmoothness:
    """Regression cover for the reported symptom: charts drawn as a hairy
    band rather than a line."""

    @pytest.mark.parametrize(
        "channel", ["TURBINE_SPEED_RPM", "TT_109A", "XT_600", "PT_109A", "GB_TRQ"]
    )
    def test_steady_state_trace_is_smooth(self, simulator, channel):
        values = []
        for tick in range(int(TIMINGS.cycle_s)):
            state, metrics = simulator.sample(float(tick))
            if state == OperatingState.STEADY_STATE:
                values.append(metrics[channel])
        assert len(values) > 100
        assert _roughness(values) < 0.6, f"{channel} still looks like white noise"

    def test_state_transitions_are_no_jumpier_than_the_rest_of_the_cycle(self, simulator):
        """A state change is a label change, not a physical event. Samples
        taken across a boundary must therefore step no further than samples
        taken anywhere else -- which is the definition of "no discontinuity"
        that does not smuggle in an assumption about noise amplitude."""
        boundaries = [
            TIMINGS.idle_s,
            TIMINGS.idle_s + TIMINGS.ramp_up_s,
            TIMINGS.idle_s + TIMINGS.ramp_up_s + TIMINGS.steady_state_s,
        ]

        def near_boundary(tick):
            return any(abs(tick - b) <= 2 for b in boundaries)

        previous = None
        at_boundary = {}
        elsewhere = {}
        for tick in range(int(TIMINGS.cycle_s)):
            _, metrics = simulator.sample(float(tick))
            if previous is not None:
                bucket = at_boundary if near_boundary(tick) else elsewhere
                for name, value in metrics.items():
                    step = abs(value - previous[name])
                    bucket[name] = max(bucket.get(name, 0.0), step)
            previous = metrics

        for name, boundary_step in at_boundary.items():
            assert boundary_step <= elsewhere[name] * 1.5, (
                f"{name} steps {boundary_step:.3f} across a state boundary but at "
                f"most {elsewhere[name]:.3f} elsewhere -- transition is discontinuous"
            )

    def test_a_restarted_turbine_resumes_hot_rather_than_cold(self):
        """Channels carry physical lag, so a container restarting mid-load
        must not replay a cold start it never had -- that artefact would
        read as a real fault on the dashboard."""
        fresh = TurbineSimulator("customer1", "turbine01", TIMINGS)
        # Find a tick this turbine spends at full load, then start a brand
        # new simulator directly at it.
        steady_tick = next(
            tick
            for tick in range(int(TIMINGS.cycle_s))
            if fresh.sample(float(tick))[0] == OperatingState.STEADY_STATE
        )
        restarted = TurbineSimulator("customer1", "turbine01", TIMINGS)
        _, metrics = restarted.sample(float(steady_tick))
        profile = PROFILES_BY_MEASUREMENT["TT_109A"]
        assert metrics["TT_109A"] > 0.9 * profile.load_value


class TestBuildPayload:
    def test_payload_has_the_fields_the_consumer_requires(self, simulator):
        payload = build_payload(simulator, seq_no=3, elapsed_s=10.0, event_time_ms=1725600000000)
        for field in ("message_id", "customer_id", "turbine_id", "seq_no", "event_time_ms", "metrics"):
            assert field in payload
        assert payload["customer_id"] == "customer1"
        assert payload["turbine_id"] == "turbine01"
        assert payload["seq_no"] == 3
        assert payload["event_time_ms"] == 1725600000000

    def test_payload_passes_consumer_validation(self, simulator):
        from kafka_consumer import device_path_for, validate_payload

        payload = build_payload(simulator, seq_no=0, elapsed_s=0.0, event_time_ms=1)
        validate_payload(payload)  # must not raise
        assert device_path_for(payload).endswith("customer1.site1.turbine01")

    def test_operating_state_is_a_known_state(self, simulator):
        payload = build_payload(simulator, seq_no=0, elapsed_s=400.0, event_time_ms=1)
        assert payload["operating_state"] in {str(s) for s in OperatingState}

    def test_message_ids_are_unique(self, simulator):
        ids = {
            build_payload(simulator, seq_no=i, elapsed_s=float(i), event_time_ms=i)["message_id"]
            for i in range(50)
        }
        assert len(ids) == 50
