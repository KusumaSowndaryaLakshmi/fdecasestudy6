import sqlite3, sys, unittest
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import db, engine


def make(jobs):
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row
    conn.executescript((db.BASE / "schema.sql").read_text())
    conn.executemany("INSERT INTO status_map VALUES (?,?,?)", db.STATUS_MAP)
    for i, (run, n, status, dur, rows, when) in enumerate(jobs):
        conn.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (f"J{i}", run, "T1", "Acme", "Stmt", when, status, n, dur, rows))
    return engine.load_runs(conn)

D = "2026-09-01T02:00:00"
NOW = datetime(2026, 9, 1, 3, 0)


class EngineTests(unittest.TestCase):
    def one(self, jobs, now=NOW):
        runs = engine.evaluate(make(jobs), now)
        return runs[0]

    def test_error_status_counts_as_failure(self):
        r = self.one([("R", 1, "error", 6, None, D)])
        self.assertEqual((r.verdict, r.action, r.next_attempt), ("failed", "RETRY", 2))

    def test_recovered_run_is_not_failed(self):
        r = self.one([("R", 1, "failed", 9, None, D), ("R", 2, "completed", 50, 10, D)])
        self.assertEqual((r.verdict, r.action), ("recovered", ""))

    def test_budget_exhausted_escalates(self):
        r = self.one([("R", i, "failed", 9, None, D) for i in (1, 2, 3)])
        self.assertEqual(r.action, "ESCALATE")

    def test_two_timeouts_escalate_early(self):
        r = self.one([("R", 1, "timed_out", 300, None, D), ("R", 2, "timed_out", 300, None, D)])
        self.assertEqual(r.action, "ESCALATE")

    def test_single_timeout_is_retried(self):
        r = self.one([("R", 1, "timed_out", 300, None, D)])
        self.assertEqual(r.action, "RETRY")

    def test_unknown_status_is_never_silently_ok(self):
        r = self.one([("R", 1, "partial", 20, 5, D)])
        self.assertEqual((r.verdict, r.action), ("unknown", "ESCALATE"))

    def test_empty_success_is_suspect(self):
        r = self.one([("R", 1, "completed", 20, 0, D)])
        self.assertEqual(r.verdict, "suspect")

    def test_stale_run_not_auto_retried(self):
        r = self.one([("R", 1, "error", 6, None, D)], now=NOW + timedelta(days=10))
        self.assertEqual(r.action, "ESCALATE")

    def test_running_job_is_not_a_failure(self):
        r = self.one([("R", 1, "running", 0, None, D)], now=NOW - timedelta(minutes=50))
        self.assertEqual(r.verdict, "in_progress")

    def test_sample_data_matches_expected(self):
        conn = db.connect(":memory:"); db.init_db(conn)
        runs = engine.load_runs(conn); engine.evaluate(runs, engine.default_as_of(runs))
        s = engine.summarize(runs)
        self.assertEqual((s["delivered"], s["recovered"], s["failed"], s["to_retry"], s["to_escalate"]), (9, 1, 2, 1, 1))


if __name__ == "__main__":
    unittest.main()
