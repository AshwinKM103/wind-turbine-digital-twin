-- ==========================================================================
-- Wind Turbine Digital Twin - Fleet schema (multi-customer)
-- ==========================================================================
-- GENERATED from app/config/fleet.json by app/tools/generate_fleet_schema.py
-- Do not edit by hand: edit fleet.json and regenerate.
--
-- Prerequisite: app/config/iotdb-schema.sql has already created the
-- root.digitaltwin database and the turbine_template device template.
-- ==========================================================================

-- Customer1: 2 turbine(s) across 1 site(s)
SET DEVICE TEMPLATE turbine_template TO root.digitaltwin.customer1.site1;
CREATE TIMESERIES USING DEVICE TEMPLATE ON root.digitaltwin.customer1.site1.turbine01;
CREATE TIMESERIES USING DEVICE TEMPLATE ON root.digitaltwin.customer1.site1.turbine02;
SET TTL TO root.digitaltwin.customer1 2592000000;

-- Customer2: 3 turbine(s) across 1 site(s)
SET DEVICE TEMPLATE turbine_template TO root.digitaltwin.customer2.site1;
CREATE TIMESERIES USING DEVICE TEMPLATE ON root.digitaltwin.customer2.site1.turbine03;
CREATE TIMESERIES USING DEVICE TEMPLATE ON root.digitaltwin.customer2.site1.turbine04;
CREATE TIMESERIES USING DEVICE TEMPLATE ON root.digitaltwin.customer2.site1.turbine05;
SET TTL TO root.digitaltwin.customer2 2592000000;

-- Customer3: 4 turbine(s) across 1 site(s)
SET DEVICE TEMPLATE turbine_template TO root.digitaltwin.customer3.site1;
CREATE TIMESERIES USING DEVICE TEMPLATE ON root.digitaltwin.customer3.site1.turbine06;
CREATE TIMESERIES USING DEVICE TEMPLATE ON root.digitaltwin.customer3.site1.turbine07;
CREATE TIMESERIES USING DEVICE TEMPLATE ON root.digitaltwin.customer3.site1.turbine08;
CREATE TIMESERIES USING DEVICE TEMPLATE ON root.digitaltwin.customer3.site1.turbine09;
SET TTL TO root.digitaltwin.customer3 2592000000;

-- ==========================================================================
-- Verification:
--   SHOW DEVICES root.digitaltwin.**;
--   (expect exactly 9 devices, one per turbine in fleet.json)
-- ==========================================================================
