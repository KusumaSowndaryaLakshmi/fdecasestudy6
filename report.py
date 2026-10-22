"""Command-line view of the same logic.
  python report.py           show runs and decisions (dry run)
  python report.py --retry   also queue the safe retries (simulated)
"""
import sys

import db
import engine

conn = db.connect()
db.init_db(conn, reset=False)
runs = engine.load_runs(conn)
as_of = engine.default_as_of(runs)
engine.evaluate(runs, as_of)
print(f"Evaluated as of {as_of}\n")
for r in runs:
    if r.verdict in ("delivered",):
        continue
    print(f"{r.run_id}  {r.tenant:<16} {r.scheduled_at:%b %d}  {r.verdict.upper():<10} {r.action or '-':<9} {' > '.join(r.statuses)}")
    print(f"    why:   {r.reason}")
    if r.cause:
        print(f"    cause: {r.cause}")
print("\nSummary:", engine.summarize(runs))

if "--retry" in sys.argv:
    queued, skipped = engine.queue_retries(conn, runs)
    for r in queued:
        print(f"RETRY queued (simulated): {r.run_id} as attempt {r.next_attempt}, not before {r.retry_after:%H:%M}")
    for r in skipped:
        print(f"Already queued, skipped: {r.run_id} attempt {r.next_attempt}")
    if not queued and not skipped:
        print("Nothing to retry.")
else:
    print("\nDry run. Add --retry to queue the safe retries.")
