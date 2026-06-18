"""Behaviour tests for hook event handling."""

from claude_notify.hook_handler import HookHandler


class RecordingNotifier:
    """Test double that records notifications instead of displaying them."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def send_notification(self, **kwargs) -> bool:
        self.calls.append(kwargs)
        return True


class RecordingTelegram:
    """Telegram double that records sends instead of calling the Bot API."""

    def __init__(self, configured: bool = True) -> None:
        self.calls: list[dict] = []
        self._configured = configured

    def is_configured(self) -> bool:
        return self._configured

    def send_notification(self, **kwargs) -> bool:
        self.calls.append(kwargs)
        return True


def make_handler() -> tuple[HookHandler, RecordingNotifier]:
    notifier = RecordingNotifier()
    return HookHandler(notifier=notifier), notifier


def test_explicit_event_type_is_used():
    handler, _ = make_handler()
    assert handler.determine_event_type({"event_type": "Stop"}) == "Stop"


def test_tool_name_without_response_is_pre_tool_use():
    handler, _ = make_handler()
    assert handler.determine_event_type({"tool_name": "Bash"}) == "PreToolUse"


def test_tool_name_with_response_is_post_tool_use():
    handler, _ = make_handler()
    data = {"tool_name": "Bash", "tool_response": {"ok": True}}
    assert handler.determine_event_type(data) == "PostToolUse"


def test_notification_type_is_notification():
    handler, _ = make_handler()
    assert handler.determine_event_type({"notification_type": "info"}) == "Notification"


def test_session_without_tool_is_stop():
    handler, _ = make_handler()
    assert handler.determine_event_type({"session_id": "abc"}) == "Stop"


def test_unrecognised_payload_returns_none():
    handler, _ = make_handler()
    assert handler.determine_event_type({}) is None


def test_long_bash_command_preview_is_truncated():
    handler, _ = make_handler()

    preview = handler._get_tool_input_preview("Bash", {"command": "x" * 100})

    assert preview.startswith("Command: ")
    assert preview.endswith("...")
    assert len(preview) == len("Command: ") + 50


def test_write_preview_shows_file_path():
    handler, _ = make_handler()
    preview = handler._get_tool_input_preview("Write", {"file_path": "/tmp/a.txt"})
    assert preview == "File: /tmp/a.txt"


def test_unknown_tool_has_no_preview():
    handler, _ = make_handler()
    assert handler._get_tool_input_preview("Glob", {"pattern": "*"}) is None


def test_critical_tool_pretooluse_raises_urgency_to_critical():
    handler, notifier = make_handler()

    sent = handler.process_hook_event(
        "PreToolUse", {"tool_name": "Bash", "tool_input": {"command": "ls"}}
    )

    assert sent is True
    call = notifier.calls[-1]
    assert call["urgency"] == "critical"
    assert "Bash" in call["message"]


def test_unknown_event_sends_generic_notification():
    handler, notifier = make_handler()

    sent = handler.process_hook_event("Mystery", {})

    assert sent is True
    assert notifier.calls[-1]["title"] == "Claude Event"


def test_telegram_fans_out_alongside_desktop_by_default():
    desktop = RecordingNotifier()
    telegram = RecordingTelegram()
    handler = HookHandler(notifier=desktop, telegram=telegram)

    sent = handler.process_hook_event("Stop", {"session_id": "abc"})

    assert sent is True
    assert len(desktop.calls) == 1
    assert len(telegram.calls) == 1


def test_desktop_disabled_suppresses_desktop_but_still_sends_telegram():
    desktop = RecordingNotifier()
    telegram = RecordingTelegram()
    handler = HookHandler(
        notifier=desktop, telegram=telegram, desktop_enabled=False
    )

    sent = handler.process_hook_event("Stop", {"session_id": "abc"})

    assert sent is True
    assert desktop.calls == []  # desktop channel suppressed
    assert len(telegram.calls) == 1  # telegram still notified


def test_desktop_disabled_without_telegram_reports_no_delivery():
    desktop = RecordingNotifier()
    handler = HookHandler(notifier=desktop, desktop_enabled=False)

    sent = handler.process_hook_event("Stop", {"session_id": "abc"})

    assert sent is False  # no channel delivered
    assert desktop.calls == []
