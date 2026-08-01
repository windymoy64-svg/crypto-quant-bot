from pathlib import Path


def test_live_exchange_positions_are_merged_into_agent_monitor() -> None:
    javascript = Path("app/dashboard/static/dashboard.js").read_text(encoding="utf-8")

    assert "function liveExchangePositions()" in javascript
    assert "renderAgentMonitor(payload.monitor || [], livePositions)" in javascript
    assert 'replace(/[^A-Z0-9]/g,"")' in javascript
    assert "Live Bitunix position · awaiting Decision Agent review" in javascript


def test_entry_candidate_labels_and_colors_are_normalized() -> None:
    javascript = Path("app/dashboard/static/dashboard.js").read_text(encoding="utf-8")

    assert 'processing ? "Processing"' in javascript
    assert 'executionFailed ? "Rejected"' in javascript
    assert '=== "ENTRY" ? "Entry"' in javascript
    assert "/PROCESSING|PENDING|OPEN|NEW|RECONNECT/" in javascript


def test_live_bitunix_history_and_compact_symbols_feed_dashboard() -> None:
    javascript = Path("app/dashboard/static/dashboard.js").read_text(encoding="utf-8")
    template = Path("app/dashboard/templates/index.html").read_text(encoding="utf-8")

    assert "p.multiPortfolio.order_history=list(p.multiPortfolio.order_history)" in javascript
    assert "order_history:list(p.multiPortfolio.order_history)" in javascript
    assert "function symbolKey(symbol)" in javascript
    assert "symbolKey(pos.symbol)!==tickKey" in javascript
    assert "const uiSym=uiPosition?.symbol||sym" in javascript
    assert "multi?.closed_positions" in template
    assert "position.realized_pnl ?? position.net_pnl" in template
    assert "position.net_pnl ?? position.realized_pnl" not in template
    assert "opened_trades: opened" in template
    assert "realized_exits: exits" in template
    assert "const openedByPosition = new Map()" in template
    assert "[...exits, ...positions]" in template
    assert "const filled = history.filter" not in template
    assert "closed_positions:list(p.multiPortfolio.closed_positions)" in javascript
    assert "list(orders?.closed_positions).length" in javascript
    assert 'inSession(item, "exit")' in template
    assert 'inSession(item, "open")' in template