"""Behaviour tests for notification dispatch and capability detection.

These deliberately avoid asserting on the platform script *contents* (covered by
test_notifier_security.py); they pin routing and capability reporting, which are
stable across backend implementations.
"""

from claude_notify.notifier import ClaudeNotifier


def test_check_dependencies_reports_plyer_available():
    deps = ClaudeNotifier().check_dependencies()
    assert deps["plyer"] is True
    assert "native" in deps


def test_check_dependencies_macos(monkeypatch):
    notifier = ClaudeNotifier()
    monkeypatch.setattr(notifier, "system", "darwin")

    deps = notifier.check_dependencies()

    assert deps["native"] is True
    assert deps["method"] == "osascript"


def test_check_dependencies_windows(monkeypatch):
    notifier = ClaudeNotifier()
    monkeypatch.setattr(notifier, "system", "windows")

    assert notifier.check_dependencies()["method"] == "powershell"


def test_send_notification_routes_to_platform_backend(monkeypatch):
    notifier = ClaudeNotifier()
    monkeypatch.setattr(notifier, "system", "linux")
    captured: dict = {}

    def fake_linux(title, message, urgency, timeout):
        captured.update(title=title, message=message)
        return True

    monkeypatch.setattr(notifier, "_send_linux_notification", fake_linux)

    assert notifier.send_notification("T", "M", urgency="normal") is True
    assert captured == {"title": "T", "message": "M"}


def test_send_notification_falls_back_to_plyer_on_backend_error(monkeypatch):
    notifier = ClaudeNotifier()
    monkeypatch.setattr(notifier, "system", "linux")

    def boom(*args, **kwargs):
        raise RuntimeError("backend down")

    monkeypatch.setattr(notifier, "_send_linux_notification", boom)
    monkeypatch.setattr(notifier, "_send_plyer_notification", lambda *a, **k: True)

    assert notifier.send_notification("T", "M") is True
