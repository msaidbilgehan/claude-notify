# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview
Claude-notify is a cross-platform notification system that integrates with Claude Code hooks to alert users when Claude needs their attention or performs certain actions. It can be used both as a Claude hook and as a standalone notification tool.

## Project Status

Implemented and released as **v0.1.1**. The version is single-sourced in
`claude_notify/__init__.py` (`__version__`); `pyproject.toml` reads it via
`[tool.setuptools.dynamic]` and the CLI exposes it as `--version`. Packaging is
`pyproject.toml` (setuptools) — there is no `setup.py`.

## Tech Stack & Conventions

- **Python**, 3.7-compatible typing style: use `typing.Optional/Dict/Any`. Do
  **not** use PEP 604 (`X | None`) unions or `from __future__ import annotations`.
  Tooling (ruff/mypy) targets py311.
- **Click** (CLI), **plyer** (desktop-notification fallback), **PyYAML** (config).
- Diagnostics go through the **`logging`** module
  (`logger = logging.getLogger(__name__)`) — do not add `print` to package code.
- Notification senders return `bool` and swallow transport errors: a failed send
  must never raise out of the hook/watch path (non-blocking contract).
- Config is dict-based with merge-with-defaults: new keys added to
  `get_default_config()` self-heal into existing user config files.

## Development Commands

### Installation
```bash
# Install in development mode
pip install -e .

# Install dependencies only
pip install -r requirements.txt
```

### Tests, Lint, Types
```bash
# Run the test suite (tests/ — pytest configured in pyproject.toml)
pytest

# Lint (CI enforces `ruff check`)
ruff check .

# Type check
mypy claude_notify
```

### Manual Notification Checks
```bash
# Check system dependencies and Telegram channel status
claude-notify check

# Send a test notification (add --telegram to also hit the Telegram channel)
claude-notify send --title "Test" --message "Testing claude-notify"

# Run example scripts
python examples/example_usage.py
python examples/telegram_example.py

# Test real-time monitoring (in separate terminal)
claude-notify watch --verbose
```

### CLI Commands
- `claude-notify send`: Send a notification immediately
- `claude-notify watch`: Monitor Claude sessions for activity requiring attention
- `claude-notify hook`: Process Claude Code hook events (reads JSON from stdin)
- `claude-notify check`: Check system dependencies
- `claude-notify config show`: Display current configuration
- `claude-notify config set <key> <value>`: Update configuration
- `claude-notify config reset`: Reset to default configuration

### Watch Mode Features
- **Real-time monitoring**: Checks transcript files for changes every 30 seconds (configurable)
- **Smart pattern detection**: Identifies when Claude is waiting for input, asking questions, or encountering errors
- **Project-aware**: Shows which specific project needs attention
- **One-time notifications**: Won't spam you with repeated alerts for the same session
- **Multi-project support**: Can monitor all Claude projects or just the current directory

### Claude Hook Integration
The application is designed to work as a Claude Code hook. Key features:
- Reads hook JSON data from stdin
- Automatically determines event type from JSON structure
- Sends appropriate notifications based on event type
- Special handling for critical tools (Bash, Write, Edit, MultiEdit)
- Non-blocking operation to avoid interrupting Claude's workflow
- **Project identification**: All notifications include project name in title and full path in message

### Notification Channels

- **Desktop** (`ClaudeNotifier`): macOS `osascript`, Linux `notify-send`, Windows
  PowerShell toast, with a plyer fallback. Untrusted text is passed as `argv` /
  environment variables, never interpolated into the script — this is an injection
  fix (`b906958`); do not "simplify" it back to string interpolation.
- **Telegram** (`TelegramNotifier`, opt-in): outbound-only via the Bot API over
  stdlib `urllib`; enabled by `telegram_enabled` in config.

**Credential precedence (gotcha):** for the Telegram token/chat id, a non-empty
config value wins; `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` are only a fallback
when the config value is empty. The token is masked (`***`) in CLI output and
must never be logged.

### Project Structure
```
claude-notify/
├── claude_notify/
│   ├── __init__.py          # Public API + single-source __version__
│   ├── notifier.py          # ClaudeNotifier (desktop) + TelegramNotifier + build_telegram_notifier
│   ├── cli.py               # Click CLI: send, watch, hook, check, config
│   ├── config.py            # YAML config: get_default_config / load_config / save_config
│   ├── hook_handler.py      # Claude hook event → notification routing
│   └── session_monitor.py   # Transcript watching for `watch` mode
├── tests/                   # pytest suite (test_*.py per module)
├── examples/                # Demos: example_usage.py, telegram_example.py, test-*.py
├── .github/workflows/ci.yml # CI: ruff + pytest
├── pyproject.toml           # Packaging, deps, ruff/pytest/mypy config
├── requirements.txt         # Runtime dependencies
└── README.md
```