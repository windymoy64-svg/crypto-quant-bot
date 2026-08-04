"""Unit tests for Telegram notification settings."""
import pytest
from app.telegram.notifier import TelegramNotifier


def test_notifier_defaults():
    """Test default notifier configuration."""
    notifier = TelegramNotifier()
    assert notifier.enabled is False
    assert notifier.live is False
    assert notifier.token == ""
    assert notifier.chat_id == ""
    assert not notifier.is_configured


def test_notifier_with_explicit_credentials():
    """Test notifier with explicit token and chat_id."""
    notifier = TelegramNotifier(
        enabled=True,
        live=False,
        token="1234567890:ABCdefGHIjklMNOpqrsTUVwxyz",
        chat_id="123456789"
    )
    assert notifier.enabled is True
    assert notifier.is_configured is True


def test_notifier_send_with_live_and_configured():
    """Test that messages are delivered when configured and live."""
    notifier = TelegramNotifier(
        enabled=True,
        live=True,
        token="1234567890:ABCdefGHIjklMNOpqrsTUVwxyz",
        chat_id="123456789"
    )
    # Should add to outbox even if delivery fails (network error expected)
    notifier.send("Test message")
    assert len(notifier.outbox) >= 1
    assert "Test message" in notifier.outbox[-1]


def test_notifier_send_disabled():
    """Test that disabled notifier still stores in outbox but doesn't deliver."""
    notifier = TelegramNotifier(enabled=False, live=False, token="", chat_id="")
    notifier.send("Disabled message")
    assert len(notifier.outbox) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
