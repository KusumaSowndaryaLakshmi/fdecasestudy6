# Report Delivery Reliability

Finds scheduled report runs that never succeeded, explains why, and decides which are safe to retry automatically.

Stack: Python, Flask, SQLite, HTML/CSS with Jinja templates.

## Run it

```
pip install -r requirements.txt
python report.py          # command-line summary (dry run)
python report.py --retry  # same, and queue the safe retries automatically (simulated)
python app.py             # dashboard at http://127.0.0.1:5000
python -m unittest        # 10 tests
```

The database is created from `data/report_jobs.json` on first run. "Reload demo data" on the dashboard resets it.

## What you will see on the sample data

- 9 of 12 runs delivered on the first attempt.
- R-003 (Beta Retail) failed once and recovered on retry.
- R-010 (Epsilon Media) failed with status `error` and has not been retried. The dashboard marks it safe to retry.
- R-005 (Gamma Health) failed three times (timeout, timeout, failed). The dashboard sends it to a person.

The starter kit's `FAILURE_STATUSES` leaves out `error`, so its logic would have reported only R-005 and missed R-010.

## Files

- `engine.py`: classification, verdict per run, retry decision, root-cause hints
- `schema.sql`, `db.py`: tables, status taxonomy, seed loading
- `app.py`, `templates/`, `static/`: dashboard and the retry endpoints
- `report.py`: same logic on the command line
- `tests/test_engine.py`: unit tests for each rule

## Known limitations

- Retries are simulated. They write to a `retry_actions` table; no real job runner is called. The place to plug one in is marked in `app.py`.
- "Now" defaults to one hour after the last log entry, because the sample data is old. Use `?as_of=now` or the `AS_OF` environment variable for real time.
- Retry safety assumes report generation is idempotent and that delivery to the tenant happens only on success. This needs confirming with Meridian.
- The cause hints are simple rules over status and duration. They are hints, not diagnoses.
- No built-in scheduler, alerting, or authentication. `python report.py --retry` is built to be run from cron or a job scheduler; the dashboard buttons do the same thing by hand.
- Thresholds (3 attempts, 72 hour window, 5 and 10 minute backoff) are defaults in `engine.py`, not tuned on real data. With 15 rows they cannot be.
