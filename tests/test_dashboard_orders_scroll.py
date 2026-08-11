"""Regresi scroll panel Orders (Active Orders + Order History).

Bug: scroll tersendat dan selalu kembali ke atas karena container pemilik
scroll (`.ao-scroll` / `.order-history-scroll`) ikut dibuat ulang setiap render,
dan tabel di-rebuild penuh pada setiap `price_update` (~3x/detik).

Catatan: sumber data (paper vs real exchange) kini ditentukan oleh
execution mode dari `/api/settings/execution` (bukan heuristik
`accounts_connected`), lihat `tests/test_dashboard_mode_source.py`.
"""

from __future__ import annotations

from pathlib import Path

DASHBOARD_JS = Path("app/dashboard/static/dashboard.js")


def _js() -> str:
    return DASHBOARD_JS.read_text(encoding="utf-8")


def test_price_update_tidak_merebuild_tabel_active_orders() -> None:
    """handlePriceUpdate hanya patch sel harga/PnL, bukan render ulang tabel."""
    js = _js()

    assert "renderActiveOrders(livePos, livePend)" not in js
    # Satu-satunya pemanggil renderActiveOrders adalah render() snapshot.
    assert js.count("renderActiveOrders(") == 2  # definisi + pemanggilan di render()
    # Patch surgical per-sel tetap dipertahankan.
    assert "byId(`ao-price-${uiSym}`)" in js
    assert "byId(`ao-pnl-${uiSym}`)" in js


def test_real_exchange_pending_orders_feed_active_orders() -> None:
    js = _js()

    assert "const realSourceSelected=!paperMode" in js
    assert "const pendingOrders=realSourceSelected?list(p.multiPortfolio.open_orders)" in js
    assert "renderActiveOrders(positions,pendingOrders)" in js
    assert "renderActiveOrders(positions,p.paper?.pending_orders??[])" not in js


def test_configured_real_exchange_never_falls_back_to_paper_history() -> None:
    js = _js()

    assert "const liveOrders=realSourceSelected?" in js
    assert "closed_positions:list(p.multiPortfolio.closed_positions)" in js


def test_closed_position_summary_and_partial_fills_are_live_order_history_sources() -> None:
    js = _js()

    assert "function orderHistory(orders){ const rows=" in js
    assert 'o?.close_scope==="partial"' in js


def test_bitunix_pending_orders_are_in_realtime_price_universe() -> None:
    websocket = Path("app/dashboard/websocket.py").read_text(encoding="utf-8")

    assert 'multi.get("open_orders")' in websocket
    assert 'PublicHttpExchangeClient("bitunix"' in websocket
    assert '"source": "bitunix_public_ticker"' in websocket
    assert "client.fetch_tickers, symbols" in websocket


def test_realtime_price_source_follows_live_position_exchange() -> None:
    websocket = Path("app/dashboard/websocket.py").read_text(encoding="utf-8")

    assert 'row.get("exchange")' in websocket
    assert "if len(live_exchanges) == 1:" in websocket
    assert "exchange = next(iter(live_exchanges))" in websocket
    assert "seen = set()" in websocket
    assert "symbols = live_symbols or paper_symbols" in websocket
    assert "multi = cached_multi_portfolio()" in websocket
    assert "multi = multi_portfolio()" not in websocket


def test_chart_subscription_starts_bitunix_market_stream() -> None:
    websocket = Path("app/dashboard/websocket.py").read_text(encoding="utf-8")
    js = _js()

    assert 'message.get("type") == "chart_subscribe"' in websocket
    assert "event_hub.subscribe_chart" in websocket
    assert "BitunixTickerWebSocket" in websocket
    assert "self._chart_symbols" in websocket
    assert "type:\"chart_subscribe\"" in js
    assert "subscribeChartSymbol()" in js


def test_chart_updates_active_candle_from_bitunix_price_tick() -> None:
    js = _js()

    assert "function updateRealtimeChart(payload)" in js
    assert "state.tvSeries.update(candle)" in js
    assert 'data.type==="price_update"' in js


def test_snapshot_orders_tidak_memakai_debounce_agresif() -> None:
    """View orders memakai debounce sama dengan view lain (800ms)."""
    js = _js()

    assert 'state.currentView==="orders"?100:800' not in js
    assert "setTimeout(()=>render(data.payload),800)" in js


def test_shell_tabel_dimount_sekali_dan_hanya_tbody_dipatch() -> None:
    """Container pemilik scroll tidak dibuat ulang; hanya tbody yang diganti."""
    js = _js()

    # Shell dideklarasikan sebagai konstanta dengan tbody kosong.
    assert "const AO_SHELL=" in js
    assert "const OH_SHELL=" in js
    assert '<tbody></tbody></table></div><div class="mc-list mobile-only"></div>' in js

    # Render mendelegasikan ke patcher, bukan innerHTML penuh.
    assert "patchActiveOrders(n,rows);" in js
    assert "patchOrderHistory(n,rows);" in js

    # Markup shell hanya muncul sekali (di konstanta), tidak lagi di render body.
    assert js.count('<div class="ao-scroll desktop-only">') == 1
    assert js.count('<div class="order-history-scroll">') == 1


def test_patcher_menjaga_posisi_scroll() -> None:
    """keepScroll menyimpan dan memulihkan scrollTop container."""
    js = _js()

    assert "function keepScroll(" in js
    assert "el.scrollTop" in js
    # Active Orders: pemilik scroll desktop `.ao-scroll`, panel, dan list mobile.
    assert 'keepScroll([node,node.querySelector(".ao-scroll"),cards]' in js
    # Order History: pemilik scroll `#live-orders` sendiri dan wrapper-nya.
    assert 'keepScroll([node,node.querySelector(".order-history-scroll")]' in js


def test_order_history_shows_one_completed_trade_using_entry_values() -> None:
    js = _js()

    assert 'const dirLabel=`${isShort?"SHORT":"LONG"} CLOSED`' in js
    assert "const price=Number(o.entry??o.entry_price??o.price??0)" in js
    assert 'const status="CLOSED"' in js
    # Samakan kolom PnL dengan realizedPNL Bitunix. Net PnL setelah fee/funding
    # tetap tersedia sebagai fallback untuk sumber yang tidak punya realized PnL.
    assert "const pnl=o.pnl??o.realized_pnl??o.net_pnl" in js
    assert "Entry filled on Bitunix" not in js
    assert "Exit filled on Bitunix" not in js
    assert 'reason||"Reason bot tidak tersedia"' in js
    assert "const rows=h.slice(0,100).map" in js
    assert 'reason:o.reason??o.close_label??o.close_reason' in js


def test_order_history_preserves_close_label_and_reason_fallback() -> None:
    js = _js()

    assert 'function orderHistory(orders){ const rows=' in js
    assert 'reason:o.reason??o.close_label??o.close_reason' in js


def test_active_orders_have_realtime_stop_and_trailing_targets() -> None:
    js = _js()

    assert 'id="ao-sl-${esc(sym)}"' in js
    assert 'id="ao-trailing-${esc(sym)}"' in js
    assert "function patchActiveOrderStops(position)" in js
    assert "patchActiveOrderStops(pos)" in js or "patchActiveOrderStops(position)" in js


def test_badge_leverage_mobile_bersebelahan_dengan_badge_arah() -> None:
    """Kartu mobile menampilkan leverage tepat di samping badge LONG/SHORT."""
    js = _js()

    # Badge dibungkus .mc-tags bersama .mc-dir supaya sebaris.
    assert (
        '<span class="mc-tags"><span class="mc-dir ${dirCls}">${dirLabel}</span>${levBadge}</span>'
        in js
    )
    # Leverage aktual diutamakan, fallback ke configured_leverage.
    assert "Number(p.leverage??p.configured_leverage??0)" in js
    # Format gaya exchange: bilangan bulat tanpa desimal, mis. "25x".
    assert 'class="mc-lev">${levRaw%1===0?levRaw:levRaw.toFixed(1)}x<' in js


def test_badge_leverage_disembunyikan_bila_tidak_ada_data() -> None:
    """Tanpa leverage valid (mis. pending order), badge tidak dirender."""
    js = _js()

    assert "Number.isFinite(levRaw)&&levRaw>=1?" in js
    assert 'levRaw.toFixed(1)}x</span>`:""' in js


def test_pnl_persen_snapshot_dan_price_update_memakai_margin_yang_sama() -> None:
    """ROI tidak boleh berganti denominator antara snapshot dan tick harga."""
    js = _js()

    assert "function positionMargin(" in js
    assert "const modal=p.pending_order?0:positionMargin(p,entry,size)" in js
    assert "const modal=positionMargin(pos,entry,size)" in js
    assert "const modal=entry&&size?entry*size" not in js


def test_css_mc_tags_dan_mc_lev_tersedia() -> None:
    """Style badge leverage ada dan sebaris dengan badge arah."""
    css = Path("app/dashboard/static/dashboard.css").read_text(encoding="utf-8")

    assert ".mc-tags{display:flex;align-items:center" in css
    assert ".mc-lev{" in css
    # Memakai token tema yang sudah ada supaya ikut dark/light mode.
    assert "var(--border-2)" in css.split(".mc-lev{")[1].split("}")[0]
