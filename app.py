import os
import sqlite3
from datetime import datetime

from flask import Flask, flash, redirect, render_template, request, url_for

import db
import engine

app = Flask(__name__)
app.secret_key = "dev-only"


def get_conn():
    if not db.DB_PATH.exists():
        c = db.connect()
        db.init_db(c)
        return c
    return db.connect()


def current_state():
    conn = get_conn()
    runs = engine.load_runs(conn)
    raw = request.args.get("as_of") or os.environ.get("AS_OF")
    if raw == "now":
        as_of = datetime.now().replace(microsecond=0)
    elif raw:
        as_of = datetime.strptime(raw, engine.ISO)
    else:
        as_of = engine.default_as_of(runs)
    engine.evaluate(runs, as_of)
    return conn, runs, as_of


@app.route("/")
def dashboard():
    conn, runs, as_of = current_state()
    done = {r["run_id"]: r for r in conn.execute("SELECT * FROM retry_actions")}
    order = {"failed": 0, "suspect": 1, "unknown": 2, "recovered": 3, "in_progress": 4, "delivered": 5}
    runs.sort(key=lambda r: (order[r.verdict], r.scheduled_at, r.run_id))
    return render_template("dashboard.html", runs=runs, summary=engine.summarize(runs),
                           tenants=engine.tenant_health(runs), as_of=as_of, done=done,
                           max_attempts=engine.MAX_ATTEMPTS)


@app.post("/retry/<run_id>")
def retry(run_id):
    conn, runs, as_of = current_state()
    run = next((r for r in runs if r.run_id == run_id), None)
    if not run or run.action != "RETRY":
        flash(f"{run_id} is not eligible for an automatic retry.", "warn")
        return redirect(url_for("dashboard"))
    try:
        # Simulated runner: in production this is the call to the job runner's API.
        conn.execute("INSERT INTO retry_actions (run_id, attempt_number, mode, reason) VALUES (?,?,?,?)",
                     (run.run_id, run.next_attempt, "simulated", run.reason))
        conn.commit()
        flash(f"Retry queued for {run_id} as attempt {run.next_attempt} (simulated).", "ok")
    except sqlite3.IntegrityError:
        flash(f"Attempt {run.next_attempt} of {run_id} was already queued. Nothing sent twice.", "warn")
    return redirect(url_for("dashboard"))


@app.post("/retry-all")
def retry_all():
    conn, runs, as_of = current_state()
    sent = 0
    for run in runs:
        if run.action == "RETRY":
            try:
                conn.execute("INSERT INTO retry_actions (run_id, attempt_number, mode, reason) VALUES (?,?,?,?)",
                             (run.run_id, run.next_attempt, "simulated", run.reason))
                sent += 1
            except sqlite3.IntegrityError:
                pass
    conn.commit()
    flash(f"{sent} retry(ies) queued (simulated)." if sent else "No new retries to queue.", "ok" if sent else "warn")
    return redirect(url_for("dashboard"))


@app.post("/reset")
def reset():
    db.init_db(db.connect())
    flash("Demo data reloaded and retry log cleared.", "ok")
    return redirect(url_for("dashboard"))


if __name__ == "__main__":
    app.run(debug=True, port=5000)
