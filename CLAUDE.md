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

- **Python 3.11+** (`requires-python = ">=3.11"`; CI runs 3.11 and 3.12). Keep the
  established conservative typing style for consistency: use
  `typing.Optional/Dict/Any` rather than PEP 604 (`X | None`) unions, and avoid
  `from __future__ import annotations`. Tooling (ruff/mypy) targets py311.
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
# Build + (re)install the `claude-notify` CLI as a uv tool. Runs ruff/mypy/pytest
# first, then an editable install (live source); --wheel builds a pinned artifact.
scripts/build-install.sh            # editable (default)
scripts/build-install.sh --wheel    # build + install a wheel
scripts/build-install.sh --help     # all options

# Or directly with pip
pip install -e .                    # development mode
pip install -r requirements.txt     # dependencies only
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
- **Real-time monitoring**: Polls the JSONL transcripts under every
  `~/.claude*/projects/` tree (and `$CLAUDE_CONFIG_DIR`) for changes every 30
  seconds (configurable); only sessions touched within `RECENT_SESSION_WINDOW`
  (24h) are considered, and only changed files are re-parsed
- **Smart pattern detection**: Flags a session only when Claude is *awaiting the
  user* (it spoke/acted last) **and** its final response asks a question, makes
  an explicit request, or reports an error — a plain "all done" is not an alert
- **Project-aware**: Names the project from the session `cwd` (never the lossy
  dash-encoded directory name)
- **One-time notifications**: Won't spam you with repeated alerts for the same session
- **Multi-project support**: Can monitor all Claude projects or just the current directory

### Claude Hook Integration
The application is designed to work as a Claude Code hook. Key features:
- Reads hook JSON data from stdin
- Automatically determines event type from JSON structure
- Sends appropriate notifications based on event type
- Special handling for critical tools (Bash, Write, Edit, MultiEdit)
- Non-blocking operation to avoid interrupting Claude's workflow
- **Project identification**: the project name (title) and full path (body) come
  from the hook payload's `cwd` (falling back to the transcript's `cwd`, then the
  hook process CWD). The dash-encoded `~/.claude*/projects/<dir>` name is *not*
  decoded — it flattens path separators and cannot be reversed unambiguously.
- **Completion summary**: `Stop`/`SubagentStop` events parse the transcript
  (`transcript.py`) and add Claude's last response and the turn duration (last
  user prompt → final reply). The response is whitespace-collapsed and truncated
  to `MAX_RESPONSE_PREVIEW_CHARS`. Parsing never raises — a missing/partial file
  degrades to fewer fields, preserving the non-blocking contract.

### Notification Channels

- **Desktop** (`ClaudeNotifier` in `notifier.py`): macOS `osascript`, Linux
  `notify-send`, Windows PowerShell toast, with a plyer fallback. Untrusted text is
  passed as `argv` / environment variables, never interpolated into the script —
  this is an injection fix (`b906958`); do not "simplify" it back to string
  interpolation.
- **Telegram** (`TelegramNotifier` in `telegram.py`, opt-in): outbound-only via the
  Bot API over stdlib `urllib`; enabled by `telegram_enabled` in config.
- **Channel selection**: the hook fans out to every *enabled* channel via
  `HookHandler._dispatch` and returns success if any channel delivered. Desktop is
  gated by `desktop_enabled` (config) or the per-invocation
  `claude-notify hook --desktop/--no-desktop` override — use `--no-desktop` for a
  Telegram-only hook.

**Credential precedence (gotcha):** for the Telegram token/chat id, a non-empty
config value wins; `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` are only a fallback
when the config value is empty. The token is masked (`***`) in CLI output and
must never be logged.

### Project Structure
```
claude-notify/
├── claude_notify/
│   ├── __init__.py          # Public API + single-source __version__
│   ├── notifier.py          # ClaudeNotifier (desktop channel)
│   ├── telegram.py          # TelegramNotifier + build_telegram_notifier (opt-in channel)
│   ├── cli.py               # Click CLI: send, watch, hook, check, config
│   ├── config.py            # YAML config: get_default_config / load_config / save_config
│   ├── hook_handler.py      # Claude hook event → notification routing
│   ├── transcript.py        # Parse session JSONL → SessionSummary (last reply, duration, cwd, awaiting_user)
│   └── session_monitor.py   # Poll ~/.claude*/projects/*.jsonl for sessions awaiting the user (`watch` mode)
├── tests/                   # pytest suite (test_*.py per module)
├── examples/                # Demos: example_usage.py, telegram_example.py, test-*.py
├── scripts/build-install.sh # Build + (re)install the CLI via uv (editable default; --wheel for a pinned build)
├── .github/workflows/ci.yml # CI: ruff + pytest + mypy
├── pyproject.toml           # Packaging, deps, ruff/pytest/mypy config
├── requirements.txt         # Runtime dependencies
└── README.md
```