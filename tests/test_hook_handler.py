"""Behaviour tests for hook event handling."""

from datetime import timedelta

from claude_notify.hook_handler import HookHandler, NotificationResult


class RecordingNotifier:
    """Test double that records notifications instead of displaying them."""

    def __init__(self, delivers: bool = True) -> None:
        self.calls: list[dict] = []
        self._delivers = delivers

    def send_notification(self, **kwargs) -> bool:
        self.calls.append(kwargs)
        return self._delivers


class RecordingTelegram:
    """Telegram double that records sends instead of calling the Bot API."""

    def __init__(self, configured: bool = True, delivers: bool = True) -> None:
        self.calls: list[dict] = []
        self._configured = configured
        self._delivers = delivers

    def is_configured(self) -> bool:
        return self._configured

    def send_notification(self, **kwargs) -> bool:
        self.calls.append(kwargs)
        return self._delivers


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
    # The project name is appended for context, so match the stable prefix.
    assert notifier.calls[-1]["title"].startswith("Claude Event")


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


def test_dispatch_event_returns_composed_notification_and_outcomes():
    handler, _ = make_handler()

    result = handler.dispatch_event("Notification", {"cwd": "/work/proj"})

    assert isinstance(result, NotificationResult)
    assert result.event_type == "Notification"
    assert result.title.startswith("Claude Notification")
    assert "proj" in result.title
    assert "📁 /work/proj" in result.message
    assert result.urgency == "normal"
    # Desktop was attempted and delivered; no Telegram was configured.
    assert result.desktop.attempted is True
    assert result.desktop.delivered is True
    assert result.telegram.attempted is False
    assert result.telegram.delivered is False
    assert result.delivered is True


def test_dispatch_event_marks_disabled_desktop_as_not_attempted():
    desktop = RecordingNotifier()
    telegram = RecordingTelegram()
    handler = HookHandler(
        notifier=desktop, telegram=telegram, desktop_enabled=False
    )

    result = handler.dispatch_event("Stop", {"session_id": "abc"})

    # Desktop suppressed (skipped, not failed); Telegram carried the delivery.
    assert result.desktop.attempted is False
    assert result.desktop.delivered is False
    assert result.telegram.attempted is True
    assert result.telegram.delivered is True
    assert result.delivered is True


def test_dispatch_event_distinguishes_failed_from_skipped():
    desktop = RecordingNotifier(delivers=False)
    handler = HookHandler(notifier=desktop)

    result = handler.dispatch_event("Notification", {})

    # Desktop was attempted but rejected the send; Telegram was never tried.
    assert result.desktop.attempted is True
    assert result.desktop.delivered is False
    assert result.telegram.attempted is False
    assert result.delivered is False


def test_dispatch_event_reports_telegram_send_failure():
    telegram = RecordingTelegram(delivers=False)
    handler = HookHandler(telegram=telegram, desktop_enabled=False)

    result = handler.dispatch_event("Notification", {})

    assert result.telegram.attempted is True
    assert result.telegram.delivered is False
    assert result.delivered is False


# A minimal but representative transcript: a meta entry, a genuine prompt, an
# assistant turn that calls a tool, the tool result, and the final answer.
_TRANSCRIPT_LINES = [
    '{"type":"user","isMeta":true,"cwd":"/work/proj",'
    '"timestamp":"2026-06-19T10:00:00.000Z",'
    '"message":{"role":"user","content":"<caveat/>"}}',
    '{"type":"user","cwd":"/work/proj","timestamp":"2026-06-19T10:00:05.000Z",'
    '"message":{"role":"user","content":[{"type":"text","text":"Do the thing"}]}}',
    '{"type":"assistant","cwd":"/work/proj","timestamp":"2026-06-19T10:00:10.000Z",'
    '"message":{"role":"assistant","content":[{"type":"tool_use","name":"Bash"}]}}',
    '{"type":"user","cwd":"/work/proj","timestamp":"2026-06-19T10:00:12.000Z",'
    '"toolUseResult":{"ok":true},'
    '"message":{"role":"user","content":[{"type":"tool_result"}]}}',
    '{"type":"assistant","cwd":"/work/proj","timestamp":"2026-06-19T10:02:35.000Z",'
    '"message":{"role":"assistant",'
    '"content":[{"type":"text","text":"All done. The answer is 42."}]}}',
    '{"type":"ai-title","aiTitle":"Do the thing","sessionId":"x"}',
]


def _write_transcript(tmp_path) -> str:
    path = tmp_path / "0a1b2c3d-session.jsonl"
    path.write_text("\n".join(_TRANSCRIPT_LINES), encoding="utf-8")
    return str(path)


def test_stop_event_reports_response_duration_and_real_project(tmp_path):
    handler, notifier = make_handler()
    transcript = _write_transcript(tmp_path)

    sent = handler.process_hook_event(
        "Stop", {"session_id": "x", "transcript_path": transcript}
    )

    assert sent is True
    call = notifier.calls[-1]
    # Project comes from the transcript's cwd, not the session filename.
    assert call["title"].startswith("✅ Response complete")
    assert "proj" in call["title"]
    assert "All done. The answer is 42." in call["message"]
    assert "2m 30s" in call["message"]  # 10:00:05 prompt -> 10:02:35 reply
    assert "📁 /work/proj" in call["message"]
    # Regression: the opaque session filename must not leak into the message.
    assert ".jsonl" not in call["message"]
    assert "session" not in call["message"]


def test_stop_event_prefers_payload_cwd_over_transcript(tmp_path):
    handler, notifier = make_handler()
    transcript = _write_transcript(tmp_path)

    handler.process_hook_event(
        "Stop",
        {"session_id": "x", "transcript_path": transcript, "cwd": "/explicit/myapp"},
    )

    call = notifier.calls[-1]
    assert "myapp" in call["title"]
    assert "📁 /explicit/myapp" in call["message"]


def test_stop_event_without_transcript_still_names_project(tmp_path, monkeypatch):
    handler, notifier = make_handler()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PWD", raising=False)

    sent = handler.process_hook_event("Stop", {"session_id": "abc"})

    assert sent is True
    call = notifier.calls[-1]
    assert call["title"].startswith("✅ Response complete")
    assert tmp_path.name in call["title"]


def test_format_duration_scales_units():
    assert HookHandler._format_duration(timedelta(seconds=45)) == "45s"
    assert HookHandler._format_duration(timedelta(seconds=150)) == "2m 30s"
    assert HookHandler._format_duration(timedelta(hours=1, minutes=4)) == "1h 4m"
