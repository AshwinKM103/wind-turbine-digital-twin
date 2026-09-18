"""
Shared Kafka configuration and resilience helpers.

Provides standard configuration builders for Kafka consumers and producers
with built-in resilience defaults (read_committed, explicit commit control).

The implementation supports:

    - Standardized consumer configuration maps
    - Standardized producer configuration maps
    - Custom override dictionaries

Key classes / functions:

    - build_consumer_config: Construct standard Kafka consumer configuration.
    - build_producer_config: Construct standard Kafka producer configuration.

"""

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
    """
    Construct standard Kafka consumer configuration dictionary.

    Builds an isolated configuration dictionary enforcing read_committed
    isolation and manual offset commits by default.

    Args:
        bootstrap_servers (str): Comma-delimited list of broker host:port addresses.
        group_id (str): Unique consumer group identifier.
        auto_offset_reset (str, optional): Offset reset policy ('earliest' or 'latest'). Defaults to 'earliest'.
        enable_auto_commit (bool, optional): Whether to enable automatic offset commits. Defaults to False.
        max_poll_interval_ms (int, optional): Maximum delay between consumer polls before eviction. Defaults to 300000.
        extra_config (Dict[str, Any] | None, optional): Additional librdkafka configuration overrides. Defaults to None.

    Returns:
        Dict[str, Any]: Configuration dictionary suitable for initializing Confluent Kafka Consumer.

    Example:
        >>> config = build_consumer_config("localhost:9092", "test-group")
        >>> config["group.id"]
        'test-group'

    """
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
    """
    Construct standard Kafka producer configuration dictionary.

    Builds a reliable configuration dictionary enforcing durable write acknowledgments.

    Args:
        bootstrap_servers (str): Comma-delimited list of broker host:port addresses.
        acks (str, optional): Required broker acknowledgments ('all', '1', or '0'). Defaults to 'all'.
        extra_config (Dict[str, Any] | None, optional): Additional librdkafka configuration overrides. Defaults to None.

    Returns:
        Dict[str, Any]: Configuration dictionary suitable for initializing Confluent Kafka Producer.

    Example:
        >>> config = build_producer_config("localhost:9092")
        >>> config["acks"]
        'all'

    """
    cfg: Dict[str, Any] = {
        "bootstrap.servers": bootstrap_servers,
        "acks": acks,
    }
    if extra_config:
        cfg.update(extra_config)
    return cfg

