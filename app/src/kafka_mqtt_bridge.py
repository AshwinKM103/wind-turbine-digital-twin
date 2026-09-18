#!/usr/bin/env python3
"""Bridge turbine telemetry from Kafka to ThingsBoard over MQTT."""

from __future__ import annotations

import json
import logging
import math
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    from kafka import KafkaConsumer
except ImportError:
    logging.error("kafka-python not installed. Run: pip install kafka-python")
    sys.exit(1)

try:
    import paho.mqtt.client as mqtt
except ImportError:
    logging.error("paho-mqtt not installed. Run: pip install paho-mqtt")
    sys.exit(1)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _build_log_handlers() -> tuple[list[logging.Handler], Optional[str]]:
    """Build log handlers. Defer warnings until after basicConfig to avoid silent no-op."""
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    deferred_warning: Optional[str] = None
    log_dir = Path(os.getenv("LOG_DIR", "./logs"))
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_dir / "kafka_mqtt_bridge.log"))
    except OSError as exc:
        deferred_warning = f"file logging disabled ({log_dir}: {exc}); logging to stdout only"
    return handlers, deferred_warning


_LOG_HANDLERS, _DEFERRED_LOG_WARNING = _build_log_handlers()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=_LOG_HANDLERS,
    force=True,
)
logger = logging.getLogger(__name__)

if _DEFERRED_LOG_WARNING:
    logger.warning(_DEFERRED_LOG_WARNING)

# Measurement contract
HEADLINE_MEASUREMENTS: tuple[str, ...] = (
    "TURBINE_SPEED_RPM",
    "GB_TRQ",
    "PYRO_T",
    "PYRO_GB",
    "PT_109A",
    "FT_110A",
    "PT_150A",
    "XT_600",
    "XT_601",
    "XT_604",
    "XT_605",
    "ZT_600",
)

# Generic aliases for fleet/KPI dashboards.
DERIVED_KEYS: dict[str, str] = {
    "rpm": "TURBINE_SPEED_RPM",
    "temperature": "PYRO_GB",
    "vibration": "XT_600",
}

# Shaft power proxy: P = 2*pi/60 * RPM * GB_TRQ (in kW)
_RPM_TO_RAD_PER_S = 2.0 * math.pi / 60.0


def shaft_power_kw(rpm: float, torque_knm: float) -> float:
    """Shaft-power proxy in kW from rotor speed and gearbox torque."""
    return _RPM_TO_RAD_PER_S * rpm * torque_knm


@dataclass
class KafkaConfig:
    """Configuration for Kafka connection and consumer topic."""
    bootstrap_servers: str = field(default_factory=lambda: os.getenv("KAFKA_BOOTSTRAP_SERVERS_INTERNAL", "kafka:29092"))
    topic: str = field(default_factory=lambda: os.getenv("KAFKA_TOPIC", "turbine.telemetry.raw.v1"))
    group_id: str = field(default_factory=lambda: os.getenv("KAFKA_GROUP_ID", "kafka-mqtt-bridge-group"))
    # Read latest offsets on restart to stream live telemetry
    auto_offset_reset: str = "latest"


@dataclass
class MQTTConfig:
    """Configuration for ThingsBoard MQTT broker connection."""
    host: str = field(default_factory=lambda: os.getenv("MQTT_HOST", "thingsboard"))
    port: int = field(default_factory=lambda: int(os.getenv("MQTT_PORT", "1883")))
    keepalive: int = 60
    clean_session: bool = True


@dataclass
class BridgeConfig:
    """Composite configuration for Kafka-to-MQTT bridge runtime."""
    kafka: KafkaConfig = field(default_factory=KafkaConfig)
    mqtt: MQTTConfig = field(default_factory=MQTTConfig)
    batch_size: int = field(default_factory=lambda: int(os.getenv("BATCH_SIZE", "50")))
    batch_max_wait_s: float = field(default_factory=lambda: float(os.getenv("BATCH_MAX_WAIT_S", "5.0")))
    health_check_port: int = field(default_factory=lambda: int(os.getenv("HEALTH_CHECK_PORT", "8003")))
    token_map_path: Path = field(
        default_factory=lambda: Path(os.getenv("TB_DEVICE_TOKEN_MAP", str(REPO_ROOT / "provisioning" / "results" / "device-tokens.json")))
    )


# Metrics
@dataclass
class BridgeMetrics:
    """Metrics tracker for telemetry throughput, errors, and delivery latency."""
    messages_consumed: int = 0
    messages_published: int = 0
    messages_delivered: int = 0
    kafka_errors: int = 0
    mqtt_errors: int = 0
    unknown_devices: int = 0
    mqtt_disconnects: int = 0
    last_message_time: Optional[datetime] = None
    last_publish_time: Optional[datetime] = None
    last_delivery_time: Optional[datetime] = None
    bridge_start_time: datetime = field(default_factory=datetime.now)

    # Maximum elapsed seconds without successful delivery before marking unhealthy
    stall_threshold_s: float = 120.0

    def is_healthy(self) -> bool:
        """Check if telemetry delivery is active within stall threshold."""
        now = datetime.now()
        if self.last_delivery_time is not None:
            return (now - self.last_delivery_time).total_seconds() < self.stall_threshold_s
        return (now - self.bridge_start_time).total_seconds() < 300

    def to_dict(self) -> dict:
        """Serialize current metrics snapshot to dictionary."""
        return {
            "messages_consumed": self.messages_consumed,
            "messages_published": self.messages_published,
            "messages_delivered": self.messages_delivered,
            "kafka_errors": self.kafka_errors,
            "mqtt_errors": self.mqtt_errors,
            "unknown_devices": self.unknown_devices,
            "mqtt_disconnects": self.mqtt_disconnects,
            "last_publish_time": (
                self.last_publish_time.isoformat()
                if self.last_publish_time
                else None
            ),
            "last_delivery_time": (
                self.last_delivery_time.isoformat()
                if self.last_delivery_time
                else None
            ),
            "last_message_time": (
                self.last_message_time.isoformat()
                if self.last_message_time
                else None
            ),
            "bridge_uptime_seconds": (
                datetime.now() - self.bridge_start_time
            ).total_seconds(),
            "is_healthy": self.is_healthy(),
        }


# Device registry
@dataclass(frozen=True)
class DeviceBinding:
    """Everything needed to publish one turbine's telemetry to ThingsBoard."""

    customer_id: str
    site_id: str
    turbine_id: str
    device_name: str
    token: str


class DeviceRegistry:
    """Resolves (customer_id, turbine_id) from Kafka to ThingsBoard device credentials."""

    def __init__(self, bindings: dict[tuple[str, str], DeviceBinding]):
        """Initialize registry with mapping from (customer, turbine) to device binding."""
        self._bindings = bindings

    def __len__(self) -> int:
        return len(self._bindings)

    def resolve(self, customer_id: str, turbine_id: str) -> Optional[DeviceBinding]:
        """Lookup device binding by customer ID and turbine ID."""
        return self._bindings.get((customer_id, turbine_id))

    @classmethod
    def load(cls, token_map_path: Path | str) -> "DeviceRegistry":
        """Build device registry from exported token map."""
        path = Path(token_map_path)
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise FileNotFoundError(
                f"device token map not found at {path}. Generate it with: "
                f"python app/tools/export_device_tokens.py"
            ) from None
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"device token map at {path} is not valid JSON: {exc}"
            ) from exc

        entries = document.get("devices", {})
        bindings: dict[tuple[str, str], DeviceBinding] = {}
        skipped: list[str] = []

        for key, entry in entries.items():
            token = entry.get("token")
            # Fall back to splitting key if identity fields are omitted
            parts = key.split("/")
            customer_id = entry.get("customer_id") or (parts[0] if len(parts) == 3 else None)
            site_id = entry.get("site_id") or (parts[1] if len(parts) == 3 else None)
            turbine_id = entry.get("turbine_id") or (parts[2] if len(parts) == 3 else None)

            if not (token and customer_id and site_id and turbine_id):
                skipped.append(key)
                continue

            bindings[(customer_id, turbine_id)] = DeviceBinding(
                customer_id=customer_id,
                site_id=site_id,
                turbine_id=turbine_id,
                device_name=entry.get(
                    "device_name", f"{customer_id}.{site_id}.{turbine_id}"
                ),
                token=token,
            )

        if skipped:
            logger.warning(
                "%d token map entr(ies) were malformed and skipped: %s",
                len(skipped),
                ", ".join(skipped[:5]) + (" ..." if len(skipped) > 5 else ""),
            )

        if not bindings:
            raise ValueError(
                f"token map at {path} yielded no usable device bindings; "
                f"the bridge would publish nothing"
            )

        logger.info("Device registry loaded: %d turbine(s) bound", len(bindings))
        return cls(bindings)


# ThingsBoard MQTT publisher

TELEMETRY_TOPIC = "v1/devices/me/telemetry"


class ThingsboardDevicePublisher:
    """Manages authenticated MQTT sessions for ThingsBoard device telemetry publishing."""

    def __init__(self, config: MQTTConfig, metrics: BridgeMetrics):
        """Initialize publisher with MQTT connection config and metric counters."""
        self.config = config
        self.metrics = metrics
        self._clients: dict[str, mqtt.Client] = {}
        self._lock = threading.Lock()
        self._last_offline_warn: dict[str, float] = {}

    def _connect_device(self, binding: DeviceBinding) -> Optional[mqtt.Client]:
        """Establish and configure authenticated MQTT client connection for a device."""
        device = binding.device_name
        client = mqtt.Client(
            client_id=f"bridge-{device}",
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        )
        # Set device access token credentials
        client.username_pw_set(binding.token)
        # Reconnect with exponential backoff
        client.reconnect_delay_set(min_delay=1, max_delay=60)
        # Bound message queue to prevent memory growth during broker outages
        client.max_queued_messages_set(1000)

        connect_codes: list[int] = []

        def on_connect(client, userdata, flags, reason_code, properties=None):
            connect_codes.append(int(reason_code.value))
            if not reason_code.is_failure:
                logger.info("MQTT session established for device %s", device)

        def on_disconnect(
            client, userdata, flags, reason_code, properties=None
        ):
            # Track disconnection events for health monitoring
            self.metrics.mqtt_disconnects += 1
            logger.warning(
                "MQTT session for %s dropped by broker (%s); reconnecting",
                device,
                reason_code,
            )

        def on_publish(client, userdata, mid, reason_code=None, properties=None):
            # Record PUBACK delivery confirmation
            self.metrics.messages_delivered += 1
            self.metrics.last_delivery_time = datetime.now()

        client.on_connect = on_connect
        client.on_disconnect = on_disconnect
        client.on_publish = on_publish

        try:
            client.connect(self.config.host, self.config.port, self.config.keepalive)
        except Exception as exc:
            logger.error("MQTT connect failed for %s: %s", device, exc)
            self.metrics.mqtt_errors += 1
            return None

        client.loop_start()

        deadline = time.time() + 5.0
        while not connect_codes and time.time() < deadline:
            time.sleep(0.05)

        if not connect_codes or connect_codes[0] != 0:
            logger.error(
                "MQTT CONNACK %s for device %s (expected 0; is its access "
                "token current?)",
                connect_codes or "timeout",
                device,
            )
            client.loop_stop()
            self.metrics.mqtt_errors += 1
            return None

        return client

    def _client_for(self, binding: DeviceBinding) -> Optional[mqtt.Client]:
        """Retrieve cached active MQTT client or create a new session."""
        with self._lock:
            client = self._clients.get(binding.device_name)
            if client is not None:
                return client
            client = self._connect_device(binding)
            if client is not None:
                self._clients[binding.device_name] = client
            return client

    def publish_telemetry(
        self, binding: DeviceBinding, ts_ms: int, values: dict
    ) -> bool:
        """Publish one timestamped reading for one device."""
        client = self._client_for(binding)
        if client is None:
            now = time.time()
            if now - self._last_offline_warn.get(binding.device_name, 0.0) >= 30.0:
                logger.warning("No MQTT connection for %s; dropping telemetry", binding.device_name)
                self._last_offline_warn[binding.device_name] = now
            return False

        payload = json.dumps({"ts": ts_ms, "values": values})
        try:
            result = client.publish(TELEMETRY_TOPIC, payload, qos=1)
        except Exception as exc:
            logger.error("Publish raised for %s: %s", binding.device_name, exc)
            self.metrics.mqtt_errors += 1
            return False

        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            logger.error("Publish error %s for %s", result.rc, binding.device_name)
            self.metrics.mqtt_errors += 1
            return False

        self.metrics.messages_published += 1
        return True

    def disconnect_all(self) -> None:
        """Stop client loops and disconnect all active MQTT sessions."""
        with self._lock:
            clients = list(self._clients.values())
            self._clients.clear()
        for client in clients:
            try:
                client.loop_stop()
                client.disconnect()
            except Exception as e:
                logger.debug(f"Disconnect error: {e}")

    close = disconnect_all


# Kafka consumer
class TurbineTelemetryConsumer:
    """Consumes serialized turbine telemetry batches from Kafka."""

    def __init__(self, config: KafkaConfig, metrics: BridgeMetrics):
        """Initialize Kafka consumer configuration and metrics reference."""
        self.config = config
        self.metrics = metrics
        self.consumer = None

    def connect(self, retries: int = 5, retry_delay_s: float = 2.0) -> bool:
        """Establish connection to Kafka broker with retry backoff."""
        for attempt in range(retries):
            try:
                self.consumer = KafkaConsumer(
                    self.config.topic,
                    bootstrap_servers=self.config.bootstrap_servers,
                    group_id=self.config.group_id,
                    auto_offset_reset=self.config.auto_offset_reset,
                    value_deserializer=lambda m: json.loads(m.decode("utf-8")),
                    enable_auto_commit=True,
                    max_poll_records=100,
                    session_timeout_ms=10000,
                )
                logger.info(
                    "Connected to Kafka (%s) on attempt %d",
                    self.config.topic,
                    attempt + 1,
                )
                return True
            except Exception as exc:
                logger.warning(
                    "Kafka connection attempt %d/%d failed: %s",
                    attempt + 1,
                    retries,
                    exc,
                )
                time.sleep(retry_delay_s)
        return False

    def consume_batch(self, max_messages: int = 50, timeout_ms: int = 5000) -> list:
        """Poll Kafka for a batch of incoming messages up to max_messages."""
        messages = []
        try:
            poll_result = self.consumer.poll(
                timeout_ms=timeout_ms, max_records=max_messages
            )
            for partition_records in poll_result.values():
                messages.extend(partition_records)
        except Exception as exc:
            logger.error("Error consuming from Kafka: %s", exc)
            self.metrics.kafka_errors += 1
        return messages


# Bridge


def build_telemetry_values(metrics: dict, operating_state: str) -> dict:
    """Assemble the ThingsBoard `values` object for one Kafka reading.

    Includes all raw telemetry channels from `metrics`, plus derived keys,
    shaft power proxy, and operating state.
    """
    values: dict = dict(metrics)

    for alias, source in DERIVED_KEYS.items():
        value = metrics.get(source)
        if value is not None:
            values[alias] = value

    rpm = metrics.get("TURBINE_SPEED_RPM")
    torque = metrics.get("GB_TRQ")
    if rpm is not None and torque is not None:
        values["power"] = round(shaft_power_kw(rpm, torque), 4)

    values["state"] = operating_state
    return values


class KafkaToMQTTBridge:
    """Bridges telemetry from Kafka topics to ThingsBoard MQTT endpoints."""

    def __init__(self, config: BridgeConfig, registry: Optional[DeviceRegistry] = None):
        self.config = config
        self.metrics = BridgeMetrics()
        self.registry = registry or DeviceRegistry.load(config.token_map_path)
        self.kafka_consumer = TurbineTelemetryConsumer(config.kafka, self.metrics)
        self.publisher = ThingsboardDevicePublisher(config.mqtt, self.metrics)
        self.running = False
        self._warned_unknown: set[tuple[str, str]] = set()

    def start(self) -> bool:
        """Initialize Kafka consumer and mark bridge as running."""
        logger.info("Initializing Kafka->ThingsBoard MQTT bridge...")
        if not self.kafka_consumer.connect():
            logger.error("Failed to connect to Kafka")
            return False
        self.running = True
        logger.info(
            "Bridge started; %d device binding(s) ready (MQTT sessions open lazily)",
            len(self.registry),
        )
        return True

    def run(self) -> None:
        """Process message batches continuously and forward to ThingsBoard."""
        logger.info("Starting message loop...")

        while self.running:
            try:
                batch = self.kafka_consumer.consume_batch(
                    max_messages=self.config.batch_size,
                    timeout_ms=int(self.config.batch_max_wait_s * 1000),
                )

                if batch:
                    published_count = 0
                    for msg in batch:
                        if self._publish_message(msg.value):
                            published_count += 1
                        self.metrics.messages_consumed += 1
                        self.metrics.last_message_time = datetime.now()

                    self.metrics.messages_published += published_count
                    if published_count:
                        self.metrics.last_publish_time = datetime.now()
                    logger.info(
                        "Published %d/%d messages to ThingsBoard",
                        published_count,
                        len(batch),
                    )

            except Exception as exc:
                logger.error("Error in message loop: %s", exc)
                self.metrics.kafka_errors += 1
                time.sleep(1)

    def _publish_message(self, telemetry: dict) -> bool:
        """Publish one Kafka telemetry record as ThingsBoard device telemetry."""
        try:
            customer_id = telemetry.get("customer_id")
            turbine_id = telemetry.get("turbine_id")
            if not customer_id or not turbine_id:
                logger.warning("Telemetry record missing customer_id/turbine_id; dropped")
                return False

            binding = self.registry.resolve(customer_id, turbine_id)
            if binding is None:
                self.metrics.unknown_devices += 1
                identity = (customer_id, turbine_id)
                if identity not in self._warned_unknown:
                    self._warned_unknown.add(identity)
                    logger.warning(
                        "No ThingsBoard device bound for %s/%s; skipping "
                        "(further occurrences silenced)",
                        customer_id,
                        turbine_id,
                    )
                return False

            ts_ms = int(
                telemetry.get("event_time_ms")
                or telemetry.get("timestamp")
                or time.time() * 1000
            )
            values = build_telemetry_values(
                telemetry.get("metrics", {}),
                telemetry.get("operating_state", telemetry.get("state", "UNKNOWN")),
            )

            return self.publisher.publish_telemetry(binding, ts_ms, values)

        except Exception as exc:
            logger.error("Error publishing telemetry: %s", exc)
            return False

    def stop(self) -> None:
        """Stop message consumer and close active MQTT sessions."""
        logger.info("Stopping bridge...")
        self.running = False
        if self.kafka_consumer.consumer:
            self.kafka_consumer.consumer.close()
        self.publisher.disconnect_all()
        logger.info("Bridge stopped")


# Health check server
def start_health_check_server(port: int, metrics: BridgeMetrics) -> None:
    """Start background HTTP health check and metrics server."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class HealthCheckHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/ready":
                healthy = metrics.is_healthy()
                self.send_response(200 if healthy else 503)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"OK\n" if healthy else b"NOT READY\n")
            elif self.path == "/metrics":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(metrics.to_dict()).encode("utf-8"))
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format, *args):
            pass

    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("Health check server started on port %d", port)


# Main
def main() -> int:
    """Initialize configuration, health server, and bridge processing loop."""
    config = BridgeConfig()

    try:
        bridge = KafkaToMQTTBridge(config)
    except (FileNotFoundError, ValueError) as exc:
        logger.error("Cannot start bridge: %s", exc)
        return 1

    start_health_check_server(config.health_check_port, bridge.metrics)

    if not bridge.start():
        logger.error("Failed to start bridge")
        return 1

    try:
        bridge.run()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    finally:
        bridge.stop()

    return 0


if __name__ == "__main__":
    sys.exit(main())
