"""Stratul de bază de date (SQLite) pentru contracte, demisii și date de intrare."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Optional

from config import DB_PATH, LOCAL_TZ
from utils import now_iso


class Database:
    def __init__(self, path: str):
        self.path = Path(path)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            # Railway fără volum montat: cădem pe un fișier local.
            self.path = Path("legacy_ems.db")
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = asyncio.Lock()
        self._migrate()

    # ------------------------------------------------------------------
    # MIGRARE
    # ------------------------------------------------------------------
    def _migrate(self) -> None:
        with self.conn:
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS join_dates (
                    user_id TEXT PRIMARY KEY,
                    join_date TEXT NOT NULL,
                    set_by TEXT NOT NULL,
                    set_at TEXT NOT NULL
                )
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS resignations (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    channel_id TEXT NOT NULL,
                    message_id TEXT UNIQUE NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    decided_at TEXT,
                    decided_by TEXT,
                    reason TEXT,
                    request_reason TEXT,
                    request_name TEXT,
                    request_hours TEXT,
                    join_date TEXT,
                    days INTEGER
                )
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS contracts (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    guild_id TEXT NOT NULL,
                    channel_id TEXT,
                    message_id TEXT,
                    nume_ic TEXT NOT NULL,
                    cnp TEXT NOT NULL,
                    functie TEXT,
                    recruiter_id TEXT NOT NULL,
                    recruiter_signature TEXT NOT NULL,
                    recruiter_grade TEXT NOT NULL,
                    member_signature TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    signed_at TEXT,
                    terminated_at TEXT,
                    terminated_by TEXT,
                    terminated_signature TEXT,
                    terminated_grade TEXT,
                    terminated_reason TEXT,
                    worked_seconds INTEGER
                )
                """
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_resignations_user_status ON resignations(user_id, status)"
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_resignations_message ON resignations(message_id)"
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_contracts_user_status ON contracts(user_id, status)"
            )

            columns = {row[1] for row in self.conn.execute("PRAGMA table_info(resignations)").fetchall()}
            for column in ("request_reason", "request_name", "request_hours", "contract_id"):
                if column not in columns:
                    self.conn.execute(f"ALTER TABLE resignations ADD COLUMN {column} TEXT")

    # ------------------------------------------------------------------
    # DATA INTRĂRII
    # ------------------------------------------------------------------
    async def set_join_date(self, user_id: int, join_dt, set_by: int) -> None:
        async with self.lock:
            with self.conn:
                self.conn.execute(
                    """
                    INSERT INTO join_dates(user_id, join_date, set_by, set_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET
                        join_date=excluded.join_date,
                        set_by=excluded.set_by,
                        set_at=excluded.set_at
                    """,
                    (str(user_id), join_dt.astimezone(LOCAL_TZ).isoformat(), str(set_by), now_iso()),
                )

    async def get_join_date(self, user_id: int) -> Optional[str]:
        async with self.lock:
            row = self.conn.execute(
                "SELECT join_date FROM join_dates WHERE user_id = ?",
                (str(user_id),),
            ).fetchone()
            return row["join_date"] if row else None

    # ------------------------------------------------------------------
    # CONTRACTE
    # ------------------------------------------------------------------
    async def create_contract(
        self,
        contract_id: str,
        user_id: int,
        guild_id: int,
        channel_id: int,
        nume_ic: str,
        cnp: str,
        functie: str,
        recruiter_id: int,
        recruiter_signature: str,
        recruiter_grade: str,
    ) -> dict:
        async with self.lock:
            with self.conn:
                # Un singur contract in asteptare per membru.
                self.conn.execute(
                    "UPDATE contracts SET status = 'CANCELLED' WHERE user_id = ? AND status = 'PENDING_SIGN'",
                    (str(user_id),),
                )
                self.conn.execute(
                    """
                    INSERT INTO contracts(
                        id, user_id, guild_id, channel_id, nume_ic, cnp, functie,
                        recruiter_id, recruiter_signature, recruiter_grade, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING_SIGN', ?)
                    """,
                    (
                        contract_id,
                        str(user_id),
                        str(guild_id),
                        str(channel_id),
                        nume_ic,
                        cnp,
                        functie,
                        str(recruiter_id),
                        recruiter_signature,
                        recruiter_grade,
                        now_iso(),
                    ),
                )
                row = self.conn.execute("SELECT * FROM contracts WHERE id = ?", (contract_id,)).fetchone()
                return dict(row)

    async def set_contract_message(self, contract_id: str, message_id: int) -> None:
        async with self.lock:
            with self.conn:
                self.conn.execute(
                    "UPDATE contracts SET message_id = ? WHERE id = ?",
                    (str(message_id), contract_id),
                )

    async def get_contract(self, contract_id: str) -> Optional[dict]:
        async with self.lock:
            row = self.conn.execute("SELECT * FROM contracts WHERE id = ?", (contract_id,)).fetchone()
            return dict(row) if row else None

    async def get_contract_by_message(self, message_id: int) -> Optional[dict]:
        async with self.lock:
            row = self.conn.execute(
                "SELECT * FROM contracts WHERE message_id = ? ORDER BY created_at DESC LIMIT 1",
                (str(message_id),),
            ).fetchone()
            return dict(row) if row else None

    async def refuse_contract(self, contract_id: str, refused_at_iso: str) -> Optional[dict]:
        """Angajatul a apăsat `Refuză contractul`."""
        async with self.lock:
            with self.conn:
                row = self.conn.execute("SELECT * FROM contracts WHERE id = ?", (contract_id,)).fetchone()
                if not row:
                    return None
                if row["status"] != "PENDING_SIGN":
                    return dict(row)
                self.conn.execute(
                    """
                    UPDATE contracts
                    SET status = 'REFUSED', terminated_at = ?, terminated_reason = 'Contract refuzat de angajat.'
                    WHERE id = ?
                    """,
                    (refused_at_iso, contract_id),
                )
                updated = self.conn.execute("SELECT * FROM contracts WHERE id = ?", (contract_id,)).fetchone()
                return dict(updated)

    async def get_pending_contract(self, user_id: int) -> Optional[dict]:
        async with self.lock:
            row = self.conn.execute(
                """
                SELECT * FROM contracts
                WHERE user_id = ? AND status = 'PENDING_SIGN'
                ORDER BY created_at DESC LIMIT 1
                """,
                (str(user_id),),
            ).fetchone()
            return dict(row) if row else None

    async def get_active_contract(self, user_id: int) -> Optional[dict]:
        async with self.lock:
            row = self.conn.execute(
                """
                SELECT * FROM contracts
                WHERE user_id = ? AND status = 'SIGNED'
                ORDER BY signed_at DESC LIMIT 1
                """,
                (str(user_id),),
            ).fetchone()
            return dict(row) if row else None

    async def get_last_contract(self, user_id: int) -> Optional[dict]:
        async with self.lock:
            row = self.conn.execute(
                """
                SELECT * FROM contracts
                WHERE user_id = ? AND status IN ('SIGNED', 'TERMINATED')
                ORDER BY COALESCE(signed_at, created_at) DESC LIMIT 1
                """,
                (str(user_id),),
            ).fetchone()
            return dict(row) if row else None

    async def sign_contract(self, contract_id: str, member_signature: str, signed_at_iso: str) -> Optional[dict]:
        async with self.lock:
            with self.conn:
                row = self.conn.execute("SELECT * FROM contracts WHERE id = ?", (contract_id,)).fetchone()
                if not row:
                    return None
                if row["status"] != "PENDING_SIGN":
                    return dict(row)
                self.conn.execute(
                    "UPDATE contracts SET status = 'SIGNED', member_signature = ?, signed_at = ? WHERE id = ?",
                    (member_signature, signed_at_iso, contract_id),
                )
                updated = self.conn.execute("SELECT * FROM contracts WHERE id = ?", (contract_id,)).fetchone()
                return dict(updated)

    async def cancel_contract(self, contract_id: str) -> None:
        async with self.lock:
            with self.conn:
                self.conn.execute(
                    "UPDATE contracts SET status = 'CANCELLED' WHERE id = ? AND status = 'PENDING_SIGN'",
                    (contract_id,),
                )

    async def terminate_contract(
        self,
        contract_id: str,
        terminated_by: int,
        terminated_signature: str,
        terminated_grade: str,
        terminated_reason: str,
        terminated_at_iso: str,
        worked_seconds: Optional[int],
    ) -> Optional[dict]:
        async with self.lock:
            with self.conn:
                self.conn.execute(
                    """
                    UPDATE contracts
                    SET status = 'TERMINATED', terminated_by = ?, terminated_signature = ?,
                        terminated_grade = ?, terminated_reason = ?, terminated_at = ?, worked_seconds = ?
                    WHERE id = ?
                    """,
                    (
                        str(terminated_by),
                        terminated_signature,
                        terminated_grade,
                        terminated_reason,
                        terminated_at_iso,
                        worked_seconds,
                        contract_id,
                    ),
                )
                row = self.conn.execute("SELECT * FROM contracts WHERE id = ?", (contract_id,)).fetchone()
                return dict(row) if row else None

    async def get_recent_contracts(self, limit: int = 10) -> list[dict]:
        async with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM contracts ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # DEMISII
    # ------------------------------------------------------------------
    async def create_resignation(
        self,
        request_id: str,
        user_id: int,
        channel_id: int,
        message_id: int,
        join_date_iso: Optional[str],
        days: Optional[int],
        request_reason: str,
        request_name: str,
        request_hours: str,
        contract_id: Optional[str] = None,
    ) -> None:
        async with self.lock:
            with self.conn:
                self.conn.execute(
                    """
                    INSERT INTO resignations(
                        id, user_id, channel_id, message_id, status, created_at, join_date, days,
                        request_reason, request_name, request_hours, contract_id
                    ) VALUES (?, ?, ?, ?, 'PENDING', ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        request_id,
                        str(user_id),
                        str(channel_id),
                        str(message_id),
                        now_iso(),
                        join_date_iso,
                        days,
                        request_reason,
                        request_name,
                        request_hours,
                        contract_id,
                    ),
                )

    async def get_pending_for_user(self, user_id: int) -> Optional[dict]:
        async with self.lock:
            row = self.conn.execute(
                """
                SELECT * FROM resignations
                WHERE user_id = ? AND status = 'PENDING'
                ORDER BY created_at DESC LIMIT 1
                """,
                (str(user_id),),
            ).fetchone()
            return dict(row) if row else None

    async def get_by_message_id(self, message_id: int) -> Optional[dict]:
        async with self.lock:
            row = self.conn.execute(
                "SELECT * FROM resignations WHERE message_id = ? LIMIT 1",
                (str(message_id),),
            ).fetchone()
            return dict(row) if row else None

    async def decide(
        self,
        message_id: int,
        status: str,
        decided_by: int,
        reason: Optional[str],
        join_date_iso: Optional[str],
        days: Optional[int],
    ) -> Optional[dict]:
        async with self.lock:
            with self.conn:
                row = self.conn.execute(
                    "SELECT * FROM resignations WHERE message_id = ? LIMIT 1",
                    (str(message_id),),
                ).fetchone()
                if not row:
                    return None
                if row["status"] != "PENDING":
                    return dict(row)

                self.conn.execute(
                    """
                    UPDATE resignations
                    SET status = ?, decided_at = ?, decided_by = ?, reason = ?, join_date = ?, days = ?
                    WHERE message_id = ?
                    """,
                    (status, now_iso(), str(decided_by), reason, join_date_iso, days, str(message_id)),
                )
                updated = self.conn.execute(
                    "SELECT * FROM resignations WHERE message_id = ? LIMIT 1",
                    (str(message_id),),
                ).fetchone()
                return dict(updated) if updated else None

    async def get_recent_resignations(self, limit: int = 10) -> list[dict]:
        async with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM resignations ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]


db = Database(DB_PATH)
