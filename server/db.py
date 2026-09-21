from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "poker.db"


class Database:
    """SQLite-backed storage for hand history and player chip balances.

    Each call opens and closes its own connection, which keeps this safe to
    use from FastAPI's threadpool without shared connection state.
    """

    def __init__(self, path: Path | str = DEFAULT_DB_PATH) -> None:
        self.path = Path(path)
        self._schema_ready = False

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        if not self._schema_ready:
            self._init_schema(conn)
            self._schema_ready = True
        return conn

    def _init_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hand_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_code TEXT NOT NULL,
                hand_number INTEGER NOT NULL,
                payouts TEXT NOT NULL,
                stacks_after TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chip_balances (
                player_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                balance INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()

    # ------------------------------------------------------------------
    # Hand history

    def record_hand(
        self,
        room_code: str,
        payouts: dict[str, int],
        stacks_after: dict[str, int],
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            hand_number = conn.execute(
                "SELECT COUNT(*) + 1 FROM hand_history WHERE room_code = ?",
                (room_code,),
            ).fetchone()[0]
            cursor = conn.execute(
                """
                INSERT INTO hand_history (room_code, hand_number, payouts, stacks_after, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (room_code, hand_number, json.dumps(payouts), json.dumps(stacks_after), now),
            )
            return cursor.lastrowid

    def get_hand_history(self, room_code: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM hand_history WHERE room_code = ? ORDER BY hand_number",
                (room_code,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "room_code": row["room_code"],
                "hand_number": row["hand_number"],
                "payouts": json.loads(row["payouts"]),
                "stacks_after": json.loads(row["stacks_after"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Chip balances

    def update_chip_balance(self, player_id: str, name: str, balance: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO chip_balances (player_id, name, balance, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(player_id) DO UPDATE SET
                    name = excluded.name,
                    balance = excluded.balance,
                    updated_at = excluded.updated_at
                """,
                (player_id, name, balance, now),
            )

    def get_chip_balance(self, player_id: str) -> Optional[int]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT balance FROM chip_balances WHERE player_id = ?",
                (player_id,),
            ).fetchone()
        return row["balance"] if row is not None else None


db = Database()
