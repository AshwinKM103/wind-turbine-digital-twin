# DAQ Pipeline Track Status

## Done
- Historical NI DAQ log replay implemented in [replay_daq_to_kafka.py](../../../app/tools/replay_daq_to_kafka.py) as single source of telemetry, supporting 1 Hz rate-controlled replay and HTTP control server.
- Kafka-to-IoTDB consumer implemented in [kafka_consumer.py](../../../app/src/kafka_consumer.py) featuring 62-measurement Tablet batch writes, circuit breaker error handling, and dead-letter queue routing.
- Kafka-to-ThingsBoard bridge implemented in [kafka_mqtt_bridge.py](../../../app/src/kafka_mqtt_bridge.py) streaming headline telemetry and subsystem diagnostics over MQTT.
- Historical NI DAQ log replay implemented in [replay_daq_to_kafka.py](../../../app/tools/replay_daq_to_kafka.py) supporting 1 Hz rate-controlled replay, an HTTP control server (`/api/replay/status`), subsystem scoring, and automated PDF shift test report generation (`/api/reports/generate`).
- Normalized replay dataset generated at [daq_test_log_normalized_1hz.csv](../../../data/daq_test_log_normalized_1hz.csv) alongside sensor metadata in [daq_sensor_metadata.json](../../../data/daq_sensor_metadata.json) and template schema mapping in [turbine-schema-extracted.json](../../../data/turbine-schema-extracted.json).

## In Progress
- Direct live NI-DAQmx hardware driver ingestion into Kafka.
- Reconciling timestamp resolution limitations in historical raw logs ([20260812_NI_DAQ_TEST_LOG_DigitalTwin.csv](../../../data/20260812_NI_DAQ_TEST_LOG_DigitalTwin.csv)), where minute-precision timestamps cover ~3,589 rows/hr.

## Pending / Not Started
- High-frequency edge buffer service for handling bursty millisecond-level raw DAQ acquisitions prior to Kafka ingress.
- Schema migration tool for dynamic addition and removal of NI DAQ hardware physical channels without service restarts.

## Open Decisions
- Timestamp interpolation strategy: whether to synthesize sub-second timestamps linearly across rows sharing the same minute in raw logs or preserve original timestamps and rely on consumer-side sequence numbers (`seq_no`).
- Live acquisition protocol: whether to run a Python DAQmx service writing directly to Kafka or publish over MQTT through an intermediate edge gateway.
