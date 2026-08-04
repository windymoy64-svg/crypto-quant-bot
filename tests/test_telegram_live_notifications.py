from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import run_realtime
from app.telegram.notifier import TelegramNotifier
from app.telegram.trade_reporter import TradeReporter
from app.telegram.trade_reporter import send_trade_report


def _payload(status: str = "FILLED", reason: str = "") -> dict:
    return {
        "entries": [{
            "symbol": "HYPE/USDT",
            "result": {
                "decision": {
                    "action": "ENTRY_SELL", "symbol": "HYPE/USDT",
                    "confidence_score": 90, "confluence_score": 67,
                    "regime": "TRENDING_BEARISH",
                    "reasons": ["bias=BEARISH", "confluence=67"],
                    "entry_plan": {
                        "side": "SELL", "entry_price": 52.3,
                        "stop_loss": 53.1, "take_profit_1": 50.7,
                    },
                },
                "execution": {
                    "success": status == "FILLED", "errors": [],
                    "plan": {"symbol": "HYPE/USDT"},
                    "results": [{
                        "status": status, "order_id": "order-1" if status == "FILLED" else "",
                        "requested_quantity": 28.6,
                        "filled_quantity": 28.6 if status == "FILLED" else 0,
                        "average_price": 52.3 if status == "FILLED" else 0,
                        "reason": reason,
                        "meta": {"role": "entry"},
                    }],
                },
            },
        }],
        "monitor": [],
    }


def test_live_execution_message_is_readable_html() -> None:
    row = _payload()["entries"][0]["result"]
    message = TradeReporter().format_live_execution(row["decision"], row["execution"])

    assert "✅ <b>LIVE ENTRY EXECUTED</b>" in message
    assert "<b>HYPE/USDT</b>" in message
    assert "<b>SHORT</b>" in message
    assert "Stop Loss" in message
    assert "TP1" in message
    assert "Bitunix Futures" in message


def test_rejection_reason_is_html_escaped() -> None:
    row = _payload("REJECTED", "amount < minimum")["entries"][0]["result"]
    message = TradeReporter().format_live_execution(row["decision"], row["execution"])

    assert "❌ <b>LIVE ORDER REJECTED</b>" in message
    assert "amount &lt; minimum" in message


def test_notifier_posts_html_and_reports_success() -> None:
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b'{"ok":true}'
    response.__exit__.return_value = False
    notifier = TelegramNotifier(enabled=True, live=True, token="token", chat_id="chat")

    with patch("urllib.request.urlopen", return_value=response) as urlopen:
        assert notifier.send("<b>Hello</b>") is True

    body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
    assert body["parse_mode"] == "HTML"
    assert body["disable_web_page_preview"] is True
    assert notifier.delivered_count == 1


def test_legacy_plain_text_does_not_enable_html_parser() -> None:
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b'{"ok":true}'
    response.__exit__.return_value = False
    notifier = TelegramNotifier(enabled=True, live=True, token="token", chat_id="chat")

    with patch("urllib.request.urlopen", return_value=response) as urlopen:
        assert notifier.send("MA5 < MA20") is True

    body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
    assert "parse_mode" not in body


def test_close_trade_report_is_delivered_to_telegram() -> None:
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b'{"ok":true}'
    response.__exit__.return_value = False
    notifier = TelegramNotifier(enabled=True, live=True, token="token", chat_id="chat")
    event = {
        "type": "closed",
        "position": {
            "symbol": "ADA/USDT", "side": "BUY", "entry": 0.184,
            "exit_price": 0.189, "original_size": 23.5,
            "remaining_size": 0, "realized_pnl": 0.1175,
            "stop_loss": 0.181, "take_profit": [0.189, 0.192, 0.195],
            "tp_hit": [True, False, False], "close_reason": "take_profit_1",
        },
    }

    with patch("urllib.request.urlopen", return_value=response) as urlopen:
        send_trade_report(notifier, event)

    assert urlopen.call_count == 1
    body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
    assert "CLOSE POSITION" in body["text"]
    assert "ADA/USDT" in body["text"]


def test_live_pipeline_notification_is_deduplicated() -> None:
    notifier = MagicMock()
    notifier.send.return_value = True
    run_realtime._telegram_event_sent_at.clear()

    assert run_realtime.notify_live_pipeline_executions(notifier, _payload()) == 1
    assert run_realtime.notify_live_pipeline_executions(notifier, _payload()) == 0
    notifier.send.assert_called_once()