"""Claude Notify - Cross-platform notifications for Claude"""

# Single source of truth for the package version. pyproject.toml reads this
# via [tool.setuptools.dynamic], and the CLI imports it for --version, so the
# value must only ever be changed here.
__version__ = "0.1.1"
__author__ = "jamez01"

from .hook_handler import HookHandler
from .notifier import ClaudeNotifier
from .session_monitor import ClaudeSessionMonitor
from .telegram import TelegramNotifier, build_telegram_notifier

__all__ = [
    "ClaudeNotifier",
    "TelegramNotifier",
    "build_telegram_notifier",
    "HookHandler",
    "ClaudeSessionMonitor",
]
