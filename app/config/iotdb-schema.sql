-- ============================================================================
-- Wind Turbine Digital Twin - IoTDB Schema (Week 1)
-- ============================================================================
-- Run via: docker exec -it iotdb /iotdb/sbin/start-cli.sh -h 127.0.0.1 -p 6667 \
--            -u root -pw root -e "$(cat iotdb-schema.sql)"
-- or, from inside the CLI shell, paste these statements one at a time.
--
-- Hierarchy: root.digitaltwin.<customer_id>.<site_id>.<turbine_id>.<measurement>
-- This file provisions customer1 / site1 / turbine01 (single turbine, per
-- current scope). Add more turbines later by SET-ing the same device
-- template onto additional root.digitaltwin.<customer>.<site>.* paths.
-- ============================================================================

-- 1. Database (storage group) per customer -> lets TTL / auth / deletion
--    be scoped per tenant without touching other customers' data.
CREATE DATABASE root.digitaltwin;

-- 2. Device template: all 61 sensor channels from the NI DAQ CSV, plus a
--    seq_no companion measurement used by the consumer for idempotency /
--    ordering diagnostics (see kafka-consumer.py). GORILLA encoding is
--    IoTDB's recommended encoding for near-continuous floating point
--    sensor series; SNAPPY compression on top for additional size reduction.
CREATE DEVICE TEMPLATE turbine_template (
  PT_109A FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  PT_110A FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  PT_110B FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  PT_111B FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  PT_111 FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  PT_112 FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  PT_162 FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  PT_161 FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  PT_160 FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  PT_120 FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  PT_111C FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  PT_153 FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  PT_163 FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  PT_150A FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  PT_150B FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  PT_201 FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  PT_253 FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  FT_110A FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  FT_162 FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  TT_109A FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  TT_110A FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  TT_110B FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  TT_111 FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  TT_112 FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  TT_162 FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  TT_161 FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  TT_160 FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  TT_120_R FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  TT_120 FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  TT_111C FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  TT_111C_R FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  DYNO_WATER_O_L FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  TT_163 FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  TT_150A FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  TT_150B FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  ZT_600 FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  ZT_601 FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  XT_600 FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  XT_601 FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  XT_602 FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  XT_603 FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  XT_604 FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  XT_605 FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  XT_606 FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  XT_607 FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  HP_DEMAND FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  ACT_POS_FB FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  GB_TRQ FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  PYRO_T FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  PYRO_GB FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  TURBINE_SPEED_RPM FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  RTD_219A FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  RTD_219B FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  RTD_220 FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  RTD_221 FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  RTD_200 FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  RTD_202 FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  RTD_203 FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  RTD_204 FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  RTD_205 FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  RTD_201 FLOAT ENCODING=GORILLA COMPRESSION=SNAPPY,
  seq_no INT32 ENCODING=RLE COMPRESSION=SNAPPY
);

-- 3. Attach the template to every turbine device under customer1/site1.
--    Wildcards mean future turbines (turbine02, turbine03, ...) inherit
--    the schema automatically the first time they're written to -- no
--    schema migration needed to add turbines.
SET DEVICE TEMPLATE turbine_template TO root.digitaltwin.customer1.site1;

-- 4. Activate the template on the specific turbine used in Week 1
--    (root.digitaltwin.customer1.site1.turbine01). Activation on a
--    concrete device path is required before the first insert on some
--    IoTDB versions when auto-activation is disabled; harmless if it
--    later auto-activates on first write.
CREATE TIMESERIES USING DEVICE TEMPLATE ON root.digitaltwin.customer1.site1.turbine01;

-- 5. Retention: 30 days, per requirements (2592000000 ms = 30 * 24 * 60 * 60 * 1000).
--    Applies to the whole customer1 database; narrow the path if a
--    per-turbine TTL is ever needed instead.
SET TTL TO root.digitaltwin.customer1 2592000000;

-- ============================================================================
-- Verification (run manually after schema load):
--   SHOW DATABASES;
--   SHOW DEVICES root.digitaltwin.**;
--   SHOW TIMESERIES root.digitaltwin.customer1.site1.turbine01.**;
--   SHOW TTL ON root.digitaltwin.customer1;
-- ============================================================================
