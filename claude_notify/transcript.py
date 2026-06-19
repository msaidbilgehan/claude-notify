"""Distill a Claude Code transcript into a human-readable session summary.

Claude Code records each session as a JSONL transcript: one JSON object per
line, each tagged with a ``type`` (``user``, ``assistant``, ``ai-title``, ...).
This module reduces that file to a :class:`SessionSummary` — the project
directory, the last assistant response, how long the final turn took, whether
Claude is now awaiting the user, and the session's AI-generated title — so both
the completion hook and the session monitor can report what actually happened
instead of an opaque session id.

The parser is deliberately forgiving. A transcript may be truncated mid-write,
contain partially flushed lines, or use fields this version does not recognise;
every such failure degrades to a missing field rather than an exception,
preserving the non-blocking contract of the callers.

Truncation is intentionally *not* applied here: the parser returns the full
last response so callers can analyse it (e.g. detect a trailing question), and
each caller shortens it for display with :func:`format_preview`.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Default preview length: short enough to stay glanceable in a desktop toast
# while remaining far below Telegram's 4096-character per-message ceiling.
MAX_RESPONSE_PREVIEW_CHARS = 280


@dataclass(frozen=True, slots=True)
class SessionSummary:
    """Facts distilled from a transcript; every field may be absent.

    Attributes:
        cwd: Working directory the session ran in (the real project path).
        last_response: The full final assistant text, stripped but not
            truncated. Use :func:`format_preview` to shorten it for display.
        duration: Wall-clock time of the last turn (last user prompt to the
            final assistant message).
        awaiting_user: True when the last conversational entry is from the
            assistant — Claude has spoken or acted last and the next move is the
            user's. False while Claude is mid-turn (the last entry is a user
            prompt or a tool result).
        title: The session's AI-generated title, when one was recorded.
    """

    cwd: Optional[str] = None
    last_response: Optional[str] = None
    duration: Optional[timedelta] = None
    awaiting_user: bool = False
    title: Optional[str] = None


def summarize_transcript(transcript_path: str) -> SessionSummary:
    """Read a transcript file and distill it into a :class:`SessionSummary`.

    The file is consumed in a single streaming pass that retains only the few
    facts a notification needs, so memory stays bounded regardless of transcript
    size. The function never raises: an unreadable file or malformed content
    yields an empty summary, honouring the callers' non-blocking contract.

    Args:
        transcript_path: Path to the JSONL transcript.

    Returns:
        A :class:`SessionSummary`; fields that could not be determined are None
        (or, for ``awaiting_user``, False).
    """
    cwd: Optional[str] = None
    title: Optional[str] = None
    last_response: Optional[str] = None
    last_user_ts: Optional[datetime] = None
    last_assistant_ts: Optional[datetime] = None
    last_role: Optional[str] = None

    try:
        with open(transcript_path, "r", encoding="utf-8") as handle:
            for line in handle:
                entry = _parse_line(line)
                if entry is None:
                    continue

                entry_cwd = entry.get("cwd")
                if entry_cwd:
                    cwd = entry_cwd

                entry_type = entry.get("type")
                if entry_type == "ai-title":
                    title = entry.get("aiTitle") or title
                elif entry_type == "assistant":
                    last_role = "assistant"
                    ts = _parse_timestamp(entry.get("timestamp"))
                    if ts is not None:
                        last_assistant_ts = ts
                    text = _assistant_text(entry)
                    if text:
                        last_response = text
                elif entry_type == "user" and not entry.get("isMeta"):
                    last_role = "user"
                    # Only a genuine prompt — not a tool result — starts a turn.
                    if "toolUseResult" not in entry:
                        ts = _parse_timestamp(entry.get("timestamp"))
                        if ts is not None:
                            last_user_ts = ts
    except OSError as e:
        # Missing/locked/partial file: a notification is best-effort, so report
        # what little we have rather than breaking the caller.
        logger.warning("Could not read transcript %s: %s", transcript_path, e)
        return SessionSummary()

    return SessionSummary(
        cwd=cwd,
        last_response=last_response,
        duration=_turn_duration(last_user_ts, last_assistant_ts),
        awaiting_user=last_role == "assistant",
        title=title,
    )


def format_preview(text: str, limit: int = MAX_RESPONSE_PREVIEW_CHARS) -> str:
    """Collapse whitespace and cap ``text`` at ``limit`` characters for display.

    Newlines and runs of spaces are collapsed to single spaces so the preview
    reads as one clean line in a notification. An ellipsis replaces the final
    character when the text is trimmed.
    """
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: max(limit - 1, 0)].rstrip() + "…"


def _parse_line(line: str) -> Optional[Dict[str, Any]]:
    """Parse one JSONL line into a dict, or None if blank/malformed."""
    line = line.strip()
    if not line:
        return None
    try:
        entry = json.loads(line)
    except json.JSONDecodeError:
        return None
    return entry if isinstance(entry, dict) else None


def _parse_timestamp(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601 transcript timestamp (e.g. ``2026-06-19T11:22:34.503Z``).

    Returns a timezone-aware datetime, or None when the value is missing or not
    a parseable timestamp.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _assistant_text(entry: Dict[str, Any]) -> Optional[str]:
    """Join the ``text`` blocks of an assistant entry, or None if it has none.

    Assistant content is a list of typed blocks (``thinking``, ``text``,
    ``tool_use``); only ``text`` blocks hold the user-facing response.
    """
    message = entry.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, list):
        return None

    texts = [
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    joined = "\n".join(text for text in texts if text).strip()
    return joined or None


def _turn_duration(
    start: Optional[datetime], end: Optional[datetime]
) -> Optional[timedelta]:
    """Elapsed time from the last user prompt to the final assistant message.

    Returns None when either endpoint is unknown, or when they are out of order
    (which would imply a malformed transcript rather than a real duration).
    """
    if start is None or end is None:
        return None
    delta = end - start
    return delta if delta.total_seconds() >= 0 else None
