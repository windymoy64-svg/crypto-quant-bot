from __future__ import annotations

import json
from pathlib import Path
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


def test_live_execution_message_contains_operational_fields() -> None:
    row = _payload()["entries"][0]["result"]
    message = TradeReporter().format_live_execution(row["decision"], row["execution"])

    assert "✅ LIVE ENTRY EXECUTED" in message
    assert "HYPE/USDT  •  SHORT" in message
    assert "Status: FILLED" in message
    assert "📦 Quantity: 28.60000000" in message
    assert "📊 Score: 90.0  •  Confluence: 67.0" in message
    assert "🌐 Regime: TRENDING_BEARISH" in message
    assert "🧠 Thesis: bias=BEARISH, confluence=67" in message
    assert "Stop Loss" in message
    assert "TP1" in message
    assert "Bitunix Futures" in message


def test_rejection_reason_is_html_escaped() -> None:
    row = _payload("REJECTED", "amount < minimum")["entries"][0]["result"]
    message = TradeReporter().format_live_execution(row["decision"], row["execution"])

    assert "❌ LIVE ORDER REJECTED" in message
    assert "amount &lt; minimum" in message


def test_submitted_exchange_order_is_not_reported_as_rejected() -> None:
    row = _payload("SUBMITTED")["entries"][0]["result"]
    row["execution"]["success"] = False
    row["execution"]["results"][0]["meta"]["role"] = "entry"
    message = TradeReporter().format_live_execution(row["decision"], row["execution"])

    assert "🟡 LIVE ENTRY SUBMITTED" in message
    assert "Status: SUBMITTED" in message
    assert "❌ LIVE ORDER REJECTED" not in message
    assert "Exchange: exchange accepted" in message


def test_tp_protection_failure_is_reported_as_urgent() -> None:
    row = _payload("SUBMITTED")["entries"][0]["result"]
    row["execution"]["success"] = False
    row["execution"]["errors"] = ["live_entry_take_profit_not_confirmed"]

    message = TradeReporter().format_live_execution(row["decision"], row["execution"])

    assert "🚨 LIVE ENTRY PROTECTION FAILED" in message


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


def test_live_bitunix_close_baseline_delivery_retry_and_dedup(tmp_path: Path) -> None:
    checkpoint = tmp_path / "telegram-close.json"
    old = {
        "position_id": "old", "symbol": "BTCUSDT", "side": "LONG",
        "quantity": 1, "entry_price": 100, "close_price": 101,
        "net_pnl": 1, "closed_at": "2026-08-04T01:00:00+00:00",
    }
    notifier = MagicMock()

    assert run_realtime.notify_new_bitunix_closes(
        notifier, [old], checkpoint_path=checkpoint,
    ) == 0
    notifier.send.assert_not_called()

    new = {
        "position_id": "new", "symbol": "ADAUSDT", "side": "SHORT",
        "quantity": 23.5, "entry_price": 0.184, "close_price": 0.181,
        "net_pnl": 0.07, "reason": "take_profit_1",
        "closed_at": "2026-08-04T02:00:00+00:00",
    }
    notifier.send.return_value = False
    assert run_realtime.notify_new_bitunix_closes(
        notifier, [old, new], checkpoint_path=checkpoint,
    ) == 0

    notifier.send.return_value = True
    assert run_realtime.notify_new_bitunix_closes(
        notifier, [old, new], checkpoint_path=checkpoint,
    ) == 1
    assert "CLOSE POSITION" in notifier.send.call_args.args[0]
    assert "ADAUSDT" in notifier.send.call_args.args[0]

    notifier.reset_mock()
    assert run_realtime.notify_new_bitunix_closes(
        notifier, [old, new], checkpoint_path=checkpoint,
    ) == 0
    notifier.send.assert_not_called()


def test_live_pipeline_notification_is_deduplicated() -> None:
    notifier = MagicMock()
    notifier.send.return_value = True
    run_realtime._telegram_event_sent_at.clear()

    assert run_realtime.notify_live_pipeline_executions(notifier, _payload()) == 1
    assert run_realtime.notify_live_pipeline_executions(notifier, _payload()) == 0
    notifier.send.assert_called_once()


def test_live_partial_close_is_detected_from_quantity_diff(tmp_path: Path) -> None:
    checkpoint = tmp_path / "telegram-partial.json"
    notifier = MagicMock()
    notifier.send.return_value = True
    initial = {
        "ADA/USDT": {
            "symbol": "ADA/USDT", "side": "LONG", "quantity": 23.5,
            "entry_price": 0.184, "last_price": 0.189,
        },
    }

    assert run_realtime.notify_new_bitunix_partial_closes(
        notifier, initial, checkpoint_path=checkpoint,
    ) == 0
    reduced = {"ADA/USDT": {**initial["ADA/USDT"], "quantity": 12.0}}
    assert run_realtime.notify_new_bitunix_partial_closes(
        notifier, reduced, checkpoint_path=checkpoint,
        close_fills=[{
            "symbol": "ADAUSDT", "status": "FILLED", "reduceOnly": True,
            "tradeQty": "11.5", "dealAvgPrice": "0.189",
            "realizedPNL": "0.0122",
        }],
    ) == 1
    message = notifier.send.call_args.args[0]
    assert "🟡 PARTIAL CLOSE" in message
    assert "Closed: 11.50000000" in message
    assert "Reason: Take Profit" in message
    assert "Realized P&L: $0.01" in message

    notifier.reset_mock()
    assert run_realtime.notify_new_bitunix_partial_closes(
        notifier, reduced, checkpoint_path=checkpoint,
    ) == 0
    notifier.send.assert_not_called()
