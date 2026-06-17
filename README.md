# Claude-notify

A simple, cross-platform notification system to alert you when Claude needs your attention.

## Features

- 🖥️ **Cross-platform support**: Works on macOS, Linux, and Windows
- 🔔 **Native notifications**: Uses system-native notification methods when available
- 🪝 **Claude Code hooks**: Integrates seamlessly with Claude's hook system
- ⚙️ **Configurable**: Customize notification preferences
- 🎯 **Simple CLI**: Easy-to-use command-line interface
- 🔄 **Watch mode**: Continuous monitoring with periodic notifications
- 🚨 **Smart alerts**: Critical notifications for potentially destructive operations
- 📁 **Project identification**: All notifications include project name and path
- 📲 **Telegram channel**: Optionally mirror notifications to a Telegram chat

## Installation

### From Source

```bash
# Clone the repository
git clone https://github.com/msaidbilgehan/claude-notify.git
cd claude-notify

# Install dependencies
pip install -r requirements.txt

# Install the package
pip install -e .
```

### Using pip (when published)

```bash
pip install claude-notify
```

## Usage

### Claude Code Hook Integration (Recommended)

Claude-notify can be integrated directly with Claude Code as a hook to notify you when Claude needs attention or performs certain actions.

#### Setting up as a Claude Hook

You can configure claude-notify as a hook in two ways:

**Option 1: Using Claude's `/hooks` command** (Recommended)
```bash
# In Claude Code, simply run:
/hooks
# This will automatically add claude-notify hooks for Notification and Stop events
```

**Option 2: Manual configuration**

Add to your Claude settings file (`~/.claude/settings.json` or `.claude/settings.json` in your project):

```json
{
  "hooks": {
    "Notification": [
      {
        "matcher": ".*",
        "hooks": [
          {
            "type": "command",
            "command": "claude-notify hook"
          }
        ]
      }
    ],
    "Stop": [
      {
        "matcher": ".*",
        "hooks": [
          {
            "type": "command",
            "command": "claude-notify hook"
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "(Bash|Write|Edit|MultiEdit)",
        "hooks": [
          {
            "type": "command",
            "command": "claude-notify hook"
          }
        ]
      }
    ]
  }
}
```

This configuration will:
- Notify you when Claude finishes responding (Stop event)
- Alert you before Claude uses potentially destructive tools (Bash, Write, Edit, MultiEdit)
- Show the project name in ALL notification titles and full project path in ALL messages

#### Available Hook Events

- **PreToolUse**: Before Claude uses a tool (can be used to review/block actions)
- **PostToolUse**: After a tool completes successfully
- **Notification**: When Claude sends a notification
- **Stop**: When Claude finishes responding
- **SubagentStop**: When a Claude subagent completes

#### Testing Hook Integration

```bash
# Test hook with sample data (includes project path extraction)
claude-notify hook --test  # Reads from test.json

# Test project path extraction
python examples/test-project-path.py

# Test with specific event type
echo '{"tool_name": "Bash", "tool_input": {"command": "ls"}}' | claude-notify hook --event-type PreToolUse

# Hook command options:
# --event-type, -e: Override event type detection
# --test, -t: Read from test.json instead of stdin
```

#### Project Path Display

For ALL hook events, claude-notify automatically extracts and displays:
- **Project name** in the notification title (e.g., "Claude Tool Request - my-project", "Claude Response Complete - my-project")
- **Full project path** in the notification message (e.g., "Project: my-project (/home/user/projects/my-project)")

This helps you identify which Claude session/project needs your attention when working on multiple projects, regardless of the event type.

### Manual Usage

#### Send a notification

```bash
# Basic notification
claude-notify send

# Custom notification
claude-notify send --title "Custom Title" --message "Custom message" --urgency critical

# Without sound
claude-notify send --no-sound
```

#### Watch mode

Monitor Claude sessions for activity that requires your attention:

```bash
# Monitor current project (checks every 30 seconds)
claude-notify watch

# Monitor all Claude projects
claude-notify watch --all-projects

# Custom check interval with verbose output
claude-notify watch --interval 10 --verbose

# Monitor specific project
cd /path/to/project && claude-notify watch
```

Watch mode features:
- **Real-time monitoring** of Claude transcript files
- **Smart detection** of when Claude needs your input
- **Project-aware** notifications showing which project needs attention
- **Pattern matching** for questions, waiting states, and errors
- **One-time notifications** per session (won't spam you)

### Configuration

```bash
# Show current configuration
claude-notify config show

# Set configuration values
claude-notify config set timeout 15
claude-notify config set sound false
claude-notify config set urgency critical

# Reset to defaults
claude-notify config reset
```

### System check

Check if your system is properly configured:

```bash
claude-notify check
```

## Configuration Options

Configuration is stored in:
- Linux/macOS: `~/.config/claude-notify/config.yaml`
- Windows: `%APPDATA%\claude-notify\config.yaml`

Available options:
- `timeout`: Notification display duration in seconds (default: 10)
- `sound`: Play notification sound (default: true)
- `urgency`: Notification urgency level - low, normal, critical (default: normal)
- `interval`: Watch mode check interval in seconds (default: 300)
- `title`: Default notification title
- `message`: Default notification message
- `telegram_enabled`: Also send notifications to Telegram (default: false)
- `telegram_bot_token`: Telegram bot token from @BotFather (secret; shown masked)
- `telegram_chat_id`: Destination Telegram chat id

> The `telegram_bot_token` and `telegram_chat_id` can also be supplied via the
> `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` environment variables. The config
> file takes precedence: an environment variable is read only when the matching
> config value is empty.

## Telegram Notifications

In addition to native desktop notifications, claude-notify can mirror alerts to a
Telegram chat. This is an **opt-in, outbound-only** channel (it sends messages; it
never reads replies) and uses only the Python standard library — no extra
dependencies.

### 1. Create a bot and get a token

1. Open Telegram and start a chat with [@BotFather](https://t.me/BotFather).
2. Send `/newbot` and follow the prompts to name your bot.
3. BotFather replies with a **bot token** such as
   `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`.

### 2. Find your chat id

1. Send any message to your new bot (or add it to a group and post a message).
2. Open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser.
3. Copy the numeric `chat.id` from the JSON response — that is your **chat id**.

### 3. Configure claude-notify

Store the credentials in the config file:

```bash
claude-notify config set telegram_enabled true
claude-notify config set telegram_bot_token 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
claude-notify config set telegram_chat_id 123456789
```

To keep the secret out of the config file, leave `telegram_bot_token` /
`telegram_chat_id` empty and provide them through environment variables instead.
The config file takes precedence — an environment variable is read only when the
matching config value is empty — so this works only while the config values stay
empty. You still need `telegram_enabled true` in the config to turn the channel
on:

```bash
claude-notify config set telegram_enabled true
export TELEGRAM_BOT_TOKEN="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
export TELEGRAM_CHAT_ID="123456789"
```

The bot token is treated as a secret: it is never printed and is shown masked
(`***`) in `config show` and `config set` output.

### 4. Use it

```bash
# One-off: also deliver this notification to Telegram
claude-notify send --title "Build done" --message "All tests passed" --telegram

# Verify the channel (reports enabled / configured / reachable, token masked)
claude-notify check

# Try the example (prints "not configured" cleanly if no credentials are set)
python examples/telegram_example.py
```

When `telegram_enabled` is true, the `watch` loop and Claude `hook` events also
fan out to Telegram, in addition to desktop notifications. A Telegram failure is
best-effort and never blocks Claude or your desktop alerts.

## Platform-specific Notes

### macOS
- Uses native `osascript` for notifications
- Sound support included

### Linux
- Requires `notify-send` (usually part of `libnotify-bin` package)
- Install with: `sudo apt-get install libnotify-bin` (Debian/Ubuntu)
- Falls back to Python plyer if notify-send is not available

### Windows
- Uses PowerShell for native Windows 10+ toast notifications
- Falls back to Python plyer if PowerShell method fails

## Development

```bash
# Install in development mode (with dev tools: pytest, ruff, mypy)
pip install -e ".[dev]"

# Run the test suite
pytest

# Lint
ruff check .
```

## License

MIT License - see LICENSE file for details

