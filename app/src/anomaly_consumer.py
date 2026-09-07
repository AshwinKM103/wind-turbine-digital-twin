#!/usr/bin/env python3
"""
Anomaly Detection Consumer - subscribes to Kafka telemetry and runs anomaly detection.

Reads from KAFKA_TOPIC, processes readings through AnomalyDetector, and logs alerts.
For Phase 1: anomalies logged only (not published to Kafka). Phase 2 will emit to alert topics.

Health check: GET /ready returns 200 when connected to Kafka and successfully processed ≥1 message.
"""

import json
import logging
import os
import signal
import sys
import time
from typing import Optional

from confluent_kafka import Consumer, KafkaError

from anomaly_detection import AnomalyDetector, SensorReading
from config import Config
from health_server import start_health_server
from logging_config import configure_logging

log = configure_logging("anomaly-detector")
config = Config()


class AnomalyConsumer:
    """Consumes telemetry from Kafka and runs anomaly detection."""

    def __init__(self, health_state=None):
        self.detector = AnomalyDetector("/app/config/anomaly_thresholds.json")
        self.consumer = Consumer({
            'bootstrap.servers': config.KAFKA_BOOTSTRAP_SERVERS,
            'group.id': f"{config.KAFKA_GROUP_ID}-anomaly",
            'auto.offset.reset': 'latest',
            'enable.auto.commit': True,
            'session.timeout.ms': 30000,
        })
        self.consumer.subscribe([config.KAFKA_TOPIC])
        self.running = True
        self.message_count = 0
        self.error_count = 0
        self.health_state = health_state
        signal.signal(signal.SIGTERM, self._shutdown)
        signal.signal(signal.SIGINT, self._shutdown)

    def _shutdown(self, signum, frame):
        """Graceful shutdown on SIGTERM/SIGINT."""
        log.info(f"Shutdown signal {signum} received. Closing consumer.")
        self.running = False

    def process_message(self, message_dict: dict, seq: int = 0) -> Optional[dict]:
        """
        Convert Kafka message to SensorReading and run anomaly detection.

        Args:
            message_dict: Deserialized JSON from Kafka topic
            seq: sequence number for this reading

        Returns:
            Alert dict if anomaly detected, else None
        """
        try:
            customer_id = message_dict.get("customer_id", "unknown")
            turbine_id = message_dict.get("turbine_id", "unknown")
            sensor_name = message_dict.get("sensor_id", "")
            device_path = f"root.digitaltwin.{customer_id}.site1.{turbine_id}"

            reading = SensorReading(
                timestamp_ms=message_dict.get("timestamp", int(time.time() * 1000)),
                customer_id=customer_id,
                turbine_id=turbine_id,
                sensor_name=sensor_name,
                value=float(message_dict.get("value", 0)),
                device_path=device_path,
                sequence_number=seq,
            )
            alert = self.detector.process_reading(reading)
            if alert:
                log.warning(
                    "ANOMALY DETECTED",
                    extra={
                        "alert_type": alert.detection_type.value,
                        "severity": alert.severity.value,
                        "sensor": reading.sensor_name,
                        "customer": reading.customer_id,
                        "turbine": reading.turbine_id,
                        "value": reading.value,
                        "alert_msg": alert.message,
                    },
                )
                return alert.__dict__
            return None
        except (KeyError, ValueError, TypeError) as e:
            self.error_count += 1
            log.error(f"Failed to process message: {e}", extra={"msg": str(message_dict)[:100]})
            return None

    def run(self):
        """Main consumer loop: poll Kafka, process readings, detect anomalies."""
        log.info("Anomaly detection consumer started")
        sequence_number = 0

        try:
            while self.running:
                message = self.consumer.poll(timeout=1.0)

                if message is None:
                    continue

                if message.error():
                    if message.error().code() != KafkaError._PARTITION_EOF:
                        log.error(f"Kafka error: {message.error()}")
                        self.error_count += 1
                    continue

                try:
                    msg_value = json.loads(message.value().decode('utf-8'))
                    alert = self.process_message(msg_value, seq=sequence_number)
                    sequence_number += 1
                    self.message_count += 1

                    # Mark as ready after first successful message
                    if self.message_count == 1 and self.health_state:
                        self.health_state.set_ready(True)
                        self.health_state.set_check("kafka", True, "consuming messages")

                    if self.message_count % 1000 == 0:
                        log.info(
                            f"Processed {self.message_count} messages, "
                            f"{self.error_count} errors"
                        )
                except (json.JSONDecodeError, UnicodeDecodeError) as e:
                    self.error_count += 1
                    log.error(f"Failed to parse message: {e}")
                except Exception as e:
                    self.error_count += 1
                    log.exception(f"Unexpected error processing message: {e}")

        except KeyboardInterrupt:
            log.info("Interrupted by user")
        except Exception as e:
            log.exception(f"Fatal error in consumer loop: {e}")
            self.error_count += 1
        finally:
            log.info("Anomaly consumer shutting down")
            self.consumer.close()


def main():
    """Entry point: initialize logging, health server, and consumer."""
    health = start_health_server(config.HEALTH_CHECK_PORT, "anomaly-detector")
    consumer = AnomalyConsumer(health_state=health)

    try:
        log.info("Starting anomaly detection consumer loop")
        health.set_ready(False)
        health.set_check("kafka", False, "connecting...")

        consumer.run()
    except KeyboardInterrupt:
        log.info("Interrupted by user")
    except Exception as e:
        log.exception(f"Fatal error in anomaly consumer: {e}")
        sys.exit(1)
    finally:
        health.set_ready(False)
        log.info("Anomaly consumer shut down")


if __name__ == "__main__":
    main()
