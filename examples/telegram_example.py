#!/usr/bin/env python3
"""Example usage of the Claude Notify Telegram channel"""

from claude_notify import TelegramNotifier


def main():
    # Credentials are read from the environment, so no secret is hardcoded.
    # Export these before running (the token comes from @BotFather):
    #   export TELEGRAM_BOT_TOKEN="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
    #   export TELEGRAM_CHAT_ID="123456789"
    notifier = TelegramNotifier(app_name="Claude Assistant")

    print("Claude Notify - Telegram Example")
    print("=" * 40)

    # check_telegram() makes no network call until the channel is configured,
    # so this is safe to run with no credentials set.
    status = notifier.check_telegram()
    print(f"Configured: {'Yes' if status['configured'] else 'No'}")

    if not notifier.is_configured():
        print(
            "Telegram is not configured. Set TELEGRAM_BOT_TOKEN and "
            "TELEGRAM_CHAT_ID, then run this example again."
        )
        return

    print(f"Reachable: {'Yes' if status['reachable'] else 'No'}")

    print("\nSending a test Telegram message...")
    success = notifier.send_notification(
        title="Telegram Channel Test",
        message="Hello from claude-notify! Your Telegram channel works.",
        urgency="normal"
    )
    print(f"   Result: {'Success' if success else 'Failed'}")


if __name__ == "__main__":
    main()
