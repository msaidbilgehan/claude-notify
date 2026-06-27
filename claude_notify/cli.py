"""Command-line interface for Claude Notify"""

import json
import sys
import time
from pathlib import Path
from typing import Optional

import click

from . import __version__
from .config import (
    coerce_config_value,
    get_default_config,
    load_config,
    save_config,
)
from .hook_handler import ChannelOutcome, HookHandler, NotificationResult
from .notifier import ClaudeNotifier
from .session_monitor import ClaudeSessionMonitor
from .telegram import TelegramNotifier, build_telegram_notifier
from .transcript import format_preview


@click.group()
@click.version_option(version=__version__, prog_name="claude-notify")
def cli():
    """Claude Notify - Cross-platform notifications for Claude"""
    pass


@cli.command()
@click.option(
    "--title", "-t",
    default="Claude needs your attention",
    help="Notification title"
)
@click.option(
    "--message", "-m",
    default="Claude is waiting for your response",
    help="Notification message"
)
@click.option(
    "--urgency", "-u",
    type=click.Choice(["low", "normal", "critical"]),
    default="normal",
    help="Notification urgency level"
)
@click.option(
    "--timeout", "-s",
    type=int,
    default=10,
    help="Notification timeout in seconds"
)
@click.option(
    "--sound/--no-sound",
    default=True,
    help="Play notification sound"
)
@click.option(
    "--telegram/--no-telegram",
    default=False,
    help="Also send the notification to the configured Telegram chat"
)
def send(
    title: str,
    message: str,
    urgency: str,
    timeout: int,
    sound: bool,
    telegram: bool
):
    """Send a notification immediately"""
    notifier = ClaudeNotifier()

    success = notifier.send_notification(
        title=title,
        message=message,
        urgency=urgency,
        timeout=timeout,
        sound=sound
    )

    if success:
        click.echo("✓ Notification sent successfully")
    else:
        click.echo("✗ Failed to send notification", err=True)

    # Telegram is an independent, opt-in channel; attempt it even if the
    # desktop send failed, but let the desktop result drive the exit code.
    if telegram:
        telegram_notifier = build_telegram_notifier(load_config())
        if telegram_notifier is None:
            click.echo(
                "✗ Telegram not enabled or configured (set telegram_enabled, "
                "telegram_bot_token, telegram_chat_id)",
                err=True
            )
        elif telegram_notifier.send_notification(
            title=title,
            message=message,
            urgency=urgency,
            timeout=timeout,
            sound=sound
        ):
            click.echo("✓ Telegram notification sent successfully")
        else:
            click.echo("✗ Failed to send Telegram notification", err=True)

    if not success:
        sys.exit(1)


@cli.command()
@click.option(
    "--interval", "-i",
    type=int,
    default=30,
    help="Check interval in seconds (default: 30)"
)
@click.option(
    "--all-projects", "-a",
    is_flag=True,
    help="Monitor all Claude projects, not just current directory"
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    help="Show detailed monitoring information"
)
def watch(interval: int, all_projects: bool, verbose: bool):
    """Watch for Claude activity and notify when attention is needed"""
    config = load_config()
    notifier = ClaudeNotifier()
    telegram = build_telegram_notifier(config)
    desktop_enabled = config.get("desktop_enabled", True)
    monitor = ClaudeSessionMonitor()

    # Track which sessions we've already notified about
    notified_sessions = set()

    scope = "All projects" if all_projects else "Current project only"
    click.echo("🔍 Starting Claude session monitor...")
    click.echo(f"📁 Monitoring: {scope}")
    click.echo(f"⏱️  Check interval: {interval} seconds")
    click.echo("Press Ctrl+C to stop\n")

    try:
        while True:
            # Check for sessions needing attention
            sessions = monitor.check_sessions()

            # Filter to current project if not monitoring all
            if not all_projects and sessions:
                cwd = str(Path.cwd())
                sessions = [s for s in sessions if s["project_path"] == cwd]

            # Process sessions needing attention
            for session in sessions:
                session_key = session["transcript_path"]

                # Only notify once per session unless it changes again
                if session_key not in notified_sessions:
                    # Send notification
                    project_name = session["project"]
                    reason = session["reason"]

                    title = f"🔔 {reason}"
                    if project_name:
                        title = f"{title} · {project_name}"

                    body = []
                    last_response = session.get("last_response")
                    if last_response:
                        body.append(format_preview(last_response))
                        body.append("")  # blank line before the project path
                    body.append(f"📁 {session['project_path']}")
                    message = "\n".join(body)

                    urgency = (
                        "critical" if "question" in reason.lower() else "normal"
                    )

                    # Desktop is gated by config; Telegram is best-effort.
                    # "success" means at least one channel delivered.
                    desktop_success = False
                    if desktop_enabled:
                        desktop_success = notifier.send_notification(
                            title=title,
                            message=message,
                            urgency=urgency,
                            timeout=config.get("timeout", 10),
                            sound=config.get("sound", True)
                        )

                    telegram_success = False
                    if telegram is not None:
                        telegram_success = telegram.send_notification(
                            title=title, message=message, urgency=urgency
                        )

                    success = desktop_success or telegram_success
                    timestamp = time.strftime("%H:%M:%S")
                    if success:
                        notified_sessions.add(session_key)
                        click.echo(
                            f"🔔 [{timestamp}] Notification sent for "
                            f"{project_name}: {reason}"
                        )
                    else:
                        click.echo(
                            f"❌ [{timestamp}] Failed to send notification "
                            f"for {project_name}"
                        )

                    if verbose:
                        click.echo(f"   📄 Transcript: {session['transcript_path']}")
                        click.echo(f"   🕐 Last update: {session['last_update']}")

            # Clear notified sessions if their state changes (file modified again)
            current_states = monitor.transcript_states
            notified_sessions = {
                session for session in notified_sessions
                if session in current_states and
                current_states[session].get("needs_attention", False)
            }

            if verbose and not sessions:
                click.echo(f"[{time.strftime('%H:%M:%S')}] No sessions need attention")

            # Wait for next check
            time.sleep(interval)

    except KeyboardInterrupt:
        click.echo("\n\n✋ Stopping watch mode...")
        click.echo(f"📊 Monitored {len(monitor.transcript_states)} session(s)")
        click.echo("👋 Goodbye!")


@cli.command()
def check():
    """Check notification system dependencies"""
    notifier = ClaudeNotifier()
    deps = notifier.check_dependencies()

    click.echo("Claude Notify System Check")
    click.echo("=" * 30)
    click.echo(f"Operating System: {notifier.system}")
    click.echo(f"Native support: {'✓' if deps['native'] else '✗'}")
    click.echo(f"Notification method: {deps.get('method', 'unknown')}")
    click.echo(f"Plyer fallback: {'✓' if deps['plyer'] else '✗'}")

    # Telegram channel status. Only booleans are printed; the bot token is
    # never echoed (SEC_SENSITIVE_LOG).
    config_data = load_config()
    telegram = TelegramNotifier(
        bot_token=config_data.get("telegram_bot_token") or None,
        chat_id=config_data.get("telegram_chat_id") or None,
        app_name=config_data.get("app_name", "Claude")
    )
    tg_status = telegram.check_telegram()
    enabled = "✓" if config_data.get("telegram_enabled") else "✗"
    configured = "✓" if tg_status["configured"] else "✗"
    reachable = "✓" if tg_status["reachable"] else "✗"
    click.echo("")
    click.echo("Telegram channel:")
    click.echo(f"  Enabled: {enabled}")
    click.echo(f"  Configured: {configured}")
    click.echo(f"  Reachable: {reachable}")

    # Test notification
    click.echo("\nSending test notification...")
    success = notifier.send_notification(
        title="Claude Notify Test",
        message="This is a test notification",
        timeout=5
    )

    if success:
        click.echo("✓ Test notification sent successfully")
    else:
        click.echo("✗ Test notification failed", err=True)


@cli.group()
def config():
    """Manage notification preferences"""
    pass


@config.command("show")
def config_show():
    """Show current configuration"""
    config_data = load_config()
    click.echo("Current Configuration:")
    click.echo("=" * 30)
    for key, value in config_data.items():
        # Mask the bot token so `config show` never prints the secret.
        if key == "telegram_bot_token" and value:
            value = "***"
        click.echo(f"{key}: {value}")


@config.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key: str, value: str) -> None:
    """Set a configuration value"""
    config_data = load_config()

    # Coerce the text argument to the type the key expects (bool/int) so the
    # persisted config keeps native types.
    coerced = coerce_config_value(key, value)
    config_data[key] = coerced
    save_config(config_data)

    # Never echo the bot token back (SEC_SENSITIVE_LOG).
    display_value = "***" if key == "telegram_bot_token" and coerced else coerced
    click.echo(f"✓ Set {key} = {display_value}")


@config.command("reset")
def config_reset():
    """Reset configuration to defaults"""
    save_config(get_default_config())
    click.echo("✓ Configuration reset to defaults")


def _channel_label(outcome: ChannelOutcome) -> str:
    """Render a channel outcome as a short status for verbose hook output."""
    if not outcome.attempted:
        return "— skipped"
    return "✓ sent" if outcome.delivered else "✗ failed"


def _echo_notification_result(result: NotificationResult) -> None:
    """Print a triggered hook notification to stdout (``hook --verbose``)."""
    click.echo(f"🔔 Notification triggered [{result.event_type}]")
    click.echo(f"   Title:    {result.title}")
    click.echo(f"   Urgency:  {result.urgency}")
    # Indent continuation lines so a multi-line body aligns under "Message:".
    body_lines = result.message.splitlines() or [""]
    click.echo(f"   Message:  {body_lines[0]}")
    for line in body_lines[1:]:
        click.echo(f"             {line}")
    click.echo(
        f"   Channels: desktop {_channel_label(result.desktop)}"
        f"  ·  telegram {_channel_label(result.telegram)}"
    )


@cli.command()
@click.option(
    "--event-type", "-e",
    help="Override the event type (PreToolUse, PostToolUse, Notification, "
         "Stop, SubagentStop)"
)
@click.option(
    "--test", "-t",
    is_flag=True,
    help="Test mode - read from test.json file instead of stdin"
)
@click.option(
    "--desktop/--no-desktop",
    "desktop",
    default=None,
    help="Force the desktop channel on/off for this invocation, overriding "
         "the 'desktop_enabled' config value. Use --no-desktop for a "
         "Telegram-only hook."
)
@click.option(
    "--verbose/--quiet", "-v/-q",
    default=False,
    help="Print the triggered notification (title, body, channels) to stdout. "
         "Quiet by default so the hook stays silent in automation."
)
def hook(
    event_type: Optional[str],
    test: bool,
    desktop: Optional[bool],
    verbose: bool
):
    """
    Process Claude Code hook events from JSON input

    This command reads JSON from stdin and sends notifications based on the hook event.
    It's designed to be used in Claude Code hook configurations.

    Example usage in settings.json:

    \b
    {
      "hooks": {
        "PreToolUse": [{
          "matcher": ".*",
          "hooks": [{
            "type": "command",
            "command": "claude-notify hook"
          }]
        }]
      }
    }
    """
    config_data = load_config()
    # --desktop/--no-desktop overrides config when set; otherwise fall back to
    # the 'desktop_enabled' config value (default on).
    desktop_enabled = (
        config_data.get("desktop_enabled", True) if desktop is None else desktop
    )
    handler = HookHandler(
        telegram=build_telegram_notifier(config_data),
        desktop_enabled=desktop_enabled
    )

    if test:
        # Test mode - read from file
        try:
            with open("test.json", "r") as f:
                data = json.load(f)
        except FileNotFoundError:
            click.echo("Error: test.json not found", err=True)
            sys.exit(1)
        except Exception as e:
            click.echo(f"Error reading test.json: {e}", err=True)
            sys.exit(1)
    else:
        # Read JSON from stdin
        data = handler.read_stdin_json()
        if not data:
            click.echo("Error: No JSON data received from stdin", err=True)
            sys.exit(1)

    # Determine event type
    if not event_type:
        event_type = handler.determine_event_type(data)
        if not event_type:
            click.echo("Error: Could not determine event type from JSON data", err=True)
            click.echo(
                "Use --event-type to specify the event type explicitly", err=True
            )
            sys.exit(1)

    # Process the hook event
    result = handler.dispatch_event(event_type, data)

    # Verbose mode surfaces exactly what was sent and where; quiet (the default)
    # keeps the hook silent so it doesn't pollute automated output.
    if verbose:
        _echo_notification_result(result)

    if not result.delivered:
        click.echo("Warning: Failed to send notification", err=True)
        # Don't exit with error code to avoid blocking Claude operations

    # Exit successfully to not block Claude
    sys.exit(0)


def main():
    """Main entry point"""
    cli()


if __name__ == "__main__":
    main()
