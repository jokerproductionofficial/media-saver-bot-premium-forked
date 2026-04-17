"""database/db.py — SQLite database layer for users, downloads, cache, and bans."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import DB_PATH, CACHE_EXPIRY_HOURS

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════════
#  Connection helper
# ═════════════════════════════════════════════════════════════════════════════

@contextmanager
def get_conn():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ═════════════════════════════════════════════════════════════════════════════
#  Schema
# ═════════════════════════════════════════════════════════════════════════════

def init_db() -> None:
    """Create all tables if they don't exist."""
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id     INTEGER PRIMARY KEY,
                username    TEXT,
                full_name   TEXT,
                joined_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_banned   BOOLEAN DEFAULT 0,
                total_downloads INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS daily_usage (
                user_id     INTEGER,
                date        TEXT,
                count       INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, date)
            );

            CREATE TABLE IF NOT EXISTS rate_limit (
                user_id     INTEGER PRIMARY KEY,
                last_request TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS download_cache (
                cache_key   TEXT PRIMARY KEY,
                file_id     TEXT,
                file_type   TEXT,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS download_logs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER,
                video_url   TEXT,
                quality     TEXT,
                file_type   TEXT,
                status      TEXT,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS broadcast_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                message     TEXT,
                sent_count  INTEGER,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
    logger.info("Database initialized")


# ═════════════════════════════════════════════════════════════════════════════
#  User operations
# ═════════════════════════════════════════════════════════════════════════════

def upsert_user(user_id: int, username: str, full_name: str) -> None:
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO users (user_id, username, full_name)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username    = excluded.username,
                full_name   = excluded.full_name,
                last_active = CURRENT_TIMESTAMP
        """, (user_id, username or "", full_name or ""))


def get_user(user_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return dict(row) if row else None


def is_banned(user_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT is_banned FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return bool(row["is_banned"]) if row else False


def ban_user(user_id: int) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (user_id,))


def unban_user(user_id: int) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE users SET is_banned = 0 WHERE user_id = ?", (user_id,))


def get_all_users() -> List[int]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT user_id FROM users WHERE is_banned = 0"
        ).fetchall()
        return [r["user_id"] for r in rows]


def get_total_users() -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()
        return row["c"]


def increment_total_downloads(user_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET total_downloads = total_downloads + 1 WHERE user_id = ?",
            (user_id,)
        )


# ═════════════════════════════════════════════════════════════════════════════
#  Daily usage / Rate limit
# ═════════════════════════════════════════════════════════════════════════════

def get_daily_usage(user_id: int) -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    with get_conn() as conn:
        row = conn.execute(
            "SELECT count FROM daily_usage WHERE user_id = ? AND date = ?",
            (user_id, today)
        ).fetchone()
        return row["count"] if row else 0


def increment_daily_usage(user_id: int) -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO daily_usage (user_id, date, count)
            VALUES (?, ?, 1)
            ON CONFLICT(user_id, date) DO UPDATE SET count = count + 1
        """, (user_id, today))


def check_rate_limit(user_id: int, seconds: int) -> bool:
    """Return True if user is within rate limit (should be blocked)."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT last_request FROM rate_limit WHERE user_id = ?", (user_id,)
        ).fetchone()
        if not row:
            return False
        last = datetime.fromisoformat(row["last_request"])
        return (datetime.now() - last).total_seconds() < seconds


def update_rate_limit(user_id: int) -> None:
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO rate_limit (user_id, last_request)
            VALUES (?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET last_request = CURRENT_TIMESTAMP
        """, (user_id,))


# ═════════════════════════════════════════════════════════════════════════════
#  Cache
# ═════════════════════════════════════════════════════════════════════════════

def get_cache(cache_key: str) -> Optional[Dict[str, str]]:
    expiry = datetime.now() - timedelta(hours=CACHE_EXPIRY_HOURS)
    with get_conn() as conn:
        row = conn.execute("""
            SELECT file_id, file_type FROM download_cache
            WHERE cache_key = ? AND created_at > ?
        """, (cache_key, expiry.isoformat())).fetchone()
        return dict(row) if row else None


def set_cache(cache_key: str, file_id: str, file_type: str) -> None:
    with get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO download_cache (cache_key, file_id, file_type)
            VALUES (?, ?, ?)
        """, (cache_key, file_id, file_type))


# ═════════════════════════════════════════════════════════════════════════════
#  Download logs
# ═════════════════════════════════════════════════════════════════════════════

def log_download(user_id: int, url: str, quality: str, file_type: str, status: str) -> None:
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO download_logs (user_id, video_url, quality, file_type, status)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, url, quality, file_type, status))


def get_stats() -> Dict[str, Any]:
    with get_conn() as conn:
        total_users = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
        total_downloads = conn.execute("SELECT COUNT(*) as c FROM download_logs WHERE status='success'").fetchone()["c"]
        today = datetime.now().strftime("%Y-%m-%d")
        today_downloads = conn.execute(
            "SELECT COUNT(*) as c FROM download_logs WHERE status='success' AND date(created_at) = ?",
            (today,)
        ).fetchone()["c"]
        return {
            "total_users": total_users,
            "total_downloads": total_downloads,
            "today_downloads": today_downloads,
        }


# ═══════════════════════════════════════════════════════════════════
#  Recent logs (for admin panel)
# ═══════════════════════════════════════════════════════════════════

def get_recent_logs(limit: int = 10):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT user_id, file_type, quality, status, created_at "
            "FROM download_logs ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def log_broadcast(message: str, sent_count: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO broadcast_log (message, sent_count) VALUES (?, ?)",
            (message, sent_count)
        )
