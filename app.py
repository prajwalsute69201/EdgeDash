"""app.py — EdgeDash Agent Activity Dashboard (Streamlit)

Read-only dashboard. Never writes to listings/cycles and never runs execution cycles (Rule 49).
Enforces Rule 38: Top listings & gap panels read from the last passing cycle only.
Activity Log displays ALL cycles (including degraded/failed) to surface errors.
Enforces Rule 50: Robust startup under empty, unreachable, or mid-migration database conditions.
Enforces Rule 48: Zero secret leaks in UI, error banners, or logs.
"""

import logging
from pathlib import Path
from typing import Any
import streamlit as st

from edgedash import storage
from edgedash.config import load_config

logger = logging.getLogger("edgedash.app")

# --- Page Configuration & Styling ---
st.set_page_config(
    page_title="EdgeDash — Agent Activity Dashboard",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .main .block-container { padding-top: 1.5rem; padding-bottom: 2rem; }
    .stMetric, div[data-testid="stMetric"] {
        background-color: #1e222d !important;
        padding: 1rem 1.2rem !important;
        border-radius: 8px !important;
        border: 1px solid #2e3440 !important;
    }
    .stMetric [data-testid="stMetricLabel"],
    .stMetric [data-testid="stMetricLabel"] *,
    div[data-testid="stMetricLabel"],
    div[data-testid="stMetricLabel"] * {
        color: #94a3b8 !important;
        font-weight: 600 !important;
    }
    .stMetric [data-testid="stMetricValue"],
    .stMetric [data-testid="stMetricValue"] *,
    div[data-testid="stMetricValue"],
    div[data-testid="stMetricValue"] * {
        color: #ffffff !important;
        font-weight: 700 !important;
    }
    .warning-banner {
        background-color: #3b1e1e;
        color: #ff6b6b;
        padding: 1rem 1.2rem;
        border-radius: 8px;
        border-left: 6px solid #ff4d4d;
        margin-bottom: 1.5rem;
        font-weight: 500;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# --- Cached Storage Reads (Short TTL) ---
@st.cache_data(ttl=10)
def fetch_passing_cycle(db_path: str) -> dict[str, Any] | None:
    try:
        return storage.get_latest_passing_cycle(db_path)
    except Exception:
        logger.error("Failed to fetch passing cycle", exc_info=True)
        return None


@st.cache_data(ttl=10)
def fetch_recent_cycles(db_path: str, limit: int = 30) -> list[dict[str, Any]]:
    try:
        return storage.get_recent_cycles(db_path, limit=limit)
    except Exception:
        logger.error("Failed to fetch recent cycles", exc_info=True)
        return []


@st.cache_data(ttl=10)
def fetch_state_metrics(db_path: str) -> dict[str, Any]:
    try:
        return storage.get_state_metrics(db_path)
    except Exception:
        logger.error("Failed to fetch state metrics", exc_info=True)
        return {}


@st.cache_data(ttl=10)
def fetch_top_listings(db_path: str, limit: int = 10) -> list[dict[str, Any]]:
    try:
        return storage.get_scored_listings(db_path)[:limit]
    except Exception:
        logger.error("Failed to fetch top listings", exc_info=True)
        return []


@st.cache_data(ttl=10)
def fetch_top_gaps(db_path: str, limit: int = 10) -> list[dict[str, Any]]:
    try:
        return storage.get_latest_gap_snapshot(db_path)[:limit]
    except Exception:
        logger.error("Failed to fetch top gaps", exc_info=True)
        return []


def parse_notes(notes: str | None) -> dict[str, str]:
    if not notes:
        return {}
    res = {}
    for part in notes.split(" | "):
        if "=" in part:
            k, v = part.split("=", 1)
            res[k.strip()] = v.strip()
    return res


# --- Load Config & Resolve DB Path ---
try:
    config = load_config()
    db_path = config.db_path
except Exception:
    logger.warning("Failed to load config, defaulting to edgedash.db", exc_info=True)
    db_path = "edgedash.db"


# --- Main Dashboard ---
st.title("⚡ EdgeDash — Agent Activity Dashboard")
st.caption("Read-only monitoring console for scheduled execution cycles & output verification.")

# Test Database Connection / Initialization (Rule 50)
db_online = True
try:
    storage.init_db(db_path)
except Exception:
    logger.error("Database connection / init failed", exc_info=True)
    db_online = False

if not db_online:
    st.warning("⚠️ **Database Status**: Database is currently unavailable or initializing. The dashboard will update automatically when database access is restored.")
    st.stop()

# Fetch Core State
recent_cycles = fetch_recent_cycles(db_path, limit=30)
last_passing = fetch_passing_cycle(db_path)
metrics = fetch_state_metrics(db_path)

# Empty Database / No Cycles Handling (Rule 50)
if not recent_cycles and not last_passing:
    st.info("ℹ️ **No cycles recorded yet** — first run is scheduled for 09:00 UTC. The dashboard will populate automatically when the agent pipeline completes its first cycle.")
    st.markdown("---")
    st.markdown(
        """
        <div style="text-align: center; color: #64748b; font-size: 0.85rem; padding: 1rem 0;">
            ⚡ <b>EdgeDash Monitoring Console</b> | Last Verified Cycle: <b>None</b> |
            <a href="https://github.com/username/edgedash" target="_blank" style="color: #00adb5; text-decoration: none;">GitHub Repository</a>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.stop()


# ==============================================================================
# SECTION 1: HEADER STRIP (Dashboard Metrics)
# ==============================================================================
try:
    newest_cycle = recent_cycles[0] if recent_cycles else {}
    newest_notes = parse_notes(newest_cycle.get("notes"))
    newest_outcome = newest_notes.get("outcome") or newest_cycle.get("status", "unknown")
    newest_verdict = newest_notes.get("verdict") or ("pass" if newest_outcome in ("complete", "nothing_to_do") else "fail")

    last_passing_ts = last_passing.get("finished_at", "None")[:19] if last_passing else "None"
    total_listings = metrics.get("total_listings", 0)
    total_scored = metrics.get("total_scored", 0)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Last Verified Cycle", last_passing_ts)
    with col2:
        st.metric("Total Listings", f"{total_listings:,}")
    with col3:
        st.metric("Total Scored", f"{total_scored:,}")
    with col4:
        verdict_display = f"{newest_verdict.upper()} ({newest_outcome.upper()})"
        st.metric("Newest Cycle Status", verdict_display)

    if newest_outcome == "degraded" or newest_verdict == "fail":
        st.markdown(
            f"""
            <div class="warning-banner">
                ⚠️ <b>STALE DATA WARNING (Rule 38)</b>: The newest cycle at <code>{newest_cycle.get('finished_at', '')[:19]}</code>
                ended with status <b>{newest_outcome.upper()}</b> (Verdict: <code>{newest_verdict}</code>).
                <br/>All listing scores and skill gaps below are preserved from the last known-good verified cycle at <b>{last_passing_ts}</b>.
            </div>
            """,
            unsafe_allow_html=True,
        )
except Exception:
    logger.error("Header strip error", exc_info=True)
    st.error("⚠️ Header metrics temporarily unavailable.")

st.markdown("---")


# ==============================================================================
# SECTION 2: ASK YOUR DATA (Natural Language Queries)
# ==============================================================================
try:
    st.subheader("💬 Ask Your Data (Natural Language Queries)")
    st.caption("Parameterised, read-only query pipeline operating on verified data per Rules 40-46.")

    queries_today = 0
    try:
        queries_today = storage.count_queries_today(db_path)
    except Exception:
        pass

    daily_cap = getattr(config, "daily_ask_cap", 200) if "config" in locals() else 200
    is_cap_reached = queries_today >= daily_cap

    if "ask_session_history" not in st.session_state:
        st.session_state.ask_session_history = []

    if is_cap_reached:
        st.warning(
            f"⚠️ The global daily question limit has been reached ({queries_today}/{daily_cap}). "
            "The ask feature is temporarily paused to preserve resources. "
            "All verified data panels below remain fully functional."
        )

    st.write("**Try an example question:**")
    col_q1, col_q2, col_q3 = st.columns(3)
    selected_example = None

    with col_q1:
        if st.button("🏢 Which companies are hiring?", use_container_width=True, disabled=is_cap_reached):
            selected_example = "Which companies are hiring?"

    with col_q2:
        if st.button("🎯 Show my best job matches", use_container_width=True, disabled=is_cap_reached):
            selected_example = "Show my best job matches"

    with col_q3:
        if st.button("⚡ What are my top skill gaps?", use_container_width=True, disabled=is_cap_reached):
            selected_example = "What are my top skill gaps?"

    default_query = selected_example or ""
    user_question = st.text_input(
        "Ask a question about your listings, scores, or skill gaps:",
        value=default_query,
        disabled=is_cap_reached,
        placeholder="e.g. Which companies are hiring?" if not is_cap_reached else "Daily limit reached",
    )

    if user_question and not is_cap_reached:
        with st.spinner("Routing & executing query..."):
            try:
                from edgedash.query.ask import ask
                ans = ask(
                    user_question,
                    db_path=db_path,
                    config=config if "config" in locals() else None,
                    session_history=st.session_state.ask_session_history,
                )

                st.markdown("### Answer")
                if ans.tool_used and ans.tool_used.startswith("rejected:"):
                    st.warning(ans.text)
                    st.caption(f"🛡️ **Query Guard Action**: `{ans.tool_used}`")
                else:
                    st.info(ans.text)
                    if ans.tool_used:
                        st.caption(f"🔧 **Tool Executed**: `{ans.tool_used}` | **Parameters**: `{ans.params}`")

                    st.markdown("#### 📊 Underlying Data Rows (Rule 44)")
                    if ans.rows:
                        st.dataframe(ans.rows, use_container_width=True)
                    else:
                        st.caption("No data rows returned for this query.")
            except Exception:
                logger.error("Ask query execution error", exc_info=True)
                st.error("Query processing encountered an issue. Please try rephrasing your question.")
except Exception:
    logger.error("Ask panel error", exc_info=True)
    st.error("⚠️ Ask panel temporarily unavailable.")

st.markdown("---")


# ==============================================================================
# SECTION 3: AGENT ACTIVITY LOG (Most Recent 30 Cycles)
# ==============================================================================
try:
    st.subheader("📋 Agent Activity Log (Most Recent 30 Cycles)")
    st.caption("Surfaces all execution cycles including degraded and failed runs for auditing.")

    table_rows = []
    for c in recent_cycles:
        notes_dict = parse_notes(c.get("notes"))
        outcome = notes_dict.get("outcome") or c.get("status", "unknown")
        verdict = notes_dict.get("verdict") or ("pass" if outcome in ("complete", "nothing_to_do") else "fail")
        failed_checks = notes_dict.get("failed_checks", "none").strip("[]")
        retries = notes_dict.get("retries", "0")
        ran = notes_dict.get("ran", "none").strip("[]")
        skipped = notes_dict.get("skipped", "none").strip("[]")
        durations = notes_dict.get("durations", "none").strip("[]")
        timestamp = c.get("finished_at", "")[:19]

        if outcome == "complete" and verdict == "pass":
            badge = "🟢 COMPLETE (Pass)"
        elif outcome == "nothing_to_do":
            badge = "⚪ NO WORK (Pass)"
        elif outcome == "degraded":
            badge = "🔴 DEGRADED (Fail)"
        elif outcome == "partial":
            badge = "🟡 PARTIAL"
        else:
            badge = f"🟠 {outcome.upper()}"

        table_rows.append(
            {
                "Timestamp": timestamp,
                "Outcome": badge,
                "Verdict": verdict.upper(),
                "Retries": retries,
                "Failed Check & Observed Value": failed_checks,
                "Agents Run": ran,
                "Skipped": skipped,
                "Durations": durations,
            }
        )

    if table_rows:
        st.dataframe(
            table_rows,
            use_container_width=True,
            column_config={
                "Timestamp": st.column_config.TextColumn("Timestamp", width="medium"),
                "Outcome": st.column_config.TextColumn("Outcome & Status", width="medium"),
                "Verdict": st.column_config.TextColumn("Verdict", width="small"),
                "Retries": st.column_config.TextColumn("Retries", width="small"),
                "Failed Check & Observed Value": st.column_config.TextColumn("Failed Check & Observed Value", width="large"),
                "Agents Run": st.column_config.TextColumn("Agents Run", width="medium"),
                "Skipped": st.column_config.TextColumn("Skipped", width="medium"),
                "Durations": st.column_config.TextColumn("Durations", width="medium"),
            },
            hide_index=True,
        )
    else:
        st.info("No execution cycles recorded.")
except Exception:
    logger.error("Activity log panel error", exc_info=True)
    st.error("⚠️ Activity log panel temporarily unavailable.")

st.markdown("---")


# ==============================================================================
# SECTION 4: COMPACT PANELS (Top Scored Listings & Top Skill Gaps)
# ==============================================================================
col_left, col_right = st.columns(2)

with col_left:
    try:
        st.subheader("🎯 Top 10 Scored Listings (Verified Data)")
        st.caption("Derived from the last verified passing cycle per Rule 38.")
        top_listings = fetch_top_listings(db_path, limit=10)

        if top_listings:
            display_listings = []
            for l in top_listings:
                display_listings.append(
                    {
                        "Score": l.get("fit_score"),
                        "Title": l.get("title"),
                        "Company": l.get("company"),
                        "Reason": l.get("fit_reason"),
                    }
                )
            st.dataframe(
                display_listings,
                use_container_width=True,
                column_config={
                    "Score": st.column_config.NumberColumn("Score", format="%d"),
                    "Title": st.column_config.TextColumn("Title", width="medium"),
                    "Company": st.column_config.TextColumn("Company", width="small"),
                    "Reason": st.column_config.TextColumn("Reason", width="large"),
                },
                hide_index=True,
            )
        else:
            st.info("No scored listings found in verified data.")
    except Exception:
        logger.error("Top listings panel error", exc_info=True)
        st.error("⚠️ Top listings panel temporarily unavailable.")

with col_right:
    try:
        st.subheader("📊 Top 10 Skill Gaps (Verified Snapshot)")
        st.caption("Opportunity cost ranking from the last verified passing cycle.")
        top_gaps = fetch_top_gaps(db_path, limit=10)

        if top_gaps:
            display_gaps = []
            for rank, g in enumerate(top_gaps, 1):
                display_gaps.append(
                    {
                        "#": rank,
                        "Skill": g.get("skill"),
                        "Blocked": g.get("listings_blocked"),
                        "Opp. Cost": f"{float(g.get('opportunity_cost', 0.0)):.2f}",
                        "Confidence": g.get("confidence", "normal"),
                    }
                )
            st.dataframe(
                display_gaps,
                use_container_width=True,
                column_config={
                    "#": st.column_config.NumberColumn("#", format="%d"),
                    "Skill": st.column_config.TextColumn("Skill", width="medium"),
                    "Blocked": st.column_config.NumberColumn("Blocked", format="%d"),
                    "Opp. Cost": st.column_config.TextColumn("Opp. Cost", width="small"),
                    "Confidence": st.column_config.TextColumn("Confidence", width="small"),
                },
                hide_index=True,
            )
        else:
            st.info("No skill gaps found in verified data.")
    except Exception:
        logger.error("Top gaps panel error", exc_info=True)
        st.error("⚠️ Top gaps panel temporarily unavailable.")

# ==============================================================================
# SECTION 5: FOOTER (Requirement 5)
# ==============================================================================
last_verified_ts = last_passing.get("finished_at", "None")[:19] if last_passing else "None"
st.markdown("---")
st.markdown(
    f"""
    <div style="text-align: center; color: #64748b; font-size: 0.85rem; padding: 1rem 0;">
        ⚡ <b>EdgeDash Dashboard</b> | Last Verified Cycle: <b>{last_verified_ts}</b> |
        <a href="https://github.com/username/edgedash" target="_blank" style="color: #00adb5; text-decoration: none;">GitHub Repository</a>
    </div>
    """,
    unsafe_allow_html=True,
)
