"""Telegram notification channel for Claude Notify.

An opt-in, outbound-only integration with the Telegram Bot API, kept in its own
module so the channel is self-contained and independent of the desktop notifier.
It talks to the Bot API over the standard library (:mod:`urllib`) — no
third-party dependency — and is plug-and-play through
:func:`build_telegram_notifier`, which hands back a ready notifier when Telegram
is enabled and configured, or ``None`` otherwise (so callers can treat the
result as a simple on/off switch).

Security: the bot token is a secret. It is read from config or the environment,
never hardcoded, and never written to a log line — only the API method name and
the HTTP status/reason are logged.
"""

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Send Claude notifications to a Telegram chat via the Bot API.

    This is an additional, opt-in channel that mirrors
    :class:`~claude_notify.notifier.ClaudeNotifier`'s public shape so the two
    are interchangeable. Messages are sent outbound only (no inbound polling) as
    plain text, with a short HTTP timeout, and every failure is swallowed and
    reported as ``False`` so a Telegram problem never blocks Claude or raises out
    of the hook path. The bot token is a secret: it is read from config or the
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
