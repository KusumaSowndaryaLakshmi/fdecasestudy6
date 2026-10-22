import json
import sqlite3
from pathlib import Path

BASE = Path(__file__).parent
DB_PATH = BASE / "reliability.db"
DATA_PATH = BASE / "data" / "report_jobs.json"

STATUS_MAP = [
    ("completed",   "success",     "Report generated and delivered"),
    ("failed",      "failure",     "Job ended with a hard failure"),
    ("timed_out",   "failure",     "Hit the runner time limit (300s in this data)"),
    ("error",       "failure",     "Missing from the starter kit's failure list; the starter logic misses it"),
    ("running",     "in_progress", "Still executing"),
    ("queued",      "in_progress", "Waiting for a worker"),
]


def connect(path=DB_PATH):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn, data_path=DATA_PATH, reset=True):
    if reset:
        conn.executescript("DROP TABLE IF EXISTS jobs; DROP TABLE IF EXISTS status_map; DROP TABLE IF EXISTS retry_actions;")
    conn.executescript((BASE / "schema.sql").read_text())
    conn.executemany("INSERT OR REPLACE INTO status_map VALUES (?,?,?)", STATUS_MAP)
    jobs = json.loads(Path(data_path).read_text(encoding="utf-8"))["jobs"]
    conn.executemany(
        """INSERT OR REPLACE INTO jobs VALUES
           (:job_id,:run_id,:tenant_id,:tenant_name,:report_name,:scheduled_at,
            :status,:attempt_number,:duration_seconds,:row_count)""",
        jobs,
    )
    conn.commit()


if __name__ == "__main__":
    c = connect()
    init_db(c)
    n = c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    print(f"Loaded {n} attempts into {DB_PATH.name}")
