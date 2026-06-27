"""Behaviour tests for the CLI, focused on `hook --verbose/--quiet` output."""

import json

import pytest
from click.testing import CliRunner

from claude_notify import cli as cli_module
from claude_notify.config import get_default_config


class _RecordingNotifier:
    """Stand-in for the desktop notifier so tests never fire a real toast."""

    def __init__(self, *args, **kwargs) -> None:
        self.calls: list[dict] = []

    def send_notification(self, **kwargs) -> bool:
        self.calls.append(kwargs)
        return True


@pytest.fixture
def runner(monkeypatch):
    # Keep the CLI hermetic: no user config file, no Telegram, no OS toast.
    monkeypatch.setattr(cli_module, "load_config", get_default_config)
    monkeypatch.setattr(cli_module, "build_telegram_notifier", lambda config: None)
    monkeypatch.setattr(
        "claude_notify.hook_handler.ClaudeNotifier", _RecordingNotifier
    )
    return CliRunner()


def _invoke_hook(runner, *args, payload=None):
    payload = {"cwd": "/work/myproj"} if payload is None else payload
    return runner.invoke(
        cli_module.cli,
        ["hook", "--event-type", "Notification", *args],
        input=json.dumps(payload),
    )


def test_hook_verbose_prints_triggered_notification(runner):
    result = _invoke_hook(runner, "--verbose")

    assert result.exit_code == 0
    out = result.output
    assert "Notification triggered [Notification]" in out
    assert "Claude Notification" in out  # composed title
    assert "myproj" in out  # project name from cwd
    assert "📁 /work/myproj" in out  # project path in the body
    assert "desktop ✓ sent" in out
    assert "telegram — skipped" in out  # no Telegram configured


def test_hook_is_quiet_by_default(runner):
    result = _invoke_hook(runner)

    assert result.exit_code == 0
    assert result.output == ""  # silent when delivery succeeds


def test_hook_verbose_accepts_short_flag(runner):
    result = _invoke_hook(runner, "-v")

    assert result.exit_code == 0
    assert "Notification triggered" in result.output


def test_hook_verbose_telegram_only_reports_desktop_skipped(runner):
    # The documented Telegram-only invocation: desktop is suppressed and, with
    # no Telegram configured here, nothing delivers — verbose still reports it.
    result = _invoke_hook(runner, "--no-desktop", "--verbose")

    assert result.exit_code == 0  # hook never blocks Claude
    out = result.output
    assert "Notification triggered" in out
    assert "desktop — skipped" in out
    assert "telegram — skipped" in out
