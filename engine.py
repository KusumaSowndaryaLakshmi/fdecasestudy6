"""
Core logic: turn raw attempts into one verdict per run, then decide the action.

Verdicts (one per logical run):
  delivered    first attempt succeeded
  recovered    succeeded only after one or more retries (worth watching)
  suspect      "succeeded" but produced zero/null rows (silent failure)
  in_progress  still running/queued
  unknown      latest status not in status_map (taxonomy gap, needs a human)
  failed       never succeeded

Actions (only meaningful for failed runs):
  RETRY      safe and worthwhile to retry automatically
  ESCALATE   a human needs to look
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta

MAX_ATTEMPTS = 3                 # total attempts, including the original
RETRY_WINDOW = timedelta(hours=72)  # older than this: stale, a human decides
BACKOFF_MINUTES = [5, 10]        # wait before attempt 2, attempt 3
FAST_FAIL_SECONDS = 15           # a job dying this fast never got to real work
STALE_RUNNING = timedelta(hours=1)

ISO = "%Y-%m-%dT%H:%M:%S"


@dataclass
class Attempt:
    job_id: str
    n: int
    status: str
    category: str
    duration: int
    rows: int | None
    at: datetime


@dataclass
class Run:
    run_id: str
    tenant_id: str
    tenant: str
    report: str
    scheduled_at: datetime
    attempts: list = field(default_factory=list)
    verdict: str = ""
    action: str = ""            # RETRY / ESCALATE / ""
    next_attempt: int | None = None
    retry_after: datetime | None = None
    reason: str = ""
    cause: str = ""             # heuristic root-cause hint

    @property
    def statuses(self):
        return [a.status for a in self.attempts]


def load_runs(conn):
    rows = conn.execute(
        """SELECT j.*, COALESCE(m.category, 'unknown') AS category
           FROM jobs j LEFT JOIN status_map m ON lower(trim(j.status)) = m.status
           ORDER BY j.run_id, j.attempt_number"""
    ).fetchall()
    runs = {}
    for r in rows:
        run = runs.setdefault(
            r["run_id"],
            Run(r["run_id"], r["tenant_id"], r["tenant_name"], r["report_name"],
                datetime.strptime(r["scheduled_at"], ISO)),
        )
        run.attempts.append(Attempt(r["job_id"], r["attempt_number"], r["status"], r["category"],
                                    r["duration_seconds"] or 0, r["row_count"],
                                    datetime.strptime(r["scheduled_at"], ISO)))
    return list(runs.values())


def default_as_of(runs):
    """The sample data is from the past, so 'now' defaults to just after the last log line."""
    return max(a.at for r in runs for a in r.attempts) + timedelta(hours=1)


def _root_cause(run, tenant_median_rows):
    s = [a.category + ":" + a.status for a in run.attempts]
    statuses = run.statuses
    timeouts = statuses.count("timed_out")
    if timeouts and timeouts == len(statuses):
        return "Every attempt timed out: looks like a performance/volume problem, not a transient glitch."
    if timeouts and statuses[-1] != "timed_out":
        return ("Timeouts followed by a hard failure: probably a resource or volume problem "
                "that retries made worse, not random flakiness.")
    fast = [a for a in run.attempts if a.category == "failure" and a.duration <= FAST_FAIL_SECONDS]
    if fast and len(fast) == len([a for a in run.attempts if a.category == "failure"]):
        return ("Fails within seconds: the job never reached real work, so suspect config, "
                "credentials or upstream data rather than load.")
    return "No clear pattern in the attempt history."


def evaluate(runs, as_of, max_attempts=MAX_ATTEMPTS):
    for run in runs:
        atts = run.attempts
        latest = atts[-1]
        ok = [a for a in atts if a.category == "success"]

        if ok:
            good = ok[-1]
            if not good.rows:
                run.verdict, run.action = "suspect", "ESCALATE"
                run.reason = "Marked completed but produced no rows: the customer may have received an empty report."
            elif len(atts) > 1:
                run.verdict = "recovered"
                run.reason = f"Succeeded on attempt {good.n} after {good.n - 1} failed attempt(s)."
            else:
                run.verdict = "delivered"
            continue

        if latest.category == "in_progress":
            if as_of - latest.at > STALE_RUNNING:
                run.verdict, run.action = "failed", "ESCALATE"
                run.reason = "Still marked as running long after it should have finished (stuck job)."
            else:
                run.verdict = "in_progress"
            continue

        if any(a.category == "unknown" for a in atts):
            run.verdict, run.action = "unknown", "ESCALATE"
            bad = next(a.status for a in atts if a.category == "unknown")
            run.reason = f"Status '{bad}' is not in the status map. Classify it before this run can be judged."
            continue

        # Never succeeded: decide whether automation may touch it.
        run.verdict = "failed"
        run.cause = _root_cause(run, None)
        n = latest.n
        if n >= max_attempts:
            run.action = "ESCALATE"
            run.reason = f"Retry budget used up ({n} of {max_attempts} attempts, all unsuccessful)."
        elif run.statuses[-2:] == ["timed_out", "timed_out"]:
            run.action = "ESCALATE"
            run.reason = "Two timeouts in a row. An identical retry will hit the same limit, so don't burn the budget."
        elif as_of - run.scheduled_at > RETRY_WINDOW:
            run.action = "ESCALATE"
            run.reason = "Too old to retry automatically; a human should decide if the report is still wanted."
        else:
            run.action = "RETRY"
            run.next_attempt = n + 1
            wait = BACKOFF_MINUTES[min(n - 1, len(BACKOFF_MINUTES) - 1)]
            run.retry_after = latest.at + timedelta(minutes=wait)
            run.reason = f"Attempt {n} of {max_attempts} failed ({latest.status}). Retry {run.next_attempt} after {wait} min backoff."
    return runs


def summarize(runs):
    out = {k: 0 for k in ("delivered", "recovered", "suspect", "in_progress", "unknown", "failed")}
    for r in runs:
        out[r.verdict] += 1
    out["to_retry"] = sum(r.action == "RETRY" for r in runs)
    out["to_escalate"] = sum(r.action == "ESCALATE" for r in runs)
    return out


def tenant_health(runs):
    t = {}
    for r in runs:
        d = t.setdefault(r.tenant, {"runs": 0, "clean": 0, "problem": 0})
        d["runs"] += 1
        if r.verdict == "delivered":
            d["clean"] += 1
        else:
            d["problem"] += 1
    return t


def queue_retries(conn, runs, mode="simulated"):
    """Record a retry for every run whose action is RETRY. Safe to call repeatedly:
    the UNIQUE (run_id, attempt_number) key means an already-queued retry is skipped.
    In production this is where the job runner's API would be called."""
    import sqlite3
    queued, skipped = [], []
    for r in runs:
        if r.action != "RETRY":
            continue
        try:
            conn.execute("INSERT INTO retry_actions (run_id, attempt_number, mode, reason) VALUES (?,?,?,?)",
                         (r.run_id, r.next_attempt, mode, r.reason))
            queued.append(r)
        except sqlite3.IntegrityError:
            skipped.append(r)
    conn.commit()
    return queued, skipped
