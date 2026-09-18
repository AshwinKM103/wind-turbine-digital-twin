-- ==========================================================================
-- Wind Turbine Digital Twin - Fleet schema (multi-customer)
-- ==========================================================================
-- GENERATED from app/config/fleet.json by app/tools/generate_fleet_schema.py
-- Do not edit by hand: edit fleet.json and regenerate.
--
-- Prerequisite: app/config/iotdb-schema.sql has already created the
-- root.digitaltwin database and the turbine_template device template.
-- ==========================================================================

-- Zephyr Energy: 1 turbine(s) across 1 site(s)
SET DEVICE TEMPLATE turbine_template TO root.digitaltwin.`zephyr-energy`.`cascade-ridge`;
CREATE TIMESERIES USING DEVICE TEMPLATE ON root.digitaltwin.`zephyr-energy`.`cascade-ridge`.boreas;
SET TTL TO root.digitaltwin.`zephyr-energy` 2592000000;

-- ==========================================================================
-- Verification:
--   SHOW DEVICES root.digitaltwin.**;
--   (expect exactly 1 devices, one per turbine in fleet.json)
-- ==========================================================================
