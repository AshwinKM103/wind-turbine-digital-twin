"""Kafka to IoTDB consumer and batch writer."""

import json
import re
import sys
import time
from collections import OrderedDict

from confluent_kafka import Consumer, Producer, KafkaError
from iotdb.Session import Session
from iotdb.utils.IoTDBConstants import TSDataType
from iotdb.utils.Tablet import Tablet

from config import Config
from infrastructure import configure_logging, start_health_server
from resilience import CircuitBreaker, CircuitBreakerOpenError

log = configure_logging("kafka-consumer")

# Fixed schema ordered to align with IoTDB device template and synthetic producer
MEASUREMENTS = [
    "PT_109A", "PT_110A", "PT_110B", "PT_111B", "PT_111", "PT_112", "PT_162",
    "PT_161", "PT_160", "PT_120", "PT_111C", "PT_153", "PT_163", "PT_150A",
    "PT_150B", "PT_201", "PT_253", "FT_110A", "FT_162", "TT_109A", "TT_110A",
    "TT_110B", "TT_111", "TT_112", "TT_162", "TT_161", "TT_160", "TT_120_R",
    "TT_120", "TT_111C", "TT_111C_R", "DYNO_WATER_O_L", "TT_163", "TT_150A",
    "TT_150B", "ZT_600", "ZT_601", "XT_600", "XT_601", "XT_602", "XT_603",
    "XT_604", "XT_605", "XT_606", "XT_607", "HP_DEMAND", "ACT_POS_FB",
    "GB_TRQ", "PYRO_T", "PYRO_GB", "TURBINE_SPEED_RPM", "RTD_219A",
    "RTD_219B", "RTD_220", "RTD_221", "RTD_200", "RTD_202", "RTD_203",
    "RTD_204", "RTD_205", "RTD_201", "seq_no",
]
DATA_TYPES = [
    TSDataType.FLOAT, TSDataType.FLOAT, TSDataType.FLOAT, TSDataType.FLOAT,
    TSDataType.FLOAT, TSDataType.FLOAT, TSDataType.FLOAT, TSDataType.FLOAT,
    TSDataType.FLOAT, TSDataType.FLOAT, TSDataType.FLOAT, TSDataType.FLOAT,
    TSDataType.FLOAT, TSDataType.FLOAT, TSDataType.FLOAT, TSDataType.FLOAT,
    TSDataType.FLOAT, TSDataType.FLOAT, TSDataType.FLOAT, TSDataType.FLOAT,
    TSDataType.FLOAT, TSDataType.FLOAT, TSDataType.FLOAT, TSDataType.FLOAT,
    TSDataType.FLOAT, TSDataType.FLOAT, TSDataType.FLOAT, TSDataType.FLOAT,
    TSDataType.FLOAT, TSDataType.FLOAT, TSDataType.FLOAT, TSDataType.FLOAT,
    TSDataType.FLOAT, TSDataType.FLOAT, TSDataType.FLOAT, TSDataType.FLOAT,
    TSDataType.FLOAT, TSDataType.FLOAT, TSDataType.FLOAT, TSDataType.FLOAT,
    TSDataType.FLOAT, TSDataType.FLOAT, TSDataType.FLOAT, TSDataType.FLOAT,
    TSDataType.FLOAT, TSDataType.FLOAT, TSDataType.FLOAT, TSDataType.FLOAT,
    # PYRO_T matches IoTDB device template FLOAT definition
    TSDataType.FLOAT, TSDataType.FLOAT, TSDataType.FLOAT, TSDataType.FLOAT,
    TSDataType.FLOAT, TSDataType.FLOAT, TSDataType.FLOAT, TSDataType.FLOAT,
    TSDataType.FLOAT, TSDataType.FLOAT, TSDataType.FLOAT, TSDataType.FLOAT,
    TSDataType.FLOAT, TSDataType.INT32,
]
assert len(MEASUREMENTS) == len(DATA_TYPES) == 62  # 61 sensor channels + seq_no

REQUIRED_PAYLOAD_FIELDS = ("event_time_ms", "customer_id", "turbine_id", "seq_no")

# Validates path node identifiers at trust boundary against path injection
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def build_consumer() -> Consumer:
    """Instantiate configured Kafka consumer with manual commit mode."""
    config = {
        "bootstrap.servers": Config.KAFKA_BOOTSTRAP_SERVERS,
        "group.id": Config.KAFKA_GROUP_ID,
        "enable.auto.commit": False,  # Manual commit after successful storage write
        "auto.offset.reset": "earliest",
        "isolation.level": "read_committed",
        "max.poll.interval.ms": 300000,
    }
    return Consumer(config)


def build_dlq_producer() -> Producer:
    """Instantiate Kafka producer for Dead Letter Queue routing."""
    return Producer({"bootstrap.servers": Config.KAFKA_BOOTSTRAP_SERVERS, "acks": "all"})


def build_iotdb_session(health=None) -> Session:
    """Connect to IoTDB with exponential backoff until successful."""
    attempt = 0
    while True:
        attempt += 1
        try:
            session = Session(Config.IOTDB_HOST, Config.IOTDB_PORT, Config.IOTDB_USER, Config.IOTDB_PASSWORD)
            session.open(False)
            return session
        except Exception as exc:
            backoff_s = min(30.0, 1.0 * (2 ** min(attempt, 5)))
            log.error(
                "IoTDB not reachable at startup, retrying with backoff",
                extra={"attempt": attempt, "backoff_s": backoff_s, "error": str(exc)},
            )
            if health is not None:
                health.set_check("iotdb_connected", False, str(exc))
            time.sleep(backoff_s)


def validate_payload(payload: dict) -> None:
    """Validate incoming Kafka message structure and identifier constraints."""
    if not isinstance(payload, dict):
        raise ValueError(f"payload is not a JSON object: {type(payload).__name__}")
    missing = [f for f in REQUIRED_PAYLOAD_FIELDS if f not in payload]
    if missing:
        raise ValueError(f"payload missing required fields: {missing}")
    if not isinstance(payload.get("metrics"), dict):
        raise ValueError("payload.metrics must be an object")
    if not isinstance(payload["event_time_ms"], (int, float)):
        raise ValueError("payload.event_time_ms must be numeric")
    for field in ("customer_id", "turbine_id"):
        value = payload[field]
        if not isinstance(value, str) or not IDENTIFIER_PATTERN.match(value):
            raise ValueError(f"payload.{field} is not a valid identifier: {value!r}")


_UNQUOTED_NODE_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def quote_path_node(node: str) -> str:
    """Escape and backtick-quote an IoTDB path node if it cannot be unquoted."""
    if not node:
        return node
    if _UNQUOTED_NODE_PATTERN.match(node):
        return node
    escaped = node.replace("`", "``")
    return f"`{escaped}`"


def build_device_path(
    customer_id: str,
    site_id: str,
    turbine_id: str,
    root: str = "root.digitaltwin",
) -> str:
    """Build a fully qualified and escaped IoTDB device path."""
    return (
        f"{root}."
        f"{quote_path_node(customer_id)}."
        f"{quote_path_node(site_id)}."
        f"{quote_path_node(turbine_id)}"
    )


def device_path_for(payload: dict) -> str:
    """Construct fully qualified IoTDB device path from payload attributes."""
    site_id = payload.get("site_id") or Config.SITE_ID
    if not isinstance(site_id, str) or not IDENTIFIER_PATTERN.match(site_id):
        raise ValueError(f"payload.site_id is not a valid identifier: {site_id!r}")
    return build_device_path(
        customer_id=payload["customer_id"],
        site_id=site_id,
        turbine_id=payload["turbine_id"],
        root=Config.DEVICE_PATH_ROOT,
    )


def payload_to_row(payload: dict):
    """Map telemetry payload metrics to schema-aligned row values."""
    metrics = payload.get("metrics", {})
    values = []
    for name in MEASUREMENTS:
        if name == "seq_no":
            values.append(payload.get("seq_no"))
            continue
        raw = metrics.get(name)
        try:
            values.append(float(raw) if raw is not None else None)
        except (TypeError, ValueError):
            values.append(None)
    return int(payload["event_time_ms"]), values


def flush_batch_to_iotdb(
    session: Session, breaker: CircuitBreaker, timestamps, rows, device_path: str
) -> bool:
    """Write tablet batch to IoTDB protected by circuit breaker with retries."""
    tablet = Tablet(device_path, MEASUREMENTS, DATA_TYPES, rows, timestamps)
    for attempt in range(1, Config.IOTDB_WRITE_MAX_RETRIES + 1):
        try:
            breaker.call(session.insert_tablet, tablet)
            return True
        except CircuitBreakerOpenError as exc:
            log.error("IoTDB circuit breaker open, skipping write attempt", extra={"reason": str(exc)})
            return False
        except Exception as exc:
            log.error(
                "IoTDB insert_tablet failed",
                extra={"attempt": attempt, "max_retries": Config.IOTDB_WRITE_MAX_RETRIES, "error": str(exc)},
            )
            if attempt < Config.IOTDB_WRITE_MAX_RETRIES:
                time.sleep(Config.IOTDB_WRITE_BACKOFF_BASE_S * (2 ** (attempt - 1)))
    return False


class BufferedRecord:
    """One validated Kafka message, ready to be written to IoTDB."""

    __slots__ = ("device_path", "timestamp", "row", "raw_message")

    def __init__(self, device_path: str, timestamp: int, row: list, raw_message) -> None:
        """Initialize buffered record with metadata, row values, and raw Kafka message."""
        self.device_path = device_path
        self.timestamp = timestamp
        self.row = row
        self.raw_message = raw_message


def group_by_device(records) -> "OrderedDict[str, list[BufferedRecord]]":
    """Partition buffered records by device path preserving encounter order."""
    groups: "OrderedDict[str, list[BufferedRecord]]" = OrderedDict()
    for record in records:
        groups.setdefault(record.device_path, []).append(record)
    return groups


def send_to_dlq(dlq_producer: Producer, raw_messages, reason: bytes = b"iotdb_write_failed_after_retries"):
    """Route failed or unparseable messages to Dead Letter Queue topic."""
    for msg in raw_messages:
        try:
            dlq_producer.produce(
                topic=Config.DLQ_TOPIC,
                key=msg.key(),
                value=msg.value(),
                headers=[("failure_reason", reason)],
            )
        except Exception as exc:
            log.error("Failed to forward message to DLQ (data loss risk)", extra={"error": str(exc)})
    dlq_producer.flush(10)


def run_consumer():
    """Main consumer loop reading Kafka telemetry and writing batches to IoTDB."""
    health = start_health_server(Config.HEALTH_CHECK_PORT, "kafka-consumer")
    health.set_check("kafka_connected", False, "not yet attempted")
    health.set_check("iotdb_connected", False, "not yet attempted")

    consumer = build_consumer()
    dlq_producer = build_dlq_producer()

    # Blocks until IoTDB is reachable; retries internally with backoff.
    session = build_iotdb_session(health)
    health.set_check("iotdb_connected", True, "session open")

    consumer.subscribe([Config.KAFKA_TOPIC])
    health.set_check("kafka_connected", True, "subscribed")
    health.set_ready(True)

    breaker = CircuitBreaker(
        failure_threshold=Config.CIRCUIT_BREAKER_FAILURE_THRESHOLD,
        reset_timeout_s=Config.CIRCUIT_BREAKER_RESET_TIMEOUT_S,
        name="iotdb",
    )

    log.info(
        "Consumer started",
        extra={
            "topic": Config.KAFKA_TOPIC, "group": Config.KAFKA_GROUP_ID,
            "device_path_root": Config.DEVICE_PATH_ROOT,
            "batch_size": Config.BATCH_SIZE,
        },
    )

    buffer: list[BufferedRecord] = []
    last_flush_time = time.time()
    processed_total = 0

    def flush_current_batch():
        """Flush in-memory buffered records to IoTDB partitioned by device group."""
        nonlocal buffer, last_flush_time, processed_total
        if not buffer:
            return

        groups = group_by_device(buffer)
        written = 0
        for device_path, records in groups.items():
            success = flush_batch_to_iotdb(
                session,
                breaker,
                [r.timestamp for r in records],
                [r.row for r in records],
                device_path,
            )
            if success:
                written += len(records)
                log.debug(
                    "Wrote device group", extra={"device": device_path, "records": len(records)}
                )
            else:
                log.error(
                    "IoTDB write failed, routing device group to DLQ",
                    extra={
                        "device": device_path,
                        "records": len(records),
                        "max_retries": Config.IOTDB_WRITE_MAX_RETRIES,
                    },
                )
                send_to_dlq(dlq_producer, [r.raw_message for r in records])

        health.set_check("iotdb_connected", breaker.state != "OPEN", f"circuit={breaker.state}")
        processed_total += written
        # Commit past batch; failed groups are preserved in DLQ for offline replay
        consumer.commit(message=buffer[-1].raw_message)
        log.info(
            "Processed batch",
            extra={
                "records": len(buffer),
                "written": written,
                "devices": len(groups),
                "processed_total": processed_total,
            },
        )

        buffer = []
        last_flush_time = time.time()

    try:
        while True:
            msg = consumer.poll(1.0)

            batch_full = len(buffer) >= Config.BATCH_SIZE
            batch_timed_out = (
                buffer and (time.time() - last_flush_time) >= Config.BATCH_MAX_WAIT_S
            )

            if msg is not None:
                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        pass
                    else:
                        log.error("Kafka consume error", extra={"error": str(msg.error())})
                        health.set_check("kafka_connected", False, str(msg.error()))
                else:
                    health.set_check("kafka_connected", True, "consuming")
                    try:
                        payload = json.loads(msg.value())
                        validate_payload(payload)
                        device_path = device_path_for(payload)
                        ts, row = payload_to_row(payload)
                        buffer.append(BufferedRecord(device_path, ts, row, msg))
                    except (json.JSONDecodeError, ValueError, KeyError) as exc:
                        # Forward unparseable messages to DLQ and commit offset
                        log.error("Invalid message, sending to DLQ", extra={"error": str(exc)})
                        send_to_dlq(dlq_producer, [msg], reason=b"validation_failed")
                        consumer.commit(msg)

            if buffer and (batch_full or batch_timed_out or msg is None):
                flush_current_batch()

    except KeyboardInterrupt:
        log.info("Shutdown requested, flushing remaining buffer...")
        flush_current_batch()
    finally:
        consumer.close()
        session.close()
        log.info("Consumer stopped cleanly.")


if __name__ == "__main__":
    try:
        run_consumer()
    except Exception:
        log.exception("Consumer crashed")
        sys.exit(1)
