"""Safely inspect and repair Bitunix TP/SL orders from the VPS.

Examples:
    python run_repair_tpsl.py --list
    python run_repair_tpsl.py --cancel-excess --symbol HYPEUSDT --confirm
    python run_repair_tpsl.py --explain ENAUSDT --confirm
    python run_repair_tpsl.py --prune --confirm

Mutating commands require ``--confirm``. Listing is read-only.
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.dashboard.routes.multi_portfolio import _load_bitunix_details
from app.executor_agent.bitunix_futures_adapter import (
    BITUNIX_PENDING_TP_PATH,
    BitunixCredentials,
    BitunixFuturesExecutorAdapter,
    BitunixLiveSafetyGate,
    _canonical_symbol,
    _canonical_position_side,
    _float,
)
from app.settings.exchange_credentials import load_exchange_credentials


def _adapter(confirm: bool) -> BitunixFuturesExecutorAdapter:
    credentials = load_exchange_credentials(exchange="bitunix")
    if credentials is None or not credentials.is_configured:
        raise SystemExit("Bitunix credentials are not configured")
    return BitunixFuturesExecutorAdapter(
        BitunixCredentials(credentials.api_key, credentials.api_secret),
        safety_gate=BitunixLiveSafetyGate(
            enabled=True, dry_run=not confirm, confirm_live=confirm,
        ),
    )


def _details() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    credentials = load_exchange_credentials(exchange="bitunix")
    if credentials is None or not credentials.is_configured:
        raise SystemExit("Bitunix credentials are not configured")
    details = _load_bitunix_details(credentials.api_key, credentials.api_secret)
    positions = {
        str(row.get("position_id") or ""): row
        for row in details.get("positions", [])
        if isinstance(row, dict) and row.get("position_id")
    }
    return details, positions


def _is_tp(row: dict[str, Any]) -> bool:
    return _float(row.get("tpPrice", row.get("takeProfitPrice"))) > 0


def _is_sl(row: dict[str, Any]) -> bool:
    return _float(row.get("slPrice", row.get("stopLossPrice"))) > 0


def _price(row: dict[str, Any], kind: str) -> float:
    if kind == "tp":
        return _float(row.get("tpPrice", row.get("takeProfitPrice")))
    return _float(row.get("slPrice", row.get("stopLossPrice")))


def list_orders(adapter: BitunixFuturesExecutorAdapter) -> list[dict[str, Any]]:
    rows = adapter.pending_tpsl(limit=1000)
    print(f"pending TPSL rows returned: {len(rows)}")
    if len(rows) >= 1000:
        print("WARNING: exchange returned the query limit; repeat after cancellation")
    for row in rows:
        kind = "TP" if _is_tp(row) else "SL" if _is_sl(row) else "OTHER"
        print(
            f"{kind} id={row.get('id') or row.get('orderId')} "
            f"symbol={row.get('symbol')} position={row.get('positionId') or row.get('position_id')} "
            f"price={_price(row, 'tp' if kind == 'TP' else 'sl'):.12g} "
            f"qty={_float(row.get('tpQty', row.get('slQty', row.get('qty')))):.12g}"
        )
    return rows


def cancel_excess(
    adapter: BitunixFuturesExecutorAdapter, symbol: str | None, *, confirm: bool,
) -> int:
    rows = adapter.pending_tpsl(symbol=symbol, limit=1000)
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        position = str(row.get("positionId") or row.get("position_id") or "")
        if not position:
            continue
        kind = "tp" if _is_tp(row) else "sl" if _is_sl(row) else "other"
        if kind == "other":
            continue
        level = f"{kind}:{_price(row, kind):.12g}"
        grouped.setdefault((position, level), []).append(row)
    excess = [
        row for grouped_rows in grouped.values()
        for row in sorted(grouped_rows, key=lambda item: _float(item.get("tpQty", item.get("slQty", item.get("qty")))), reverse=True)[1:]
    ]
    print(f"rows={len(rows)} excess={len(excess)} mode={'LIVE' if adapter._safety_gate.evaluate() is None else 'DRY-RUN'}")
    for row in excess:
        order_id = str(row.get("id") or row.get("orderId") or "")
        row_symbol = str(row.get("symbol") or symbol or "")
        print(f"cancel id={order_id} symbol={row_symbol} price={_price(row, 'tp' if _is_tp(row) else 'sl')}")
        if confirm and order_id:
            adapter.cancel_tpsl_order(symbol=row_symbol, order_id=order_id)
    return len(excess)


def explain_or_repair(adapter: BitunixFuturesExecutorAdapter, symbol: str, confirm: bool) -> None:
    details, _ = _details()
    compact = _canonical_symbol(symbol)
    positions = [
        row for row in details.get("positions", [])
        if isinstance(row, dict) and _canonical_symbol(row.get("symbol")) == compact
    ]
    if not positions:
        raise SystemExit(f"No open Bitunix position found for {symbol}")
    if not confirm:
        print("DRY-RUN: use --confirm to submit repair orders")
        for row in positions:
            print(json.dumps(row, indent=2, default=str))
        return
    results = adapter.repair_unprotected_positions(
        positions, timestamp=datetime.now(tz=UTC).isoformat(),
    )
    for result in results:
        print(json.dumps({
            "status": result.status,
            "symbol": result.symbol,
            "role": result.meta.get("role"),
            "quantity": result.requested_quantity,
            "price": result.meta.get("raw", {}).get("data", {}).get("tpPrice"),
            "reason": result.reason,
            "raw": result.meta.get("raw"),
        }, indent=2, default=str))


def prune_plans(confirm: bool) -> int:
    details, _ = _details()
    live_keys = {
        (_canonical_symbol(row.get("symbol")), _canonical_position_side(row.get("side")))
        for row in details.get("positions", []) if isinstance(row, dict)
    }
    path = BITUNIX_PENDING_TP_PATH
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print("No readable pending TP plan file")
        return 0
    plans = payload.get("plans", []) if isinstance(payload, dict) else []
    kept: list[dict[str, Any]] = []
    newest: set[tuple[str, str]] = set()
    for plan in reversed([row for row in plans if isinstance(row, dict)]):
        key = (_canonical_symbol(plan.get("symbol")), str(plan.get("position_side") or "").upper())
        if key not in live_keys or key in newest:
            continue
        newest.add(key)
        kept.append(plan)
    kept.reverse()
    removed = len(plans) - len(kept)
    print(f"plans={len(plans)} kept={len(kept)} removed={removed}")
    if confirm and removed:
        backup = path.with_suffix(path.suffix + ".before-prune")
        shutil.copy2(path, backup)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps({"plans": kept}, indent=2), encoding="utf-8")
        temporary.replace(path)
        print(f"backup={backup}")
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", dest="list_rows")
    parser.add_argument("--cancel-excess", action="store_true")
    parser.add_argument("--prune", action="store_true")
    parser.add_argument("--explain")
    parser.add_argument("--symbol")
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    if not any((args.list_rows, args.cancel_excess, args.prune, args.explain)):
        parser.error("choose --list, --cancel-excess, --prune, or --explain")
    if args.prune:
        prune_plans(args.confirm)
    if args.list_rows or args.cancel_excess or args.explain:
        adapter = _adapter(args.confirm)
        if args.list_rows:
            list_orders(adapter)
        if args.cancel_excess:
            cancel_excess(adapter, args.symbol, confirm=args.confirm)
        if args.explain:
            explain_or_repair(adapter, args.explain, args.confirm)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
