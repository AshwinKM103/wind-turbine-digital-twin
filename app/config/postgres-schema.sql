-- postgres-schema.sql - Operational store for alerts and turbine state history.
--
-- IoTDB holds the raw telemetry; this database holds the *derived*, low-volume
-- facts a KPI dashboard needs to answer questions IoTDB is a poor fit for:
--   "how many alerts fired last week, and how long did each take to log?"
--   "what fraction of the last 7 days was turbine04 in DOWN?"
-- Both are relational aggregations over a few thousand rows, not time-series
-- scans, so they live in Postgres.
--
-- Applied by provisioning/postgres/init.sh on first container start.
-- Re-runnable: every statement is IF NOT EXISTS / OR REPLACE.

-- ---------------------------------------------------------------------------
-- alerts: one row per *confirmed* alert (i.e. per Kafka publish).
--
-- Three timestamps, deliberately, because they answer different questions:
--   start_time  -- when the underlying condition first tripped
--                  (alert_tracking["first_triggered"], before confirmation)
--   event_time  -- the telemetry timestamp of the reading that confirmed it
--   logged_time -- when this row was written
-- MTTA is logged_time - start_time: how long a real condition sat undetected
-- while the detector waited for its confirmation count. Storing only one
-- timestamp would make that unrecoverable.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alerts (
    alert_id        UUID        PRIMARY KEY,
    customer_id     TEXT        NOT NULL,
    turbine_id      TEXT        NOT NULL,
    device_path     TEXT        NOT NULL,
    sensor          TEXT        NOT NULL,
    detection_type  TEXT        NOT NULL,
    severity        TEXT        NOT NULL,
    value           DOUBLE PRECISION,
    reason          TEXT        NOT NULL,
    threshold_info  JSONB,
    start_time      TIMESTAMPTZ NOT NULL,
    event_time      TIMESTAMPTZ NOT NULL,
    logged_time     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT alerts_severity_known
        CHECK (severity IN ('info', 'warning', 'critical')),
    -- Ordering invariant. A negative MTTA would silently poison every
    -- percentile on the KPI dashboard, so it is rejected at write time
    -- rather than filtered at read time in six different queries.
    CONSTRAINT alerts_start_not_after_logged
        CHECK (start_time <= logged_time)
);

-- The alert table is queried three ways and only three ways: by customer over
-- a time window (every dashboard panel), by turbine (the heatmap), and by
-- sensor (top offenders). One composite index per access path.
CREATE INDEX IF NOT EXISTS idx_alerts_customer_logged
    ON alerts (customer_id, logged_time DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_customer_turbine_logged
    ON alerts (customer_id, turbine_id, logged_time DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_customer_sensor
    ON alerts (customer_id, sensor, severity);

-- ---------------------------------------------------------------------------
-- alert_breaches: one row per threshold breach *observation*, including the
-- ones that never reached the confirmation count and so never became an alert.
--
-- This is what makes MTTA analysable rather than merely reportable: the
-- alerts table says a warning was logged at 12:04, the breach table says the
-- sensor had been out of range since 11:58 and was seen out of range six
-- times in between. Without it, a tuning question ("is confirmation_count=3
-- too slow for vibration?") cannot be answered from stored data at all.
--
-- alert_id is nullable and ON DELETE SET NULL: breaches outlive the alert
-- they contributed to, and retention prunes the two tables independently.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alert_breaches (
    breach_id       BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_id     TEXT        NOT NULL,
    turbine_id      TEXT        NOT NULL,
    sensor          TEXT        NOT NULL,
    detection_type  TEXT        NOT NULL,
    severity        TEXT        NOT NULL,
    value           DOUBLE PRECISION,
    turbine_state   TEXT,
    -- Which observation in the confirmation run this was: 1 = first breach,
    -- N = the one that tripped the alert.
    confirmation_no INTEGER     NOT NULL,
    alert_id        UUID        REFERENCES alerts (alert_id) ON DELETE SET NULL,
    event_time      TIMESTAMPTZ NOT NULL,
    logged_time     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT alert_breaches_severity_known
        CHECK (severity IN ('info', 'warning', 'critical'))
);

CREATE INDEX IF NOT EXISTS idx_breaches_customer_logged
    ON alert_breaches (customer_id, logged_time DESC);
CREATE INDEX IF NOT EXISTS idx_breaches_customer_turbine_sensor
    ON alert_breaches (customer_id, turbine_id, sensor);
CREATE INDEX IF NOT EXISTS idx_breaches_alert
    ON alert_breaches (alert_id);

-- ---------------------------------------------------------------------------
-- turbine_states: the operating-state timeline, one row per *stable* state.
--
-- "Stable" means the inferred state held for at least
-- STATE_STABILITY_SECONDS (default 30) before it is recorded. Raw per-sample
-- inference from RPM flickers across the IDLE/RAMP_UP boundary during
-- spin-up; writing every flicker would produce thousands of sub-second rows
-- a day per turbine and make "time in state" meaningless. The stability gate
-- turns that into roughly one row per genuine transition.
--
-- A row is INSERTed with end_time NULL when the state is entered and UPDATEd
-- when it is left, so the currently-open state is always
-- `WHERE end_time IS NULL` -- exactly one row per turbine.
--
-- duration_seconds is generated, not application-supplied: it cannot drift
-- from the timestamps it summarises.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS turbine_states (
    state_id         BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_id      TEXT        NOT NULL,
    turbine_id       TEXT        NOT NULL,
    device_path      TEXT        NOT NULL,
    state            TEXT        NOT NULL,
    start_time       TIMESTAMPTZ NOT NULL,
    end_time         TIMESTAMPTZ,
    duration_seconds DOUBLE PRECISION
        GENERATED ALWAYS AS (EXTRACT(EPOCH FROM (end_time - start_time))) STORED,
    logged_time      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT turbine_states_known
        CHECK (state IN ('IDLE', 'RAMP_UP', 'STEADY_STATE', 'RAMP_DOWN', 'DOWN')),
    CONSTRAINT turbine_states_end_after_start
        CHECK (end_time IS NULL OR end_time >= start_time)
);

CREATE INDEX IF NOT EXISTS idx_states_customer_start
    ON turbine_states (customer_id, start_time DESC);
CREATE INDEX IF NOT EXISTS idx_states_customer_turbine_start
    ON turbine_states (customer_id, turbine_id, start_time DESC);

-- At most one open state per turbine. This is the invariant the writer's
-- "UPDATE ... WHERE end_time IS NULL" close step depends on; enforcing it
-- here means a restarted detector that re-opens a state cannot silently
-- create two overlapping timelines.
CREATE UNIQUE INDEX IF NOT EXISTS idx_states_one_open_per_turbine
    ON turbine_states (customer_id, turbine_id)
    WHERE end_time IS NULL;

-- ---------------------------------------------------------------------------
-- Retention: 30 days, enforced by deletion rather than by a query filter.
--
-- Postgres has no built-in scheduler (pg_cron is an extension the alpine
-- image does not ship), so this is a function the writer calls hourly --
-- see PostgresStore._maybe_prune. Keeping the policy in SQL rather than in
-- Python means the retention window is auditable from a psql prompt, which
-- is what a compliance check actually asks for.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION prune_retention(retention_days INTEGER DEFAULT 30)
RETURNS TABLE (table_name TEXT, rows_deleted BIGINT)
LANGUAGE plpgsql
AS $$
DECLARE
    cutoff TIMESTAMPTZ := now() - make_interval(days => retention_days);
    deleted BIGINT;
BEGIN
    -- Breaches first: they reference alerts, and deleting the parent first
    -- would only null the link and leave orphans behind for a whole cycle.
    DELETE FROM alert_breaches WHERE logged_time < cutoff;
    GET DIAGNOSTICS deleted = ROW_COUNT;
    table_name := 'alert_breaches'; rows_deleted := deleted; RETURN NEXT;

    DELETE FROM alerts WHERE logged_time < cutoff;
    GET DIAGNOSTICS deleted = ROW_COUNT;
    table_name := 'alerts'; rows_deleted := deleted; RETURN NEXT;

    -- Closed states only. An open state that started 31 days ago is the
    -- turbine's *current* state; deleting it would lose the live timeline.
    DELETE FROM turbine_states WHERE end_time IS NOT NULL AND end_time < cutoff;
    GET DIAGNOSTICS deleted = ROW_COUNT;
    table_name := 'turbine_states'; rows_deleted := deleted; RETURN NEXT;
END;
$$;

COMMENT ON FUNCTION prune_retention(INTEGER) IS
    'Deletes alerts, breaches and closed state rows older than retention_days '
    '(default 30). Called hourly by the anomaly detector.';
