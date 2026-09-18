"""Read-only anomaly-detection analytics service for the turbine copilot.

Implements the "existing anomaly results" MVP item from the copilot
architecture plan: a *separate, versioned* analytics service that returns
structured evidence objects (score, severity, contributing sensors, model
version) for the LLM to cite — never a raw telemetry dump the model is asked
to eyeball itself.

Model choice: per-subsystem multivariate Isolation Forest (scikit-learn).
This is the standard unsupervised anomaly-detection algorithm for unlabeled,
correlated multivariate sensor data — no labeled fault examples exist for
this synthetic rig, an autoencoder/deep model would need GPU training infra
this deployment doesn't have, and Isolation Forest is robust to the exact
kind of correlated vibration/temperature/pressure features each subsystem
groups together. Trained per (device, subsystem) pair, in-process, on a
rolling telemetry baseline pulled through the same bounded tb_tools path
used elsewhere in the copilot (never an unbounded query).

Caveat surfaced to the caller, not hidden: the per-feature "contribution"
is a z-score-based heuristic (how many baseline standard deviations each
sensor sits from its own mean), not a true SHAP/feature-attribution value.
It is good enough to say *which* sensor is driving an anomaly, not to make
a precise quantitative claim about it.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
from sklearn.ensemble import IsolationForest

try:
    from app.copilot_backend.thingsboard_tools import (
        get_telemetry_range,
        get_latest_telemetry,
        ToolError,
        DEFAULT_MAX_POINTS,
    )
except ImportError:
    from thingsboard_tools import get_telemetry_range, get_latest_telemetry, ToolError, DEFAULT_MAX_POINTS

try:
    from app.tools.subsystem_registry import SUBSYSTEMS, Subsystem
except ImportError:
    from tools.subsystem_registry import SUBSYSTEMS, Subsystem

logger = logging.getLogger("anomaly_service")

MODEL_NAME = "isolation-forest-subsystem-baseline"
MODEL_VERSION = "1.0.0"

# How far back to pull the training baseline, and how long a trained model
# stays valid before being retrained on fresh data.
TRAINING_WINDOW_MS = 24 * 60 * 60 * 1000
RETRAIN_INTERVAL_MS = 6 * 60 * 60 * 1000
MIN_TRAINING_SAMPLES = 30
# ThingsBoard's own aggregation endpoint rejects a request whose computed
# interval count is too high (confirmed live: 2000 intervals over 24h was
# refused with HTTP 400 "exceeds the system's limit"). Match the same bound
# already proven to work for get_telemetry_range elsewhere in this backend.
TRAINING_MAX_POINTS = DEFAULT_MAX_POINTS
# Synthetic rig publishes ~1 Hz; bucket timestamps to this resolution so
# per-key series (fetched independently) can be joined into aligned rows.
ALIGNMENT_BUCKET_MS = 1000

SEVERITY_HIGH = 0.95
SEVERITY_MEDIUM = 0.80

# How many subsystems to return when the caller doesn't name one (a fleet
# scan is capped, same bounding discipline as every other tool here).
MAX_SCAN_RESULTS = 3


class AnomalyServiceError(Exception):
    """Raised when a result cannot be produced (insufficient data, bad component_id, etc.)."""


@dataclass
class _TrainedModel:
    model: IsolationForest
    feature_keys: list[str]
    train_mean: np.ndarray
    train_std: np.ndarray
    train_scores: np.ndarray
    trained_at_ms: int
    trained_through_ms: int
    n_samples: int


# Process-local cache: (device_id, asset_id) -> _TrainedModel. Acceptable to
# lose on container restart (MVP scope) — the next request just retrains.
_MODEL_CACHE: dict[tuple[str, str], _TrainedModel] = {}


def _resolve_subsystem(component_id: str) -> Subsystem:
    """Match a user/model-supplied component_id against the static registry.

    Accepts a subsystem name (case-insensitive, exact or substring), a
    mesh_id, or an asset_id — the model rarely knows the exact spelling.
    """
    needle = component_id.strip().lower()
    if not needle:
        raise AnomalyServiceError("component_id must not be empty")

    for subsystem in SUBSYSTEMS:
        if needle == subsystem.asset_id.lower() or needle == subsystem.mesh_id.lower():
            return subsystem

    exact = [s for s in SUBSYSTEMS if s.name.lower() == needle]
    if exact:
        return exact[0]

    partial = [s for s in SUBSYSTEMS if needle in s.name.lower()]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        names = ", ".join(s.name for s in partial)
        raise AnomalyServiceError(
            f"component_id '{component_id}' matches multiple subsystems ({names}); "
            "be more specific."
        )

    known = ", ".join(s.name for s in SUBSYSTEMS)
    raise AnomalyServiceError(
        f"component_id '{component_id}' does not match any known subsystem. "
        f"Known subsystems: {known}"
    )


def _align_series(
    range_data: dict[str, list[dict[str, Any]]],
    keys: list[str],
) -> tuple[np.ndarray, list[int]]:
    """Joins independently-fetched per-key time series into aligned rows.

    Buckets each series' timestamps to ALIGNMENT_BUCKET_MS and keeps only
    buckets where every requested key has a value — a simple, dependency-free
    inner join (no pandas in this service's requirements).
    """
    buckets: dict[int, dict[str, float]] = {}
    for key in keys:
        for point in range_data.get(key, []):
            ts = point.get("ts")
            value = point.get("value")
            if ts is None or value is None:
                continue
            try:
                value = float(value)
            except (TypeError, ValueError):
                continue
            bucket = int(ts) // ALIGNMENT_BUCKET_MS
            buckets.setdefault(bucket, {})[key] = value

    complete_buckets = sorted(
        bucket for bucket, row in buckets.items() if all(k in row for k in keys)
    )
    rows = [[buckets[b][k] for k in keys] for b in complete_buckets]
    ts_list = [b * ALIGNMENT_BUCKET_MS for b in complete_buckets]
    return np.array(rows, dtype=float), ts_list


def _train_model(client: object, entity_type: str, entity_id: str, subsystem: Subsystem) -> _TrainedModel:
    feature_keys = [s.key for s in subsystem.scored_sensors]
    if not feature_keys:
        raise AnomalyServiceError(
            f"Subsystem '{subsystem.name}' has no scored sensors to model."
        )

    now_ms = int(time.time() * 1000)
    start_ts = now_ms - TRAINING_WINDOW_MS

    try:
        range_result = get_telemetry_range(
            client,
            entity_type=entity_type,
            entity_id=entity_id,
            keys=feature_keys,
            start_ts=start_ts,
            end_ts=now_ms,
            max_points=TRAINING_MAX_POINTS,
        )
    except ToolError as e:
        raise AnomalyServiceError(f"Could not fetch training baseline: {e}") from e

    X, ts_list = _align_series(range_result["data"], feature_keys)
    if X.shape[0] < MIN_TRAINING_SAMPLES:
        raise AnomalyServiceError(
            f"Insufficient baseline data for subsystem '{subsystem.name}': "
            f"{X.shape[0]} aligned samples (need >= {MIN_TRAINING_SAMPLES}). "
            "The turbine may not have enough recent history yet."
        )

    model = IsolationForest(n_estimators=100, contamination="auto", random_state=42)
    model.fit(X)

    train_mean = X.mean(axis=0)
    train_std = X.std(axis=0)
    train_std[train_std == 0] = 1.0  # avoid div-by-zero for a constant sensor
    train_scores = model.score_samples(X)

    trained = _TrainedModel(
        model=model,
        feature_keys=feature_keys,
        train_mean=train_mean,
        train_std=train_std,
        train_scores=train_scores,
        trained_at_ms=now_ms,
        trained_through_ms=ts_list[-1] if ts_list else now_ms,
        n_samples=X.shape[0],
    )
    _MODEL_CACHE[(entity_id, subsystem.asset_id)] = trained
    logger.info(
        "Trained anomaly model",
        extra={
            "subsystem": subsystem.name,
            "n_samples": trained.n_samples,
            "feature_keys": feature_keys,
        },
    )
    return trained


def _get_or_train_model(client: object, entity_type: str, entity_id: str, subsystem: Subsystem) -> _TrainedModel:
    cache_key = (entity_id, subsystem.asset_id)
    cached = _MODEL_CACHE.get(cache_key)
    now_ms = int(time.time() * 1000)
    if cached and (now_ms - cached.trained_at_ms) < RETRAIN_INTERVAL_MS:
        return cached
    return _train_model(client, entity_type, entity_id, subsystem)


def _score_subsystem(
    client: object,
    entity_type: str,
    entity_id: str,
    asset_id: str,
    subsystem: Subsystem,
) -> dict[str, Any]:
    trained = _get_or_train_model(client, entity_type, entity_id, subsystem)

    try:
        latest = get_latest_telemetry(client, entity_type, entity_id, trained.feature_keys)
    except ToolError as e:
        raise AnomalyServiceError(f"Could not fetch latest telemetry: {e}") from e

    missing = [k for k in trained.feature_keys if k not in latest]
    if missing:
        raise AnomalyServiceError(
            f"Latest telemetry is missing keys {missing} for subsystem '{subsystem.name}'; "
            "cannot score current state."
        )

    x = np.array([[latest[k]["value"] for k in trained.feature_keys]], dtype=float)
    raw_score = trained.model.score_samples(x)[0]

    # sklearn's score_samples: lower = more abnormal, higher = more normal.
    # Anomaly score here = fraction of the training baseline that is MORE
    # normal than this point (i.e. train_scores > raw_score). 0 = as typical
    # as the most typical training sample; 1 = more unusual than every
    # training sample seen.
    anomaly_score = float(np.mean(trained.train_scores > raw_score))

    if anomaly_score >= SEVERITY_HIGH:
        status, severity = "ANOMALOUS", "HIGH"
    elif anomaly_score >= SEVERITY_MEDIUM:
        status, severity = "WARNING", "MEDIUM"
    else:
        status, severity = "NORMAL", None

    z_scores = (x[0] - trained.train_mean) / trained.train_std
    abs_z = np.abs(z_scores)
    total = abs_z.sum()
    contributions = (abs_z / total) if total > 0 else np.zeros_like(abs_z)
    features = sorted(
        (
            {"name": key, "contribution": round(float(contrib), 3), "z_score": round(float(z), 2)}
            for key, contrib, z in zip(trained.feature_keys, contributions, z_scores)
        ),
        key=lambda f: f["contribution"],
        reverse=True,
    )

    newest_ts = max(latest[k]["ts"] for k in trained.feature_keys)

    return {
        "analysisType": "anomaly_detection",
        "assetId": asset_id,
        "componentId": subsystem.name,
        "sensorIds": trained.feature_keys,
        "window": {"startTs": trained.trained_through_ms, "endTs": newest_ts},
        "status": status,
        "score": round(anomaly_score, 3),
        "severity": severity,
        "features": features,
        "model": {
            "name": MODEL_NAME,
            "version": MODEL_VERSION,
            "trainedThrough": datetime.fromtimestamp(
                trained.trained_through_ms / 1000, tz=timezone.utc
            ).isoformat(),
            "trainingSamples": trained.n_samples,
        },
        "qualityFlags": [],
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }


def get_analysis_results(
    client: object,
    entity_type: str,
    entity_id: str,
    asset_id: str,
    component_id: str | None = None,
) -> list[dict[str, Any]]:
    """Returns anomaly-detection evidence object(s) for a turbine.

    If component_id is given, scores that one subsystem. If omitted, scans
    every subsystem and returns the MAX_SCAN_RESULTS most anomalous ones
    (bounded, like every other tool in this backend — never an unbounded
    fleet-wide dump).

    Raises:
        AnomalyServiceError: bad component_id, or insufficient telemetry
            history to train/score any subsystem.
    """
    if component_id:
        subsystem = _resolve_subsystem(component_id)
        return [_score_subsystem(client, entity_type, entity_id, asset_id, subsystem)]

    results: list[dict[str, Any]] = []
    errors: list[str] = []
    for subsystem in SUBSYSTEMS:
        try:
            results.append(_score_subsystem(client, entity_type, entity_id, asset_id, subsystem))
        except AnomalyServiceError as e:
            errors.append(str(e))

    if not results:
        raise AnomalyServiceError(
            "Could not score any subsystem (insufficient telemetry history for all of them): "
            + "; ".join(errors[:3])
        )

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:MAX_SCAN_RESULTS]
