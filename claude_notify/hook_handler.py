"""Hook handler for Claude Code integration"""

import json
import logging
import os
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .notifier import ClaudeNotifier
from .telegram import TelegramNotifier
from .transcript import SessionSummary, format_preview, summarize_transcript

logger = logging.getLogger(__name__)


class HookHandler:
    """Process Claude Code hook events and send appropriate notifications"""

    def __init__(
        self,
        notifier: Optional[ClaudeNotifier] = None,
        telegram: Optional[TelegramNotifier] = None,
        desktop_enabled: bool = True
    ):
        self.notifier = notifier or ClaudeNotifier()
        self.telegram = telegram
        # When False, the desktop channel is suppressed and notifications go
        # out over Telegram only (a Telegram-only activation). Telegram remains
        # an opt-in, best-effort channel regardless of this flag.
        self.desktop_enabled = desktop_enabled

        # Define notification templates for different hook events
        self.event_templates = {
            "PreToolUse": {
                "title": "Claude Tool Request",
                "message": "Claude wants to use {tool_name}",
                "urgency": "normal"
            },
            "PostToolUse": {
                "title": "Claude Tool Complete",
                "message": "{tool_name} execution completed",
                "urgency": "low"
            },
            "Notification": {
                "title": "Claude Notification",
                "message": "Claude has sent a notification",
                "urgency": "normal"
            },
            "Stop": {
                "title": "Claude Response Complete",
                "message": "Claude has finished responding",
                "urgency": "normal"
            },
            "SubagentStop": {
                "title": "Claude Task Complete",
                "message": "Claude subagent has finished",
                "urgency": "low"
            }
        }

        # Special handling for certain tools
        self.critical_tools = ["Bash", "Write", "Edit", "MultiEdit"]

    def process_hook_event(self, event_type: str, data: Dict[str, Any]) -> bool:
        """
        Process a hook event and send appropriate notification

        Args:
            event_type: Type of hook event (PreToolUse, PostToolUse, etc.)
            data: JSON data from the hook

        Returns:
            bool: True if notification was sent successfully
        """
        # Completion events get a transcript-derived summary (last response and
        # turn duration); other events fire too often to justify the file read.
        summary: Optional[SessionSummary] = None
        if event_type in ("Stop", "SubagentStop"):
            transcript_path = data.get("transcript_path")
            if transcript_path:
                summary = summarize_transcript(transcript_path)

        project_name, project_path = self._resolve_project(data, summary)

        if event_type in ("Stop", "SubagentStop"):
            title, message, urgency = self._compose_completion(
                event_type, project_name, project_path, summary
            )
        elif event_type in ("PreToolUse", "PostToolUse"):
            title, message, urgency = self._compose_tool(
                event_type, data, project_name, project_path
            )
        else:
            title, message, urgency = self._compose_generic(
                event_type, project_name, project_path
            )

        # Fan out across every enabled channel (desktop + Telegram)
        return self._dispatch(
            title, message, urgency, sound=(urgency in ("normal", "critical"))
        )

    def _resolve_project(
        self, data: Dict[str, Any], summary: Optional[SessionSummary]
    ) -> Tuple[Optional[str], Optional[str]]:
        """Resolve the project as ``(name, path)`` from the working directory.

        Every Claude Code hook payload carries ``cwd`` (the project root), and
        the transcript repeats it, so a parsed summary provides a fallback. The
        hook process's own working directory is the last resort. The encoded
        ``~/.claude*/projects/<dir>`` directory name is intentionally *not*
        decoded: it flattens path separators into dashes and cannot be reversed
        unambiguously.
        """
        cwd = data.get("cwd") or (summary.cwd if summary else None)
        if cwd:
            path = Path(cwd)
            return path.name, str(path)
        return self._project_from_process_cwd()

    def _project_from_process_cwd(self) -> Tuple[Optional[str], Optional[str]]:
        """Derive ``(name, path)`` from the hook process's working directory.

        Claude runs hooks from the project root, so the process CWD is a sound
        last resort when no ``cwd`` is present in the payload or transcript.
        """
        try:
            cwd = os.environ.get("PWD") or os.getcwd()
        except OSError:
            return None, None
        path = Path(cwd)
        return path.name, str(path)

    def _compose_completion(
        self,
        event_type: str,
        project_name: Optional[str],
        project_path: Optional[str],
        summary: Optional[SessionSummary],
    ) -> Tuple[str, str, str]:
        """Build the notification for a Stop / SubagentStop event.

        The body answers what a completion alert is for: what Claude last said,
        how long the turn took, and which project — without repeating the opaque
        session id that previously dominated the message.
        """
        base = "Response complete" if event_type == "Stop" else "Subagent complete"
        title = f"✅ {base}"
        if project_name:
            title = f"{title} · {project_name}"

        lines = []
        if summary and summary.last_response:
            lines.append(format_preview(summary.last_response))
            lines.append("")  # blank line separating the response from metadata
        if summary and summary.duration is not None:
            lines.append(f"⏱ {self._format_duration(summary.duration)}")
        if project_path:
            lines.append(f"📁 {project_path}")

        message = "\n".join(lines).strip() or base
        return title, message, "normal"

    def _compose_tool(
        self,
        event_type: str,
        data: Dict[str, Any],
        project_name: Optional[str],
        project_path: Optional[str],
    ) -> Tuple[str, str, str]:
        """Build the notification for a PreToolUse / PostToolUse event."""
        template = self.event_templates[event_type]
        title = template["title"]
        urgency = template["urgency"]
        tool_name = data.get("tool_name", "Unknown Tool")
        message = template["message"].format(tool_name=tool_name)

        # Critical tools awaiting approval warrant a louder, reviewable alert.
        if tool_name in self.critical_tools and event_type == "PreToolUse":
            urgency = "critical"
            title = f"⚠️ {title}"
            message = f"Claude wants to use {tool_name} - Review required!"

        if event_type == "PreToolUse" and "tool_input" in data:
            preview = self._get_tool_input_preview(tool_name, data["tool_input"])
            if preview:
                message = f"{message}\n{preview}"

        return self._with_project(title, message, urgency, project_name, project_path)

    def _compose_generic(
        self,
        event_type: str,
        project_name: Optional[str],
        project_path: Optional[str],
    ) -> Tuple[str, str, str]:
        """Build the notification for Notification and unrecognised events."""
        template = self.event_templates.get(event_type)
        if template:
            title = template["title"]
            message = template["message"]
            urgency = template["urgency"]
        else:
            title = "Claude Event"
            message = f"Unknown event: {event_type}"
            urgency = "normal"

        return self._with_project(title, message, urgency, project_name, project_path)

    @staticmethod
    def _with_project(
        title: str,
        message: str,
        urgency: str,
        project_name: Optional[str],
        project_path: Optional[str],
    ) -> Tuple[str, str, str]:
        """Append the project name to the title and its full path to the body."""
        if project_name:
            title = f"{title} · {project_name}"
        if project_path:
            message = f"{message}\n📁 {project_path}"
        return title, message, urgency

    @staticmethod
    def _format_duration(duration: timedelta) -> str:
        """Render a turn duration compactly (e.g. ``45s``, ``3m 2s``, ``1h 4m``)."""
        total_seconds = int(duration.total_seconds())
        if total_seconds < 60:
            return f"{total_seconds}s"
        minutes, seconds = divmod(total_seconds, 60)
        if minutes < 60:
            return f"{minutes}m {seconds}s"
        hours, minutes = divmod(minutes, 60)
        return f"{hours}h {minutes}m"

    def _dispatch(
        self,
        title: str,
        message: str,
        urgency: str,
        sound: bool = True
    ) -> bool:
        """Fan a notification out to every enabled channel.

        Desktop is gated by ``desktop_enabled`` so a Telegram-only activation
        can suppress it; Telegram is an additional, best-effort channel. Returns
        ``True`` when *any* channel accepted the notification. Neither channel
        is allowed to raise, preserving the non-blocking hook contract.
        """
        desktop_success = False
        if self.desktop_enabled:
            desktop_success = self.notifier.send_notification(
                title=title,
                message=message,
                urgency=urgency,
                sound=sound
            )

        telegram_success = self._send_telegram(title, message, urgency)
        return desktop_success or telegram_success

    def _send_telegram(self, title: str, message: str, urgency: str) -> bool:
        """Best-effort fan-out to Telegram; never affects the hook exit path

        Returns whether Telegram accepted the message (``False`` when no
        Telegram notifier is configured). ``TelegramNotifier.send_notification``
        already swallows its own transport errors; this guard additionally keeps
        any unexpected error from escaping the non-blocking hook contract.
        """
        if self.telegram is None or not self.telegram.is_configured():
            return False
        try:
            return self.telegram.send_notification(
                title=title, message=message, urgency=urgency
            )
        except Exception as e:
            logger.warning("Telegram fan-out failed: %s", e)
            return False

    def _get_tool_input_preview(
        self, tool_name: str, tool_input: Dict[str, Any]
    ) -> Optional[str]:
        """Get a preview of tool input for the notification"""
        if tool_name == "Bash":
            command = tool_input.get("command", "").strip()
            if len(command) > 50:
                command = command[:47] + "..."
            return f"Command: {command}"

        elif tool_name in ["Write", "Edit", "MultiEdit"]:
            file_path = tool_input.get("file_path", "")
            if file_path:
                return f"File: {file_path}"

        elif tool_name == "Read":
            file_path = tool_input.get("file_path", "")
            if file_path:
                return f"Reading: {file_path}"

        return None

    def read_stdin_json(self) -> Optional[Dict[str, Any]]:
        """Read JSON data from stdin"""
        try:
            # Read all input from stdin
            input_data = sys.stdin.read()
            if not input_data:
                return None

            # Parse JSON
            return json.loads(input_data)
        except json.JSONDecodeError as e:
            logger.error("Failed to parse hook JSON from stdin: %s", e)
            return None
        except Exception as e:
            logger.error("Failed to read hook input from stdin: %s", e)
            return None

    def determine_event_type(self, data: Dict[str, Any]) -> Optional[str]:
        """
        Determine the event type from the hook data

        Claude hooks don't always include the event type in the JSON,
        so we need to infer it from the data structure
        """
        # Check for explicit event type
        if "event_type" in data:
            return data["event_type"]

        # Infer from data structure
        if "tool_name" in data:
            if "tool_response" in data:
                return "PostToolUse"
            else:
                return "PreToolUse"

        # Check for notification-specific fields
        if "notification_type" in data:
            return "Notification"

        # Default to Stop if we have session info but no tool info
        if "session_id" in data and "tool_name" not in data:
            return "Stop"

        return None
