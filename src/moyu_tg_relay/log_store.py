"""Structured event and audit log storage with automatic 15-day retention.

Uses SQLite with Write-Ahead Logging (WAL) for thread-safe, performant,
zero-dependency persistence in the local environment.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Mapping, Optional, Union


DEFAULT_RETENTION_DAYS = 15


class RelayLogStore:
    """Thread-safe SQLite persistent store for Telegram Relay activity logs."""

    def __init__(
        self,
        db_path: Union[str, Path] = "./.state/relay_logs.db",
        retention_days: int = DEFAULT_RETENTION_DAYS,
        *,
        clock=time.time,
    ) -> None:
        self.db_path = Path(db_path)
        self.retention_days = max(1, int(retention_days))
        self._clock = clock
        self._lock = threading.RLock()
        self._write_count = 0
        self._prune_interval = 200

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=10.0,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._get_connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS relay_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    level TEXT NOT NULL,
                    category TEXT NOT NULL,
                    message TEXT NOT NULL,
                    provider TEXT DEFAULT '',
                    account TEXT DEFAULT '',
                    request_id TEXT DEFAULT '',
                    detail TEXT DEFAULT '',
                    extra_json TEXT DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON relay_logs(timestamp);
                CREATE INDEX IF NOT EXISTS idx_logs_level ON relay_logs(level);
                CREATE INDEX IF NOT EXISTS idx_logs_category ON relay_logs(category);
                CREATE INDEX IF NOT EXISTS idx_logs_request_id ON relay_logs(request_id);
                CREATE INDEX IF NOT EXISTS idx_logs_provider ON relay_logs(provider);
                """
            )
        self.prune()

    def record(
        self,
        level: str,
        category: str,
        message: str,
        *,
        provider: str = "",
        account: str = "",
        request_id: str = "",
        detail: str = "",
        extra: Optional[Mapping[str, Any]] = None,
    ) -> int:
        """Record an event to the log database."""
        now = self._clock()
        utc_dt = dt.datetime.fromtimestamp(now, tz=dt.timezone.utc)
        created_at = utc_dt.isoformat().replace("+00:00", "Z")

        extra_str = "{}"
        if extra:
            try:
                extra_str = json.dumps(dict(extra), ensure_ascii=False)
            except Exception:
                extra_str = json.dumps({"raw": str(extra)})

        level_clean = str(level or "INFO").strip().upper()
        category_clean = str(category or "system").strip().lower()
        msg_clean = str(message or "").strip()
        provider_clean = str(provider or "").strip().lower()
        account_clean = str(account or "").strip()
        req_clean = str(request_id or "").strip()
        detail_clean = str(detail or "").strip()

        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO relay_logs (
                    timestamp, created_at, level, category, message,
                    provider, account, request_id, detail, extra_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now,
                    created_at,
                    level_clean,
                    category_clean,
                    msg_clean,
                    provider_clean,
                    account_clean,
                    req_clean,
                    detail_clean,
                    extra_str,
                ),
            )
            inserted_id = cursor.lastrowid or 0
            self._write_count += 1
            if self._write_count >= self._prune_interval:
                self._write_count = 0
                self._prune_locked(conn)

            return inserted_id

    def _prune_locked(
        self,
        conn: sqlite3.Connection,
        retention_days: Optional[int] = None,
    ) -> int:
        days = max(1, int(retention_days or self.retention_days))
        cutoff = self._clock() - (days * 86400.0)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM relay_logs WHERE timestamp < ?", (cutoff,))
        return cursor.rowcount

    def prune(self, retention_days: Optional[int] = None) -> int:
        """Prune logs older than retention_days (default configured retention days)."""
        with self._lock, self._get_connection() as conn:
            return self._prune_locked(conn, retention_days=retention_days)

    def query_logs(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        level: Optional[str] = None,
        category: Optional[str] = None,
        search: Optional[str] = None,
        since: Optional[float] = None,
        until: Optional[float] = None,
        provider: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Query paginated logs with multi-condition filtering."""
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 500))
        offset = (page - 1) * page_size

        where_clauses: list[str] = []
        params: list[Any] = []

        if level:
            lvl = str(level).strip().upper()
            if lvl != "ALL":
                where_clauses.append("level = ?")
                params.append(lvl)

        if category:
            cat = str(category).strip().lower()
            if cat != "all":
                where_clauses.append("category = ?")
                params.append(cat)

        if provider:
            prv = str(provider).strip().lower()
            if prv != "all":
                where_clauses.append("provider = ?")
                params.append(prv)

        if request_id:
            where_clauses.append("request_id LIKE ?")
            params.append(f"%{request_id.strip()}%")

        if since is not None and since > 0:
            where_clauses.append("timestamp >= ?")
            params.append(float(since))

        if until is not None and until > 0:
            where_clauses.append("timestamp <= ?")
            params.append(float(until))

        if search:
            search_str = f"%{str(search).strip()}%"
            where_clauses.append(
                "(message LIKE ? OR detail LIKE ? OR request_id LIKE ? OR account LIKE ? OR extra_json LIKE ?)"
            )
            params.extend([search_str] * 5)

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        with self._lock, self._get_connection() as conn:
            # Count total matching rows
            count_cursor = conn.cursor()
            count_cursor.execute(f"SELECT COUNT(*) FROM relay_logs {where_sql}", params)
            total = count_cursor.fetchone()[0]

            # Query paginated rows
            query_params = list(params)
            query_params.extend([page_size, offset])
            data_cursor = conn.cursor()
            data_cursor.execute(
                f"""
                SELECT id, timestamp, created_at, level, category, message,
                       provider, account, request_id, detail, extra_json
                FROM relay_logs
                {where_sql}
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                query_params,
            )

            rows = []
            for row in data_cursor.fetchall():
                extra_parsed: dict[str, Any] = {}
                raw_extra = row["extra_json"]
                if raw_extra:
                    try:
                        extra_parsed = json.loads(raw_extra)
                    except Exception:
                        extra_parsed = {"raw": raw_extra}

                rows.append(
                    {
                        "id": row["id"],
                        "timestamp": row["timestamp"],
                        "created_at": row["created_at"],
                        "level": row["level"],
                        "category": row["category"],
                        "message": row["message"],
                        "provider": row["provider"],
                        "account": row["account"],
                        "request_id": row["request_id"],
                        "detail": row["detail"],
                        "extra": extra_parsed,
                    }
                )

            return {
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": (total + page_size - 1) // page_size if total > 0 else 1,
                "logs": rows,
            }

    def get_stats(self) -> dict[str, Any]:
        """Aggregate statistics for admin dashboard overview."""
        now = self._clock()
        last_24h = now - 86400.0

        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()

            # Total logs in database
            cursor.execute("SELECT COUNT(*) FROM relay_logs")
            total_logs = cursor.fetchone()[0]

            # Logs in last 24h
            cursor.execute("SELECT COUNT(*) FROM relay_logs WHERE timestamp >= ?", (last_24h,))
            logs_24h = cursor.fetchone()[0]

            # Count by level (last 24h)
            cursor.execute(
                """
                SELECT level, COUNT(*) as cnt
                FROM relay_logs
                WHERE timestamp >= ?
                GROUP BY level
                """,
                (last_24h,),
            )
            level_counts = {row["level"]: row["cnt"] for row in cursor.fetchall()}

            # Count by category (last 24h)
            cursor.execute(
                """
                SELECT category, COUNT(*) as cnt
                FROM relay_logs
                WHERE timestamp >= ?
                GROUP BY category
                """,
                (last_24h,),
            )
            category_counts = {row["category"]: row["cnt"] for row in cursor.fetchall()}

            # Total distinct OTP requests recorded
            cursor.execute(
                """
                SELECT COUNT(DISTINCT request_id)
                FROM relay_logs
                WHERE request_id != '' AND timestamp >= ?
                """,
                (last_24h,),
            )
            requests_24h = cursor.fetchone()[0]

            # Oldest log timestamp
            cursor.execute("SELECT MIN(timestamp) FROM relay_logs")
            oldest_ts = cursor.fetchone()[0]

            return {
                "total_logs": total_logs,
                "logs_24h": logs_24h,
                "requests_24h": requests_24h,
                "level_counts": level_counts,
                "category_counts": category_counts,
                "retention_days": self.retention_days,
                "oldest_timestamp": oldest_ts,
                "db_size_bytes": self.db_path.stat().st_size if self.db_path.is_file() else 0,
            }


__all__ = ["DEFAULT_RETENTION_DAYS", "RelayLogStore"]
