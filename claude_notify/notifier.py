"""Cross-platform notification system for Claude"""

import platform
import subprocess
import os
from typing import Dict
from plyer import notification as plyer_notification


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
            print(f"Notification error: {e}")
            # Try fallback method
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