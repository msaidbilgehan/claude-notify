"""Behaviour tests for the Telegram notification channel.

These never touch the network: the HTTP seam (``urllib.request.urlopen``) and
the ``_call`` seam are stubbed, so the tests stay fast, isolated, and
deterministic.
"""

import urllib.error
import urllib.request

import pytest

from claude_notify.telegram import TelegramNotifier, build_telegram_notifier


class _FakeResponse:
    """Minimal stand-in for the context manager urlopen returns."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


@pytest.fixture(autouse=True)
def _no_telegram_env(monkeypatch):
    """Isolate every test from any real TELEGRAM_* credentials in the env."""
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)


# --- credential resolution -------------------------------------------------

def test_is_configured_requires_both_token_and_chat_id():
    assert TelegramNotifier("tok", "chat").is_configured() is True
    assert TelegramNotifier("tok", "").is_configured() is False
    assert TelegramNotifier("", "chat").is_configured() is False


def test_credentials_fall_back_to_environment(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "env-chat")

    notifier = TelegramNotifier()

    assert notifier.bot_token == "env-token"
    assert notifier.chat_id == "env-chat"


def test_explicit_credentials_win_over_environment(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "env-chat")

    notifier = TelegramNotifier(bot_token="arg-token", chat_id="arg-chat")

    assert notifier.bot_token == "arg-token"
    assert notifier.chat_id == "arg-chat"


# --- message formatting ----------------------------------------------------

def test_format_message_includes_app_title_and_body():
    notifier = TelegramNotifier("tok", "chat", app_name="Claude")
    assert notifier._format_message("Title", "Body", "normal") == "Claude\nTitle\nBody"


def test_format_message_flags_critical_urgency():
    notifier = TelegramNotifier("tok", "chat", app_name="Claude")
    assert notifier._format_message("Title", "Body", "critical").startswith("⚠️ ")


# --- send_notification -----------------------------------------------------

def test_send_notification_no_ops_when_unconfigured(monkeypatch):
    def fail(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("unconfigured notifier must not hit the network")

    monkeypatch.setattr(urllib.request, "urlopen", fail)

    assert TelegramNotifier("", "").send_notification("T", "M") is False


def test_send_notification_posts_sendmessage_with_chat_and_text(monkeypatch):
    notifier = TelegramNotifier("tok", "12345", app_name="Claude")
    captured = {}

    def fake_call(method, params=None, timeout=10):
        captured.update(method=method, params=params)
        return True

    monkeypatch.setattr(notifier, "_call", fake_call)

    assert notifier.send_notification("Title", "Body", urgency="normal") is True
    assert captured["method"] == "sendMessage"
    assert captured["params"]["chat_id"] == "12345"
    assert captured["params"]["text"] == "Claude\nTitle\nBody"


# --- _call HTTP transport --------------------------------------------------

def test_call_returns_true_on_ok_response(monkeypatch):
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda request, timeout=10: _FakeResponse(b'{"ok": true}'),
    )
    assert TelegramNotifier("tok", "chat")._call("getMe", timeout=5) is True


def test_call_returns_false_when_api_reports_not_ok(monkeypatch):
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda request, timeout=10: _FakeResponse(b'{"ok": false}'),
    )
    assert TelegramNotifier("tok", "chat")._call("getMe") is False


def test_call_swallows_http_error(monkeypatch):
    def raise_http(request, timeout=10):
        raise urllib.error.HTTPError("url", 401, "Unauthorized", None, None)

    monkeypatch.setattr(urllib.request, "urlopen", raise_http)
    assert TelegramNotifier("tok", "chat")._call("sendMessage") is False


def test_call_swallows_url_error(monkeypatch):
    def raise_url(request, timeout=10):
        raise urllib.error.URLError("network down")

    monkeypatch.setattr(urllib.request, "urlopen", raise_url)
    assert TelegramNotifier("tok", "chat")._call("sendMessage") is False


def test_call_returns_false_without_token():
    assert TelegramNotifier("", "chat")._call("getMe") is False


# --- check_telegram --------------------------------------------------------

def test_check_telegram_skips_network_when_unconfigured(monkeypatch):
    def fail(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("must not hit the network when unconfigured")

    monkeypatch.setattr(urllib.request, "urlopen", fail)

    assert TelegramNotifier("", "").check_telegram() == {
        "configured": False,
        "reachable": False,
    }


# --- build_telegram_notifier factory ---------------------------------------

def test_build_returns_none_when_disabled():
    config = {
        "telegram_enabled": False,
        "telegram_bot_token": "tok",
        "telegram_chat_id": "chat",
    }
    assert build_telegram_notifier(config) is None


def test_build_returns_none_when_enabled_but_uncredentialed():
    config = {
        "telegram_enabled": True,
        "telegram_bot_token": "",
        "telegram_chat_id": "",
    }
    assert build_telegram_notifier(config) is None


def test_build_returns_notifier_when_enabled_and_configured():
    config = {
        "telegram_enabled": True,
        "telegram_bot_token": "tok",
        "telegram_chat_id": "chat",
        "app_name": "Claude",
    }
    notifier = build_telegram_notifier(config)

    assert notifier is not None
    assert notifier.is_configured() is True
    assert notifier.app_name == "Claude"
