"""Shared Kafka configuration and resilience helpers."""

from __future__ import annotations

from typing import Any, Dict


def build_consumer_config(
    bootstrap_servers: str,
    group_id: str,
    auto_offset_reset: str = "earliest",
    enable_auto_commit: bool = False,
    max_poll_interval_ms: int = 300000,
    extra_config: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Construct standard Kafka consumer configuration dictionary."""
    cfg: Dict[str, Any] = {
        "bootstrap.servers": bootstrap_servers,
        "group.id": group_id,
        "enable.auto.commit": enable_auto_commit,
        "auto.offset.reset": auto_offset_reset,
        "isolation.level": "read_committed",
        "max.poll.interval.ms": max_poll_interval_ms,
    }
    if extra_config:
        cfg.update(extra_config)
    return cfg


def build_producer_config(
    bootstrap_servers: str,
    acks: str = "all",
    extra_config: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Construct standard Kafka producer configuration dictionary."""
    cfg: Dict[str, Any] = {
        "bootstrap.servers": bootstrap_servers,
        "acks": acks,
    }
    if extra_config:
        cfg.update(extra_config)
    return cfg
