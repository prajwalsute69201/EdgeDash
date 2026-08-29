# EdgeDash Steering Rules

## Project Summary
**EdgeDash** is an autonomous AI career intelligence agent. It operates on a scheduled loop that fetches live job listings, scores them for fit against a user profile, surfaces skill gaps, verifies its own output, and publishes a Streamlit dashboard.

---

## System Architecture
The system follows a strict pipeline architecture. Do not deviate from this architecture without explicit user approval:

```
Trigger (Scheduled) ──► Orchestrator ──► Sub-Agents ──► Verifier ──► Storage ──► Dashboard (Read-Only)
                                        ├── Fetcher
                                        ├── Scorer
                                        └── GapAnalyzer
```

* **Orchestrator**: Reads state and delegates execution to sub-agents. The Orchestrator **never** fetches or scores directly.
* **Sub-Agents**: (`Fetcher`, `Scorer`, `GapAnalyzer`). Each sub-agent has exactly **one goal** and **one stop condition**.
* **Verifier**: Validates output prior to persistence.
* **Storage**: Single persistence boundary with a thin interface.
* **Dashboard**: Read-only visualization powered by Streamlit.

---

## Hard Rules

1. **Python 3.11+ & Standard Library First**:
   * Target Python **3.11+**.
   * Use the standard library first. Add an external dependency only when it genuinely saves real work.
   * **Always tell the user why** before adding any external dependency.

2. **Single Storage Boundary**:
   * **ALL** storage access must go through a single storage module exposing a thin, unified interface.
   * **No other module may import `sqlite3` directly.**
   * Swapping SQLite for hosted Postgres must require a change in **only this single storage file**.

3. **Config-Driven Profile & Role Data**:
   * **Never hardcode** user-specific values (role, city, keywords, skills profile, etc.).
   * Everything user-specific lives in external configuration.

4. **Zero Secrets in Code**:
   * No API keys, credentials, or secrets in source code.
   * Environment variables only, loaded in one centralized location.

5. **Mandatory Audit Trail (`cycle_log`)**:
   * Every agent run **must write a row** to the `cycle_log` table containing:
     * **What ran** (agent/task identifier)
     * **When** (timestamp)
     * **Records touched** (count)
     * **Status** (`pass` / `fail`)
     * **Retry reason** (if applicable)

6. **Fail Loudly**:
   * Absolutely **no bare `except: pass`** or silent error handling.
   * Errors must be raised or visibly surfaced so issues are immediately obvious.

7. **Type Hints & Docstring Discipline**:
   * **Type hints** are required on **every** function signature.
   * Write docstrings **only** where the intent is not obvious from the function/parameter names.

8. **File Line Count Limit**:
   * Keep files under **~150 lines**. Split modules before size becomes an issue.

### Network & Sources

9. **Source Isolation**:
   * Every external source lives behind a `Source` class with a uniform interface.
   * The `Fetcher` never contains source-specific parsing. Adding a source must never require editing the `Fetcher`.

10. **Normalized Output Schema**:
    * Every `Source` returns a list of normalized dicts with **EXACTLY** these keys: `source`, `external_id`, `title`, `company`, `location`, `url`, `description`, `posted_at`, `raw`.
    * Missing values are `None`, never empty string `""`, never `"N/A"`.

11. **Centralized Network Client**:
    * All network calls go through one helper with a timeout (10s default), explicit retry (2 attempts, exponential backoff), and a `User-Agent` header.
    * No bare `requests.get` anywhere else in the codebase.

12. **Resilient Failure Handling**:
    * A source failing must **NEVER** kill the cycle.
    * Catch errors per-source, log the failure to `cycle_log` with status `"failed"`, and continue to the next source. One dead job board must not stop other sources.

13. **Secret Isolation via Environment Variables**:
    * Secrets come from environment variables via a `.env` file that is gitignored.
    * Never a literal key in code, never a key in `config.yaml`.
    * If a key is missing, that source skips itself with a clear log line — it does not crash the cycle.

14. **Source Courtesy & Limits**:
    * Respect the source. Rate limit to at most 1 request per second per source, set a real `User-Agent`, and honor any documented page limits.

### Intelligence & Scoring

15. **Centralized LLM Module**:
    * All LLM calls go through one module, `edgedash/llm.py`, exposing one function. The provider and model name come from config, never hardcoded. Rate limit to stay inside a free tier (default 1 request per second, max 15 per minute). No other file imports an LLM SDK.

16. **Fact Extraction Only**:
    * NEVER ask a model for a final score, ranking, or numeric rating. The model extracts structured facts only. All scoring arithmetic is deterministic Python in ONE function. The model never sees the scoring weights.

17. **Schema Validation & Failure Isolation**:
    * Every model response is validated against an explicit schema before use. A response that fails validation is retried once, then logged as a failure for THAT listing only — it must not crash the cycle or stop the remaining listings. Never `json.loads` raw model text without a validation and repair path.

18. **Idempotent Scoring & Extraction Caching**:
    * Scoring is idempotent. Never re-score a listing that already has a score. Select only listings `WHERE score IS NULL`. Cache extraction results keyed on a hash of the job description so the same text is never sent to the model twice.

19. **Code-Generated Score Reasons**:
    * Every score carries a human-readable reason GENERATED FROM THE SCORE COMPONENTS by our code — never free text written by the model.

20. **Score Distribution Auditing**:
    * Log the score distribution (count, min, max, mean, spread) to `cycle_log` on every scoring run. A run where all scores fall within 10 points is a suspect run and must be logged as such.

21. **Batch Size Capping**:
    * Cap listings scored per cycle at a configurable batch size (default 25) so a cost or rate-limit blowup is structurally impossible.

### Aggregate Analysis

22. **Deterministic Aggregate Analysis**:
    * Aggregate analysis is deterministic SQL and Python. No LLM call may produce, adjust, or rank an aggregate number. A model may only SUGGEST canonical groupings for a human to approve.

23. **Explicit Canonical Skill Alias Map**:
    * Skill names are canonicalised through an explicit alias map in `config.yaml` that I own and can read. Never auto-merge skill names by model judgement or string similarity alone.

24. **Fit-Score Weighted Gap Ranking**:
    * Gap ranking is weighted by the fit score of the listing the gap came from. A gap in a listing I score 20 on is worth far less than a gap in a listing I score 85 on. Never rank gaps by raw frequency alone.

25. **Timestamped Report Snapshots**:
    * Every gap report run writes a timestamped SNAPSHOT. Never overwrite the previous report. Trend over time is a first-class output, not an afterthought.

26. **Row-Level Traceability**:
    * Every aggregate number must be traceable to the rows that produced it. Any reported gap must be able to list the specific listing IDs it was computed from. No number appears in the dashboard that I cannot drill into.

27. **Sample Size Reporting**:
    * Report the sample size alongside every aggregate. A gap computed from 3 listings and a gap computed from 90 listings must never be presented as equally reliable.

### Orchestration

28. **Dynamic Orchestration Execution**:
    * The Orchestrator reads system state and decides which agents to run. It never runs a fixed sequence. Skipping an agent because there is no work for it is a SUCCESSFUL outcome, not a failure.

29. **Explicit Delegation Boundaries**:
    * Every delegation carries an explicit goal and an explicit stop condition (max items, max duration). A sub-agent never decides its own limits — the Orchestrator sets them.

30. **Orchestrator Scope Separation**:
    * The Orchestrator never does an agent's work. It reads state, delegates, collects results, logs. No fetching, scoring, or analysis logic in the Orchestrator.

31. **Pre-Execution Plan Logging**:
    * The Orchestrator prints and logs its PLAN before executing it — which agents will run, which are skipped, and the state value that caused each decision.

32. **Partial Cycle Resiliency**:
    * One sub-agent failing does not stop the cycle. Log the failure, continue with the remaining plan, and mark the cycle partial.

33. **Cycle Summary Persistence**:
    * Every cycle writes exactly one summary row: what ran, what was skipped, why, duration per agent, and the outcome.

### Verification

34. **Plausibility-Only Judgment**:
    * The Verifier judges output plausibility and NEVER repairs, rewrites, or adjusts data. It returns a verdict and a reason. The Orchestrator decides what to do about a failure.

35. **Distribution & Shape Verification**:
    * Verification checks plausibility, never correctness. There is no ground truth for a fit score. Checks assert properties of the output distribution and shape, not the accuracy of any single value.

36. **Bounded Retry Limit**:
    * A failed verification triggers at most ONE retry of the failing agent with adjusted context. After that the cycle is marked "degraded" and stops. Never retry in an unbounded loop.

37. **Detailed Failure Logging**:
    * Every verdict is logged to `cycle_log` with the check that failed and the observed value that failed it — never just "failed".

38. **Verified Data Gatekeeping**:
    * Only cycles with a passing verdict may be read by the dashboard. A failed cycle must never overwrite the last known-good data. Stale verified data always beats fresh unverified data.

39. **Configurable Thresholds**:
    * Verification thresholds live in `config.yaml`, not in code, and every threshold has a comment saying what failure it is designed to catch.

### Natural Language Queries

40. **No Model-Generated SQL**:
    * NEVER generate SQL from a model. No text-to-SQL, ever, in any form.
    * The model selects from a fixed registry of parameterised query functions that I wrote. It never composes a query.

41. **Read-Only & Validated Query Tools**:
    * Every query tool is read-only, parameterised, and takes typed parameters that are validated and clamped to a safe range before execution. A model-supplied parameter is untrusted input.

42. **Two Model Calls Per Question (ROUTE & PHRASE)**:
    * The model appears exactly twice per question: once to ROUTE (pick a tool and its parameters) and once to PHRASE (turn returned rows into prose). It never touches the database in either call.

43. **Strict Phrasing Constraints**:
    * The phrasing call may use ONLY the numbers present in the rows it was given. It must not estimate, extrapolate, add outside context, or infer a value that is not in the data. If the rows are empty it must say so plainly.

44. **Mandatory Data Row Display**:
    * Every answer displays the underlying rows alongside it. No prose answer appears without the data that produced it.

45. **No Guessing or Fallback Answers**:
    * If no tool matches the question, say so and list what CAN be asked. Never guess at the closest tool and never answer from general knowledge.

46. **Last Passing Cycle Isolation**:
    * Query tools read from the last passing cycle only, per rule 38.

### Deployment

47. Never rely on the local filesystem for anything that must survive a
    restart. Hosting filesystems are ephemeral. All persistent state is in
    the hosted database.
48. Every secret comes from an environment variable read in one place.
    No secret is ever committed, printed, logged, or shown in an error
    message or traceback.
49. The scheduled job and the dashboard are separate processes that share
    only the database. The dashboard never runs a cycle; the scheduler
    never serves a page.
50. The deployed app must start and render even when the database is
    empty, unreachable, or mid-migration. It shows a clear status message
    instead of a stack trace. A stranger must never see a traceback.
51. The scheduled job is idempotent and safe to run twice. It must have a
    hard timeout and stay inside free-tier limits.


---

## Code Style & Development Workflow

* **Functions**: Write small, single-purpose, highly testable functions.
* **Code Clarity**: Prefer plain, readable Python over clever or obscure syntax.
* **Focused Building**: When requested to build one module, build **only** that module — do not scaffold the rest of the application.
