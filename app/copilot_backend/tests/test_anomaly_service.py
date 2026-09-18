"""Tests for the Isolation Forest anomaly-detection analytics service.

Verifies:
- component_id resolution against the subsystem registry (name/mesh_id/asset_id)
- insufficient-baseline-data is a clear error, not a crash or a fabricated score
- a clearly-normal reading scores as NORMAL and a clearly-outlying reading as ANOMALOUS
- the unscoped fleet scan is bounded (MAX_SCAN_RESULTS)
- every result carries model name/version/trainedThrough (evidence, not a bare number)
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from app.copilot_backend import anomaly_service
from app.tools.subsystem_registry import SUBSYSTEMS


GEARBOX = next(s for s in SUBSYSTEMS if s.name == "Gearbox")
GEARBOX_KEYS = [s.key for s in GEARBOX.scored_sensors]


def _make_range_data(keys, n_samples, means, start_ts=0, step_ms=1000, noise=0.05, seed=0):
    """Builds a fake get_telemetry_range()['data'] dict: tight Gaussian baseline."""
    rng = np.random.default_rng(seed)
    data = {k: [] for k in keys}
    for i in range(n_samples):
        ts = start_ts + i * step_ms
        for k in keys:
            value = float(means[k] + rng.normal(0, noise * max(abs(means[k]), 1.0)))
            data[k].append({"ts": ts, "value": value})
    return data


@pytest.fixture(autouse=True)
def _clear_model_cache():
    anomaly_service._MODEL_CACHE.clear()
    yield
    anomaly_service._MODEL_CACHE.clear()


class TestResolveSubsystem:
    def test_should_match_by_exact_name(self):
        result = anomaly_service._resolve_subsystem("Gearbox")
        assert result.name == "Gearbox"

    def test_should_match_case_insensitively(self):
        result = anomaly_service._resolve_subsystem("GEARBOX")
        assert result.name == "Gearbox"

    def test_should_match_by_mesh_id(self):
        result = anomaly_service._resolve_subsystem("Gearbox.001")
        assert result.name == "Gearbox"

    def test_should_match_by_asset_id(self):
        result = anomaly_service._resolve_subsystem(GEARBOX.asset_id)
        assert result.name == "Gearbox"

    def test_should_raise_for_unknown_component(self):
        with pytest.raises(anomaly_service.AnomalyServiceError):
            anomaly_service._resolve_subsystem("Nonexistent Component XYZ")

    def test_should_raise_for_empty_component(self):
        with pytest.raises(anomaly_service.AnomalyServiceError):
            anomaly_service._resolve_subsystem("")


class TestGetAnalysisResults:
    def test_should_raise_on_insufficient_training_data(self):
        client = MagicMock()
        means = {k: 10.0 for k in GEARBOX_KEYS}
        sparse_data = _make_range_data(GEARBOX_KEYS, n_samples=5, means=means)

        with patch(
            "app.copilot_backend.anomaly_service.get_telemetry_range",
            return_value={"data": sparse_data, "truncated": False, "interval_ms": 0},
        ):
            with pytest.raises(anomaly_service.AnomalyServiceError, match="Insufficient"):
                anomaly_service.get_analysis_results(
                    client, "DEVICE", "device-1", "boreas", component_id="Gearbox"
                )

    def test_should_score_a_typical_reading_as_normal(self):
        client = MagicMock()
        means = {k: 4.5 for k in GEARBOX_KEYS}
        baseline = _make_range_data(GEARBOX_KEYS, n_samples=200, means=means, noise=0.02)
        latest = {k: {"value": means[k], "ts": 999999} for k in GEARBOX_KEYS}

        with patch(
            "app.copilot_backend.anomaly_service.get_telemetry_range",
            return_value={"data": baseline, "truncated": False, "interval_ms": 0},
        ), patch(
            "app.copilot_backend.anomaly_service.get_latest_telemetry", return_value=latest
        ):
            results = anomaly_service.get_analysis_results(
                client, "DEVICE", "device-1", "boreas", component_id="Gearbox"
            )

        assert len(results) == 1
        result = results[0]
        assert result["status"] == "NORMAL"
        assert result["componentId"] == "Gearbox"
        assert result["model"]["name"] == anomaly_service.MODEL_NAME
        assert result["model"]["version"] == anomaly_service.MODEL_VERSION
        assert "trainedThrough" in result["model"]

    def test_should_score_a_wild_outlier_as_anomalous(self):
        client = MagicMock()
        means = {k: 4.5 for k in GEARBOX_KEYS}
        baseline = _make_range_data(GEARBOX_KEYS, n_samples=200, means=means, noise=0.02)
        # 50x the baseline mean on every scored sensor at once — an unmistakable outlier.
        latest = {k: {"value": means[k] * 50, "ts": 999999} for k in GEARBOX_KEYS}

        with patch(
            "app.copilot_backend.anomaly_service.get_telemetry_range",
            return_value={"data": baseline, "truncated": False, "interval_ms": 0},
        ), patch(
            "app.copilot_backend.anomaly_service.get_latest_telemetry", return_value=latest
        ):
            results = anomaly_service.get_analysis_results(
                client, "DEVICE", "device-1", "boreas", component_id="Gearbox"
            )

        result = results[0]
        assert result["status"] == "ANOMALOUS"
        assert result["severity"] == "HIGH"
        assert result["score"] > anomaly_service.SEVERITY_HIGH
        # Every scored sensor was pushed off-baseline; features should reflect that.
        assert len(result["features"]) == len(GEARBOX_KEYS)
        assert all(f["contribution"] >= 0 for f in result["features"])

    def test_unscoped_scan_should_be_bounded(self):
        client = MagicMock()

        def fake_range(client_, entity_type, entity_id, keys, start_ts, end_ts, **kwargs):
            means = {k: 5.0 for k in keys}
            data = _make_range_data(keys, n_samples=100, means=means, noise=0.02)
            return {"data": data, "truncated": False, "interval_ms": 0}

        def fake_latest(client_, entity_type, entity_id, keys):
            return {k: {"value": 5.0, "ts": 999999} for k in keys}

        with patch(
            "app.copilot_backend.anomaly_service.get_telemetry_range", side_effect=fake_range
        ), patch(
            "app.copilot_backend.anomaly_service.get_latest_telemetry", side_effect=fake_latest
        ):
            results = anomaly_service.get_analysis_results(
                client, "DEVICE", "device-1", "boreas", component_id=None
            )

        assert len(results) <= anomaly_service.MAX_SCAN_RESULTS
        # Results must be sorted most-anomalous first.
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_should_raise_for_unknown_component(self):
        client = MagicMock()
        with pytest.raises(anomaly_service.AnomalyServiceError):
            anomaly_service.get_analysis_results(
                client, "DEVICE", "device-1", "boreas", component_id="Nonexistent Part"
            )
