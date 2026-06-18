"""Hook handler for Claude Code integration"""

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from .notifier import ClaudeNotifier
from .telegram import TelegramNotifier

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

    def _extract_project_info(self, data: Dict[str, Any]) -> Optional[str]:
        """Extract project directory from transcript path"""
        transcript_path = data.get("transcript_path", "")
        if not transcript_path:
            return self._get_current_project_fallback()

        # Convert to Path object for easier manipulation
        path = Path(transcript_path)

        # The transcript is typically in .claude/tmp/<session_id>/transcript.txt
        # We want to find the project root (parent of .claude)
        try:
            # Look for .claude in the path
            parts = path.parts
            for i, part in enumerate(parts):
                if part == ".claude":
                    if i > 0:
                        project_path = Path(*parts[:i])
                        project_name = parts[i-1]

                        # .claude under $HOME means a global Claude session
                        home_path = Path.home()
                        if project_path == home_path:
                            # This is a global Claude session, try to get actual project
                            return self._get_current_project_fallback()

                        # This is a project-specific .claude directory
                        return f"{project_name} ({project_path})"

            # If no .claude found, try to extract meaningful directory info
            # Look for common project indicators
            for i in range(len(parts) - 1, -1, -1):
                part = parts[i]
                # Skip common temp/hidden directories
                if part in ["tmp", "temp", ".claude", ".git", "__pycache__"]:
                    continue
                # Skip session-like IDs (long alphanumeric strings)
                if len(part) > 20 and part.replace("-", "").replace("_", "").isalnum():
                    continue
                # This might be a project directory
                if i > 0:
                    parent_path = Path(*parts[:i+1])
                    return f"{part} ({parent_path})"

            # Fallback to current working directory detection
            return self._get_current_project_fallback()

        except Exception:
            return self._get_current_project_fallback()

    def _get_current_project_fallback(self) -> Optional[str]:
        """Get current project info as fallback when transcript path is not helpful"""
        try:
            # Try to get current working directory from environment
            cwd = os.environ.get("PWD") or os.getcwd()
            cwd_path = Path(cwd)

            # Extract project name from current working directory
            project_name = cwd_path.name

            # Avoid generic directory names and user names (compared lower-cased,
            # so the sets are stored already lower-cased for O(1) membership).
            generic_names = {"home", "tmp", "temp", "desktop", "documents",
                             "downloads", "users", "user", "workspace", "projects"}
            user_names = {"james", "alice", "bob", "admin", "root"}

            if (project_name.lower() in generic_names
                    or project_name.lower() in user_names):
                # Try to find a meaningful project directory by going up the path
                for parent in cwd_path.parents:
                    parent_name = parent.name
                    if (parent_name.lower() not in generic_names
                            and parent_name.lower() not in user_names
                            and parent_name not in ("", "/")):
                        return f"{parent_name} ({parent})"

                # If we can't find a good project name, just use current dir
                return f"Current Project ({cwd_path})"

            return f"{project_name} ({cwd_path})"

        except Exception:
            return "Unknown Project"

    def process_hook_event(self, event_type: str, data: Dict[str, Any]) -> bool:
        """
        Process a hook event and send appropriate notification

        Args:
            event_type: Type of hook event (PreToolUse, PostToolUse, etc.)
            data: JSON data from the hook

        Returns:
            bool: True if notification was sent successfully
        """
        # Extract project information
        project_info = self._extract_project_info(data)

        if event_type not in self.event_templates:
            # Unknown event type, send generic notification
            message = f"Unknown event: {event_type}"
            if project_info:
                message = f"{message}\nProject: {project_info}"
            return self._dispatch("Claude Event", message, "normal")

        template = self.event_templates[event_type]
        title = template["title"]
        message = template["message"]
        urgency = template["urgency"]

        # Add project info to title for better context
        if project_info:
            # Extract just the project name for the title
            project_name = (
                project_info.split(" (")[0]
                if " (" in project_info
                else project_info
            )
            title = f"{title} - {project_name}"

        # Customize message based on event type and data
        if event_type in ["PreToolUse", "PostToolUse"]:
            tool_name = data.get("tool_name", "Unknown Tool")
            message = message.format(tool_name=tool_name)

            # Increase urgency for critical tools
            if tool_name in self.critical_tools and event_type == "PreToolUse":
                urgency = "critical"
                title = f"⚠️ {title}"
                message = f"Claude wants to use {tool_name} - Review required!"

            # Add tool input preview for PreToolUse
            if event_type == "PreToolUse" and "tool_input" in data:
                tool_input = data["tool_input"]
                preview = self._get_tool_input_preview(tool_name, tool_input)
                if preview:
                    message = f"{message}\n{preview}"

        # Always show the full project path in the message for all events
        if project_info:
            # Show full project info in the message body
            message = f"{message}\nProject: {project_info}"

        # Fan out across every enabled channel (desktop + Telegram)
        return self._dispatch(
            title,
            message,
            urgency,
            sound=(urgency in ["normal", "critical"])
        )

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
