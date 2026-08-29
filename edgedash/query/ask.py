"""Two-call natural language query pipeline for EdgeDash with abuse guards.

Enforces Rule 42: Model appears exactly twice (ROUTE and PHRASE).
Enforces Rule 43: Phrasing uses only numbers present in returned rows.
Enforces Rule 45: If no tool matches, returns fixed listing of available tools.
Enforces Abuse Guards: Session rate limiting, input sanitization/length/injection checks, and global daily cap.
"""

import json
import time
from dataclasses import dataclass
from typing import Any

from edgedash import llm, storage
from edgedash.config import Config, load_config
from edgedash.query.tools import TOOLS


@dataclass
class Answer:
    text: str
    rows: list[dict[str, Any]]
    tool_used: str | None
    params: dict[str, Any]


ROUTER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "tool": {
            "type": ["string", "null"],
            "description": "Exact name of matching query tool, or null if no tool matches.",
        },
        "params": {
            "type": "object",
            "description": "Key-value dictionary of parameters to pass to the query tool.",
        },
        "confidence": {
            "type": "string",
            "enum": ["high", "low"],
            "description": "Confidence rating for routing decision.",
        },
    },
    "required": ["tool", "params", "confidence"],
    "additionalProperties": False,
}

PHRASER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "text": {
            "type": "string",
            "description": "2-3 sentences directly answering the user question based strictly on the retrieved rows.",
        }
    },
    "required": ["text"],
    "additionalProperties": False,
}

INJECTION_PATTERNS: list[str] = [
    "ignore previous",
    "system prompt",
    "you are now",
]


def _format_tools_registry() -> str:
    lines = []
    for name, spec in TOOLS.items():
        desc = spec.get("description", "")
        params = spec.get("parameters", {})
        lines.append(f"- Tool Name: {name}")
        lines.append(f"  Description: {desc}")
        lines.append(f"  Parameters Spec: {json.dumps(params)}")
    return "\n".join(lines)


def _format_unsupported_question_answer() -> str:
    lines = [
        "I cannot answer that question because no matching query tool is available for it.",
        "",
        "Here are the topics and tools you CAN ask about:",
    ]
    for name, spec in TOOLS.items():
        desc = spec.get("description", "")
        lines.append(f"- **{name}**: {desc}")
    return "\n".join(lines)


def build_routing_prompt(question: str) -> str:
    registry_text = _format_tools_registry()
    return f"""You are a precise query router for career intelligence data.
Your sole job is to select an available query tool from the registry below that matches the user's question, or return null if no tool matches.

AVAILABLE TOOLS REGISTRY:
{registry_text}

USER QUESTION: "{question}"

CRITICAL ROUTING RULES:
1. Select a tool ONLY if its description explicitly covers the user's question.
2. If NO tool matches the user's question, set "tool" to null.
3. DO NOT guess, extrapolate, or pick the "closest" tool if there is no exact fit.
4. DO NOT invent tools or parameters not listed in the registry.
5. Provide parameters matching the tool's parameter specification.
"""


def build_phrasing_prompt(question: str, summary: str, rows: list[dict[str, Any]]) -> str:
    rows_json = json.dumps(rows, indent=2)
    return f"""You are a phrasing assistant for career intelligence query results.

USER QUESTION: "{question}"
DATA RETRIEVAL SUMMARY: "{summary}"
RETRIEVED ROWS DATA:
{rows_json}

CRITICAL PHRASING CONSTRAINTS (Rule 43):
1. Write 2-3 sentences providing a direct answer to the user's question using ONLY the provided RETRIEVED ROWS DATA.
2. Use ONLY the numbers and facts present in these rows. DO NOT estimate, extrapolate, add outside context, or infer values not present in the data.
3. If the retrieved rows are empty, state plainly that the database does not contain an answer or matching listings.
4. Incorporate the DATA RETRIEVAL SUMMARY so the user knows what context/listings were inspected.
"""


def check_session_rate_limit(
    session_history: list[float] | None = None,
    window_seconds: float = 600.0,
    max_requests: int = 10,
) -> float | None:
    """Checks session rate limit (max 10 requests per 10 minutes).
    Returns None if allowed, or wait_time_seconds if rate limited.
    """
    if session_history is None:
        return None

    now = time.time()
    # Remove timestamps older than window_seconds
    while session_history and (now - session_history[0]) >= window_seconds:
        session_history.pop(0)

    if len(session_history) >= max_requests:
        oldest = session_history[0]
        wait_seconds = max(1.0, window_seconds - (now - oldest))
        return wait_seconds

    session_history.append(now)
    return None


def sanitize_and_validate_input(question: str) -> tuple[str | None, str | None]:
    """Sanitizes question input and checks length/injection.
    Returns (cleaned_question, error_or_rejection_reason).
    """
    if not isinstance(question, str) or not question.strip():
        return None, "rejected: empty input"

    # Strip control characters (ord < 32 except newline, carriage return, tab)
    cleaned = "".join(ch for ch in question if ord(ch) >= 32 or ch in "\n\r\t").strip()
    if not cleaned:
        return None, "rejected: empty input"

    if len(cleaned) > 300:
        return cleaned, "rejected: input length"

    cleaned_lower = cleaned.lower()
    for pattern in INJECTION_PATTERNS:
        if pattern in cleaned_lower:
            return cleaned, "rejected: suspicious input"

    return cleaned, None


def ask(
    question: str,
    db_path: str = "edgedash.db",
    config: Config | None = None,
    session_history: list[float] | None = None,
) -> Answer:
    start_time = time.time()
    if config is None:
        config = load_config()

    # Guard 1: Session Rate Limit Check (max 10 per 10 mins, checked BEFORE routing)
    wait_secs = check_session_rate_limit(session_history=session_history, window_seconds=600.0, max_requests=10)
    if wait_secs is not None:
        wait_mins = int(wait_secs // 60)
        rem_secs = int(wait_secs % 60)
        time_str = f"{wait_mins}m {rem_secs}s" if wait_mins > 0 else f"{rem_secs}s"
        msg = f"Session rate limit exceeded (max 10 questions per 10 minutes). Please wait {time_str} before asking another question."
        storage.log_query(
            db_path=db_path,
            question=question[:300] if question else "",
            tool_chosen="rejected: rate limit",
            params={"wait_seconds": round(wait_secs, 1)},
            answerable=False,
            duration_ms=(time.time() - start_time) * 1000.0,
        )
        return Answer(
            text=msg,
            rows=[],
            tool_used="rejected: rate limit",
            params={"wait_seconds": round(wait_secs, 1)},
        )

    # Guard 2: Input Guards (Empty, Control chars, Length > 300, Instruction Injection)
    cleaned_q, rejection_reason = sanitize_and_validate_input(question)
    if rejection_reason is not None:
        storage.log_query(
            db_path=db_path,
            question=question[:300] if question else "",
            tool_chosen=rejection_reason,
            params={"reason": rejection_reason},
            answerable=False,
            duration_ms=(time.time() - start_time) * 1000.0,
        )

        if rejection_reason == "rejected: empty input":
            text = "Please enter a valid question."
        elif rejection_reason == "rejected: input length":
            text = "Question is too long (maximum 300 characters allowed)."
        elif rejection_reason == "rejected: suspicious input":
            # Standard can't-answer message, do NOT explain filter in response
            text = _format_unsupported_question_answer()
        else:
            text = "Question rejected."

        return Answer(
            text=text,
            rows=[],
            tool_used=rejection_reason,
            params={"reason": rejection_reason},
        )

    # Guard 3: Global Daily Cap Check
    today_count = storage.count_queries_today(db_path=db_path)
    if today_count >= config.daily_ask_cap:
        msg = f"The global daily limit of {config.daily_ask_cap} questions has been reached. The ask feature is temporarily paused to preserve resources. Please check back tomorrow or view the verified data panels below."
        storage.log_query(
            db_path=db_path,
            question=cleaned_q,
            tool_chosen="rejected: daily cap",
            params={"daily_cap": config.daily_ask_cap, "current_count": today_count},
            answerable=False,
            duration_ms=(time.time() - start_time) * 1000.0,
        )
        return Answer(
            text=msg,
            rows=[],
            tool_used="rejected: daily cap",
            params={"daily_cap": config.daily_ask_cap},
        )

    # Step 1: ROUTE Call
    routing_prompt = build_routing_prompt(cleaned_q)
    route_res = llm.complete_json(
        prompt=routing_prompt,
        schema=ROUTER_SCHEMA,
        config=config,
    )

    chosen_tool = route_res.get("tool")
    params = route_res.get("params", {})
    if not isinstance(params, dict):
        params = {}

    # Handle null / empty tool choice
    if chosen_tool is None or chosen_tool == "" or str(chosen_tool).lower() == "null":
        duration_ms = (time.time() - start_time) * 1000.0
        storage.log_query(
            db_path=db_path,
            question=cleaned_q,
            tool_chosen=None,
            params=params,
            answerable=False,
            duration_ms=duration_ms,
        )
        return Answer(
            text=_format_unsupported_question_answer(),
            rows=[],
            tool_used=None,
            params=params,
        )

    # Validate returned tool name is in TOOLS registry (hard error per rule)
    if chosen_tool not in TOOLS:
        raise ValueError(
            f"Router returned invalid tool name '{chosen_tool}' not present in registered TOOLS registry."
        )

    # Step 2: EXECUTE Tool
    tool_spec = TOOLS[chosen_tool]
    tool_func = tool_spec["func"]

    # Call tool function with params and db_path
    tool_result = tool_func(**params, db_path=db_path)
    summary = str(tool_result.get("summary", ""))
    rows = tool_result.get("rows", [])
    if not isinstance(rows, list):
        rows = []

    # Step 3: PHRASE Call
    phrasing_prompt = build_phrasing_prompt(cleaned_q, summary, rows)
    phrase_res = llm.complete_json(
        prompt=phrasing_prompt,
        schema=PHRASER_SCHEMA,
        config=config,
    )
    answer_text = str(phrase_res.get("text", "")).strip()

    duration_ms = (time.time() - start_time) * 1000.0
    storage.log_query(
        db_path=db_path,
        question=cleaned_q,
        tool_chosen=chosen_tool,
        params=params,
        answerable=True,
        duration_ms=duration_ms,
    )

    return Answer(
        text=answer_text,
        rows=rows,
        tool_used=chosen_tool,
        params=params,
    )
