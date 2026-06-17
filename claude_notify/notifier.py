"""Cross-platform notification system for Claude"""

import json
import logging
import os
import platform
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional
from plyer import notification as plyer_notification

logger = logging.getLogger(__name__)


class ClaudeNotifier:
    """Cross-platform notification handler for Claude alerts"""
    
    def __init__(self, app_name: str = "Claude"):
        self.app_name = app_name
        self.system = platform.system().lower()
        
    def send_notification(
        self, 
        title: str, 
        message: str, 
        urgency: str = "normal",
        timeout: int = 10,
        sound: bool = True
    ) -> bool:
        """
        Send a notification across different platforms
        
        Args:
            title: Notification title
            message: Notification message
            urgency: Urgency level (low, normal, critical)
            timeout: Notification timeout in seconds
            sound: Whether to play a sound
            
        Returns:
            bool: True if notification was sent successfully
        """
        try:
            if self.system == "darwin":  # macOS
                return self._send_macos_notification(title, message, sound)
            elif self.system == "linux":
                return self._send_linux_notification(title, message, urgency, timeout)
            elif self.system == "windows":
                return self._send_windows_notification(title, message, timeout)
            else:
                # Fallback to plyer for unknown systems
                return self._send_plyer_notification(title, message, timeout)
        except Exception as e:
            logger.warning("Notification failed, falling back to plyer: %s", e)
            return self._send_plyer_notification(title, message, timeout)
    
    def _send_macos_notification(self, title: str, message: str, sound: bool) -> bool:
        """Send a notification on macOS via ``osascript``.

        The title and message are passed to the AppleScript as run-handler
        arguments (``argv``), not interpolated into the script source. Because
        this text can originate from transcript content or tool input, embedding
        it in the script literal would let a quote or AppleScript expression
        break out and execute arbitrary code (script injection). Passing it as
        ``argv`` keeps it inert data.
        """
        notification_clause = (
            "display notification (item 1 of argv) "
            "with title (item 2 of argv) subtitle (item 3 of argv)"
        )
        if sound:
            notification_clause += ' sound name "default"'

        command = [
            "osascript",
            "-e", "on run argv",
            "-e", notification_clause,
            "-e", "end run",
            message,
            title,
            self.app_name,
        ]

        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
            return True
        except subprocess.CalledProcessError:
            return False
    
    def _send_linux_notification(
        self, 
        title: str, 
        message: str, 
        urgency: str, 
        timeout: int
    ) -> bool:
        """Send notification on Linux using notify-send"""
        try:
            # Check if notify-send is available
            subprocess.run(
                ["which", "notify-send"],
                check=True,
                capture_output=True
            )
            
            cmd = [
                "notify-send",
                f"--app-name={self.app_name}",
                f"--urgency={urgency}",
                f"--expire-time={timeout * 1000}",  # Convert to milliseconds
                title,
                message
            ]
            
            subprocess.run(cmd, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False
    
    def _send_windows_notification(self, title: str, message: str, timeout: int) -> bool:
        """Send a notification on Windows via a PowerShell toast.

        The title, message, and app name are passed to PowerShell through
        environment variables and XML-escaped inside the script, rather than
        interpolated into the script source. A double-quoted PowerShell
        here-string expands ``$(...)`` subexpressions, so interpolating
        untrusted notification text would allow arbitrary command execution;
        reading the values from ``$env:`` keeps them inert strings, and the
        XML escape prevents them from breaking out of the toast markup
        (command/script injection).
        """
        ps_script = (
            '$ErrorActionPreference = "Stop"\n'
            "[Windows.UI.Notifications.ToastNotificationManager,"
            " Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null\n"
            "[Windows.Data.Xml.Dom.XmlDocument,"
            " Windows.Data.Xml.Dom, ContentType = WindowsRuntime] | Out-Null\n"
            "$title = [System.Security.SecurityElement]::Escape($env:CLAUDE_NOTIFY_TITLE)\n"
            "$message = [System.Security.SecurityElement]::Escape($env:CLAUDE_NOTIFY_MESSAGE)\n"
            "$appName = $env:CLAUDE_NOTIFY_APP\n"
            '$template = @"\n'
            '<toast duration="long">\n'
            "    <visual>\n"
            '        <binding template="ToastText02">\n'
            '            <text id="1">$title</text>\n'
            '            <text id="2">$message</text>\n'
            "        </binding>\n"
            "    </visual>\n"
            '    <audio src="ms-winsoundevent:Notification.Default" />\n'
            "</toast>\n"
            '"@\n'
            "$xml = New-Object Windows.Data.Xml.Dom.XmlDocument\n"
            "$xml.LoadXml($template)\n"
            "$toast = New-Object Windows.UI.Notifications.ToastNotification $xml\n"
            "[Windows.UI.Notifications.ToastNotificationManager]"
            "::CreateToastNotifier($appName).Show($toast)\n"
        )

        env = os.environ.copy()
        env["CLAUDE_NOTIFY_TITLE"] = title
        env["CLAUDE_NOTIFY_MESSAGE"] = message
        env["CLAUDE_NOTIFY_APP"] = self.app_name

        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                check=True,
                capture_output=True,
                env=env,
            )
            return True
        except subprocess.CalledProcessError:
            return False
    
    def _send_plyer_notification(self, title: str, message: str, timeout: int) -> bool:
        """Fallback notification using plyer library"""
        try:
            plyer_notification.notify(
                title=title,
                message=message,
                app_name=self.app_name,
                timeout=timeout
            )
            return True
        except Exception:
            return False
    
    def check_dependencies(self) -> Dict[str, bool]:
        """Check which notification methods are available"""
        deps = {
            "plyer": True,  # Always available if installed
            "native": False
        }
        
        if self.system == "darwin":
            # macOS always has osascript
            deps["native"] = True
            deps["method"] = "osascript"
        elif self.system == "linux":
            # Check for notify-send
            try:
                subprocess.run(
                    ["which", "notify-send"],
                    check=True,
                    capture_output=True
                )
                deps["native"] = True
                deps["method"] = "notify-send"
            except subprocess.CalledProcessError:
                deps["method"] = "plyer"
        elif self.system == "windows":
            # Windows with PowerShell
            deps["native"] = True
            deps["method"] = "powershell"

        return deps


class TelegramNotifier:
    """Send Claude notifications to a Telegram chat via the Bot API.

    This is an additional, opt-in channel that mirrors
    :class:`ClaudeNotifier`'s public shape so the two are interchangeable.
    Messages are sent outbound only (no inbound polling) as plain text, with
    a short HTTP timeout, and every failure is swallowed and reported as
    ``False`` so a Telegram problem never blocks Claude or raises out of the
    hook path. The bot token is a secret: it is read from config or the
    environment, never hardcoded, and never written to a log line.
    """

    api_base = "https://api.telegram.org"

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        app_name: str = "Claude"
    ):
        # Credentials resolve from explicit args first, then environment
        # variables. Never hardcode and never log the token.
        self.bot_token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
        self.app_name = app_name

    def is_configured(self) -> bool:
        """Return True when both a bot token and a chat id are available"""
        return bool(self.bot_token) and bool(self.chat_id)

    def send_notification(
        self,
        title: str,
        message: str,
        urgency: str = "normal",
        timeout: int = 10,
        sound: bool = True
    ) -> bool:
        """
        Send a notification to the configured Telegram chat

        Mirrors ``ClaudeNotifier.send_notification`` so callers can treat the
        two channels uniformly. ``sound`` is accepted for signature
        compatibility and ignored (Telegram controls its own alerting);
        ``timeout`` bounds the HTTP request rather than a toast lifetime.

        Args:
            title: Notification title
            message: Notification message
            urgency: Urgency level (low, normal, critical); ``critical`` adds a
                leading ⚠️ to the message, matching the hook handler style
            timeout: HTTP request timeout in seconds
            sound: Accepted for ClaudeNotifier compatibility; unused here

        Returns:
            bool: True if Telegram accepted the message, False on any failure
        """
        if not self.is_configured():
            return False

        text = self._format_message(title, message, urgency)
        return self._call(
            "sendMessage",
            {"chat_id": self.chat_id, "text": text},
            timeout
        )

    def check_telegram(self) -> Dict[str, Any]:
        """Report Telegram channel availability

        Returns ``{"configured": bool, "reachable": bool}``. ``reachable``
        performs a lightweight ``getMe`` call only when configured, with a
        short timeout, and is ``False`` on any failure so ``check`` and
        ``watch`` never hang or raise.
        """
        configured = self.is_configured()
        reachable = self._call("getMe", timeout=5) if configured else False
        return {"configured": configured, "reachable": reachable}

    def _format_message(self, title: str, message: str, urgency: str) -> str:
        """Build the plain-text body (no parse_mode, so no escaping needed)"""
        prefix = "⚠️ " if urgency == "critical" else ""
        return f"{prefix}{self.app_name}\n{title}\n{message}"

    def _call(
        self,
        method: str,
        params: Optional[Dict[str, str]] = None,
        timeout: int = 10
    ) -> bool:
        """Call a Telegram Bot API method, returning whether it succeeded

        The bot token sits in the URL path, so it must never appear in a log
        line — only the method name and the HTTP status/reason are logged.
        Transport and parse errors are caught and reported as ``False`` to keep
        the send best-effort and non-blocking.
        """
        if not self.bot_token:
            return False

        url = f"{self.api_base}/bot{self.bot_token}/{method}"
        data = urllib.parse.urlencode(params).encode("utf-8") if params else None
        request = urllib.request.Request(url, data=data)

        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read()
            payload = json.loads(body.decode("utf-8"))
            return bool(payload.get("ok", False))
        except urllib.error.HTTPError as e:
            # e.code / e.reason do not contain the bot token.
            logger.warning(
                "Telegram %s rejected: HTTP %s %s", method, e.code, e.reason
            )
            return False
        except urllib.error.URLError as e:
            logger.warning("Telegram %s failed: %s", method, e.reason)
            return False
        except (OSError, ValueError) as e:
            # ValueError covers json.JSONDecodeError; OSError covers socket
            # timeouts and other transport failures.
            logger.warning("Telegram %s failed: %s", method, e)
            return False


def build_telegram_notifier(
    config: Dict[str, Any]
) -> Optional[TelegramNotifier]:
    """Construct a TelegramNotifier from config when Telegram is enabled

    Returns ``None`` when ``telegram_enabled`` is falsy or when no usable
    credentials resolve (from config or the ``TELEGRAM_BOT_TOKEN`` /
    ``TELEGRAM_CHAT_ID`` environment variables), so callers can use the result
    as a simple on/off switch for the channel.
    """
    if not config.get("telegram_enabled"):
        return None

    notifier = TelegramNotifier(
        bot_token=config.get("telegram_bot_token") or None,
        chat_id=config.get("telegram_chat_id") or None,
        app_name=config.get("app_name", "Claude")
    )
    return notifier if notifier.is_configured() else None