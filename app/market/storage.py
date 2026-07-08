from __future__ import annotations

import sqlite3
from pathlib import Path

from app.core.models import Candle


DEFAULT_HISTORY_DB = Path("data/market_history.sqlite3")


class SQLiteCandleStorage:
    def __init__(self, database_path: str | Path = DEFAULT_HISTORY_DB) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def load_candles(self, exchange: str, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT symbol, timestamp, open, high, low, close, volume
                FROM candles
                WHERE exchange = ? AND symbol = ? AND timeframe = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (exchange, symbol, timeframe, limit),
            ).fetchall()

        return [
            Candle(
                symbol=row[0],
                timestamp=row[1],
                open=float(row[2]),
                high=float(row[3]),
                low=float(row[4]),
                close=float(row[5]),
                volume=float(row[6]),
            )
            for row in reversed(rows)
        ]

    def save_candles(self, exchange: str, timeframe: str, candles: list[Candle]) -> None:
        if not candles:
            return

        with self._connect() as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO candles (
                    exchange, symbol, timeframe, timestamp, open, high, low, close, volume
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        exchange,
                        candle.symbol,
                        timeframe,
                        candle.timestamp,
                        candle.open,
                        candle.high,
                        candle.low,
                        candle.close,
                        candle.volume,
                    )
                    for candle in candles
                ],
            )

    def get_cache_updated_at(self, cache_key: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT updated_at FROM cache_metadata WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
        return str(row[0]) if row else None

    def set_cache_updated_at(self, cache_key: str, updated_at: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO cache_metadata (cache_key, updated_at)
                VALUES (?, ?)
                """,
                (cache_key, updated_at),
            )

    def checkpoint(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS candles (
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    PRIMARY KEY (exchange, symbol, timeframe, timestamp)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS cache_metadata (
                    cache_key TEXT PRIMARY KEY,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_candles_lookup
                ON candles (exchange, symbol, timeframe, timestamp)
                """
            )