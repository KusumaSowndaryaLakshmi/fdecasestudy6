# Solution Design: Report Delivery Reliability

## The problem

Meridian's job runner logs every attempt of every scheduled report, but nobody reads the log. Tenants find missing reports before Meridian does. Sam wants a check that identifies which report runs never succeeded and retries the safe ones before a customer notices.

The log is attempt-level and a report is run-level, so the first job is to collapse attempts into one verdict per run. A failed attempt is not a failed report if a later attempt succeeded.

## Assumptions

1. **What counts as failed.** `failed`, `timed_out` and `error` are failures. `completed` is success. The starter kit listed only the first two, so a run with `error` would never be flagged. That is exactly the silent miss Sam described.
2. **Unknown statuses are not success.** Any status not in the mapping table is shown as "unknown" and sent to a person. New or misspelled statuses will appear in real logs, and guessing wrong either way is costly.
3. **A run succeeded if any attempt succeeded.** Not only the latest attempt.
4. **Retrying is safe** because report generation is idempotent and the tenant only receives a report on success. I could not verify this from the data; it is the first thing I would ask Sam.
5. **An empty "success" is suspect.** A completed attempt with zero rows may have delivered an empty statement. None exist in the sample, but it is cheap to catch.
6. **"Now" is the end of the dataset**, since the sample is from the past. Configurable.

## Approach

Raw attempts load into SQLite unchanged. A `status_map` table holds the failure definition, so changing what counts as failed is a data edit, not a code change. `engine.py` groups attempts by run and assigns one verdict: delivered, recovered, suspect, in progress, unknown, or failed. For failed runs it picks an action.

**Retry policy**

- Up to 3 attempts in total, matching what the data already shows. Beyond that, escalate.
- Backoff of 5 then 10 minutes, close to the gaps already in the log.
- **Two timeouts in a row escalate early.** An identical retry hits the same 300 second limit. Retrying again wastes budget and load on a job that is probably too big.
- Runs older than 72 hours are not retried automatically. A person decides whether a month-old statement is still wanted.
- Each retry is recorded with a unique key on run and attempt number, so a double click or two overlapping schedulers cannot send it twice.

**Output.** A dashboard puts the answer in the first sentence (how many runs never reached a customer, how many can be retried, how many need a person). Each run shows its attempts, the decision and the reason. A command-line report gives the same view.

**Cause hints.** Simple rules over status and duration. Timeouts followed by a hard failure point to volume or resource pressure (Gamma Health has the largest row counts in the data). Failures within seconds point to config or upstream data. These are labelled as hints.

## Trade-offs

- **Rules over an LLM for classification.** Rules are predictable, free and easy to explain. An LLM adds value only once there are real log messages to read; the sample has none.
- **Automatic retry, run on demand.** `python report.py --retry` makes the retry decisions and queues them with no human step, so it can go straight into cron. The dashboard buttons do the same by hand, which lets Meridian check the policy before trusting it. A built-in scheduler is future work.
- **Conservative escalation.** I would rather send a few extra runs to a person than retry something that cannot succeed.
- **SQLite and Flask.** Right for a take-home. Not what I would run in production (see below).

## With more time, data or budget

- Confirm idempotency and what the tenant sees on duplicate delivery.
- Run `report.py --retry` on a schedule and alert when a run is escalated, with the dashboard as the place to look.
- Call the real job runner API and read its response, instead of simulating.
- Use real error messages to separate transient causes (network, locks) from deterministic ones (bad config), and optionally have an LLM categorise them for the person reading the escalation.
- Tune thresholds per report from historical duration, for example a time limit based on each tenant's typical runtime.

## How this changes at scale

With thousands of tenants and many report types, loading everything and grouping in Python stops working. I would:

- Compute verdicts in SQL or a streaming job over only the recent window, with an index on run and status.
- Move to Postgres or a warehouse table, and use a queue with per-tenant rate limits so a bad night cannot flood the runner with retries.
- Alert on rates, not single runs: a tenant or a report type failing more than usual is a different problem from one flaky run.
- Keep the status mapping and thresholds in config per report type.
