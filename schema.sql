-- Raw attempt log, loaded as-is from the job runner export.
CREATE TABLE IF NOT EXISTS jobs (
    job_id           TEXT PRIMARY KEY,
    run_id           TEXT NOT NULL,
    tenant_id        TEXT NOT NULL,
    tenant_name      TEXT NOT NULL,
    report_name      TEXT NOT NULL,
    scheduled_at     TEXT NOT NULL,
    status           TEXT NOT NULL,
    attempt_number   INTEGER NOT NULL,
    duration_seconds INTEGER,
    row_count        INTEGER,
    UNIQUE (run_id, attempt_number)
);
CREATE INDEX IF NOT EXISTS idx_jobs_run ON jobs (run_id);

-- The "what counts as failed" decision lives in data, not code.
-- Any status NOT listed here is treated as 'unknown' and surfaced to a human.
CREATE TABLE IF NOT EXISTS status_map (
    status   TEXT PRIMARY KEY,
    category TEXT NOT NULL CHECK (category IN ('success','failure','in_progress')),
    note     TEXT
);

-- Audit log of every retry decision taken. The UNIQUE key is the idempotency
-- guard: one retry per (run, next attempt number), even if someone double-clicks
-- or two scheduler instances overlap.
CREATE TABLE IF NOT EXISTS retry_actions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL,
    attempt_number  INTEGER NOT NULL,
    mode            TEXT NOT NULL,
    reason          TEXT,
    created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (run_id, attempt_number)
);
