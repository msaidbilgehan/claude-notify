"""Regression tests for notification script/command injection.

Notification ``title``/``message`` can originate from transcript content and
tool input, so they are untrusted. These tests pin the contract that the
platform backends never interpolate that text into the script source: macOS
delivers it as ``osascript`` run-handler ``argv`` and Windows delivers it as
environment data, keeping it inert (see ``SEC_COMMAND_INJECTION``).
"""

import subprocess
import unittest
from unittest import mock

from claude_notify.notifier import ClaudeNotifier

# Payloads that break out of a naively interpolated script:
#   - AppleScript: a double quote closes the string literal.
#   - PowerShell here-string: ``$(...)`` is an evaluated subexpression.
#   - Toast XML: ``</text>`` closes the element.
EVIL_TITLE = 'pwn" & (do shell script "id") & "'
EVIL_MESSAGE = '</text></binding>$(Remove-Item C:\\ -Recurse)'


class MacOsInjectionTests(unittest.TestCase):
    def test_payload_passed_as_argv_not_interpolated(self) -> None:
        notifier = ClaudeNotifier(app_name="Claude")

        with mock.patch("claude_notify.notifier.subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0)
            sent = notifier._send_macos_notification(
                EVIL_TITLE, EVIL_MESSAGE, sound=True
            )

        self.assertTrue(sent)
        (command,), _kwargs = run.call_args
        self.assertEqual(command[0], "osascript")
        # Untrusted text is delivered out-of-band as run-handler argv...
        self.assertEqual(command[-3:], [EVIL_MESSAGE, EVIL_TITLE, "Claude"])
        # ...and never appears inside the executed -e script fragments.
        script = "\n".join(
            command[index + 1]
            for index, token in enumerate(command)
            if token == "-e"
        )
        self.assertNotIn(EVIL_MESSAGE, script)
        self.assertNotIn(EVIL_TITLE, script)


class WindowsInjectionTests(unittest.TestCase):
    def test_payload_passed_via_env_not_interpolated(self) -> None:
        notifier = ClaudeNotifier(app_name="Claude")

        with mock.patch("claude_notify.notifier.subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0)
            sent = notifier._send_windows_notification(
                EVIL_TITLE, EVIL_MESSAGE, timeout=10
            )

        self.assertTrue(sent)
        (command,), kwargs = run.call_args
        self.assertEqual(command[0], "powershell")
        # The script source is static — no untrusted text is interpolated in.
        script = command[-1]
        self.assertNotIn(EVIL_MESSAGE, script)
        self.assertNotIn(EVIL_TITLE, script)
        # Untrusted text is delivered as inert environment data instead.
        env = kwargs["env"]
        self.assertEqual(env["CLAUDE_NOTIFY_TITLE"], EVIL_TITLE)
        self.assertEqual(env["CLAUDE_NOTIFY_MESSAGE"], EVIL_MESSAGE)
        self.assertEqual(env["CLAUDE_NOTIFY_APP"], "Claude")


if __name__ == "__main__":
    unittest.main()
