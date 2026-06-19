"""Monitor Claude sessions for activity that requires user attention.

Claude Code stores each session as a JSONL transcript under
``~/.claude*/projects/<encoded-cwd>/<session>.jsonl`` (multiple home
directories — e.g. ``~/.claude`` and ``~/.claude-work`` — and
``$CLAUDE_CONFIG_DIR`` are all honoured). This monitor polls those files and,
when Claude has finished a turn and is awaiting the user with a question, an
explicit request, or a possible error, surfaces the session so the caller can
notify. State is tracked per file so each pause is reported once.

All transcript reading goes through :mod:`claude_notify.transcript`, the single
place that understands the JSONL schema; this module only applies the
attention policy on top of the resulting :class:`SessionSummary`.
"""

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .transcript import SessionSummary, summarize_transcript

logger = logging.getLogger(__name__)

# Only consider sessions touched within this window; older transcripts are
# almost certainly finished work the user has already moved on from.
RECENT_SESSION_WINDOW = timedelta(hours=24)

# Lower-cased substrings in Claude's final message that hint it is explicitly
# waiting on the user.
WAITING_HINTS = (
    "let me know",
    "would you like",
    "should i proceed",
    "shall i proceed",
    "please provide",
    "please confirm",
    "please specify",
    "could you clarify",
    "what would you like",
    "how would you like",
    "is there anything else",
    "waiting for your",
    "awaiting your",
)

# Lower-cased substrings that hint Claude reported a problem worth surfacing.
ERROR_HINTS = (
    "i was unable to",
    "i couldn't",
    "i could not",
    "i ran into an error",
    "the build failed",
    "permission denied",
)


class ClaudeSessionMonitor:
    """Monitor Claude sessions for activity requiring user attention."""

    def __init__(self) -> None:
        self.project_roots = self._find_project_roots()
        # Per-transcript state: last seen mtime and whether it needed attention.
        self.transcript_states: Dict[str, Dict[str, Any]] = {}

    def _find_project_roots(self) -> List[Path]:
        """Find every ``.../projects`` directory that holds session transcripts.

        Claude keeps transcripts under one or more home directories
        (``~/.claude``, ``~/.claude-work``, ...) plus an optional
        ``$CLAUDE_CONFIG_DIR``. Returns the existing ``projects`` subtrees,
        de-duplicated by resolved path.
        """
        candidates = list(Path.home().glob(".claude*"))
        config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
        if config_dir:
            candidates.append(Path(config_dir))

        roots: List[Path] = []
        seen: set[str] = set()
        for base in candidates:
            projects = base / "projects"
            try:
                resolved = str(projects.resolve())
            except OSError:
                continue
            if projects.is_dir() and resolved not in seen:
                seen.add(resolved)
                roots.append(projects)
        return roots

    def _get_active_sessions(self) -> List[Path]:
        """Return transcript files modified within the recency window."""
        now = datetime.now(tz=timezone.utc)
        sessions: List[Path] = []
        for projects in self.project_roots:
            for transcript in projects.glob("*/*.jsonl"):
                mtime = self._modified_at(transcript)
                if mtime is not None and now - mtime < RECENT_SESSION_WINDOW:
                    sessions.append(transcript)
        return sessions

    @staticmethod
    def _modified_at(path: Path) -> Optional[datetime]:
        """Return a file's mtime as an aware UTC datetime, or None if unreadable."""
        try:
            return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except OSError:
            return None

    def check_sessions(self) -> List[Dict[str, Any]]:
        """Check active sessions, returning those newly needing attention.

        Only transcripts whose mtime advanced since the last check are
        re-parsed, so a poll does no work for idle sessions.
        """
        needing_attention: List[Dict[str, Any]] = []

        for transcript in self._get_active_sessions():
            key = str(transcript)
            modified = self._modified_at(transcript)
            if modified is None:
                continue
            current_mtime = modified.timestamp()

            last_mtime = self.transcript_states.get(key, {}).get("mtime", 0.0)
            if current_mtime <= last_mtime:
                continue  # unchanged since last check

            summary = summarize_transcript(key)
            state = self._analyze(summary)
            self.transcript_states[key] = {
                "mtime": current_mtime,
                "needs_attention": state["needs_attention"],
                "last_check": time.time(),
            }

            if state["needs_attention"]:
                project_path = summary.cwd or str(transcript.parent)
                needing_attention.append({
                    "project": Path(project_path).name,
                    "project_path": project_path,
                    "transcript_path": key,
                    "reason": state["reason"],
                    "pattern": state["pattern"],
                    "last_response": summary.last_response,
                    "last_update": modified.strftime("%Y-%m-%d %H:%M:%S"),
                })

        return needing_attention

    @staticmethod
    def _analyze(summary: SessionSummary) -> Dict[str, Any]:
        """Decide whether a session needs attention from its summary.

        Claude awaiting the user (it spoke or acted last) is necessary but not
        sufficient: a plain "all done" is not an interruption. Attention is
        raised only when the final response also asks a question, makes an
        explicit request, or reports an error.
        """
        no_attention = {"needs_attention": False, "reason": None, "pattern": None}
        if not summary.awaiting_user or not summary.last_response:
            return no_attention

        response = summary.last_response.rstrip()
        lowered = response.lower()

        if response.endswith("?"):
            return {
                "needs_attention": True,
                "reason": "Claude asked a question",
                "pattern": "question",
            }
        if any(hint in lowered for hint in WAITING_HINTS):
            return {
                "needs_attention": True,
                "reason": "Claude is waiting for your input",
                "pattern": "waiting",
            }
        if any(hint in lowered for hint in ERROR_HINTS):
            return {
                "needs_attention": True,
                "reason": "Claude may have hit an issue",
                "pattern": "error",
            }
        return no_attention
