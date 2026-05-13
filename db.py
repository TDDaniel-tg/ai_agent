import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from config import config


_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(config.db_path)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn


@contextmanager
def get_db():
    conn = _get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL UNIQUE,
                session_string TEXT NOT NULL,
                api_id INTEGER NOT NULL,
                api_hash TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                channel_link TEXT NOT NULL,
                channel_title TEXT DEFAULT '',
                is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
                UNIQUE(account_id, channel_link)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS vacancies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                channel_title TEXT DEFAULT '',
                message_id INTEGER,
                sender_id INTEGER,
                text TEXT NOT NULL,
                ai_score REAL DEFAULT 0.0,
                ai_summary TEXT DEFAULT '',
                status TEXT DEFAULT 'new',
                budget_info TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now')),
                responded_at TEXT,
                followup_sent INTEGER DEFAULT 0,
                last_followup_at TEXT,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('auto_mode', '0')")
        db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('stack', ?)", (config.default_stack,))
        db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('about_me', ?)", (config.default_about,))
        db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('min_budget', '')")
        db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('followup_days', ?)", (str(config.followup_days),))


def get_setting(key: str) -> Optional[str]:
    with get_db() as db:
        row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None


def set_setting(key: str, value: str):
    with get_db() as db:
        db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def get_accounts() -> list:
    with get_db() as db:
        return [dict(r) for r in db.execute(
            "SELECT * FROM accounts ORDER BY created_at"
        ).fetchall()]


def add_account(phone: str, session_string: str, api_id: int, api_hash: str) -> int:
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO accounts (phone, session_string, api_id, api_hash) VALUES (?, ?, ?, ?)",
            (phone, session_string, api_id, api_hash),
        )
        return cur.lastrowid


def delete_account(account_id: int):
    with get_db() as db:
        db.execute("DELETE FROM accounts WHERE id = ?", (account_id,))


def get_channels(account_id: int) -> list:
    with get_db() as db:
        return [dict(r) for r in db.execute(
            "SELECT * FROM channels WHERE account_id = ? AND is_active = 1 ORDER BY created_at",
            (account_id,),
        ).fetchall()]


def add_channel(account_id: int, channel_link: str, channel_title: str = ""):
    with get_db() as db:
        db.execute(
            "INSERT OR IGNORE INTO channels (account_id, channel_link, channel_title) VALUES (?, ?, ?)",
            (account_id, channel_link, channel_title),
        )


def remove_channel(channel_id: int):
    with get_db() as db:
        db.execute("UPDATE channels SET is_active = 0 WHERE id = ?", (channel_id,))


def save_vacancy(account_id: int, channel_title: str, message_id: int,
                 sender_id: Optional[int], text: str, score: float = 0.0,
                 summary: str = "", budget_info: str = "") -> Optional[int]:
    with get_db() as db:
        existing = db.execute(
            "SELECT id FROM vacancies WHERE account_id = ? AND message_id = ?",
            (account_id, message_id),
        ).fetchone()
        if existing:
            return existing["id"]
        cur = db.execute(
            "INSERT INTO vacancies (account_id, channel_title, message_id, sender_id, text, ai_score, ai_summary, budget_info) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (account_id, channel_title, message_id, sender_id, text, score, summary, budget_info),
        )
        return cur.lastrowid


def update_vacancy_status(vacancy_id: int, status: str):
    with get_db() as db:
        db.execute(
            "UPDATE vacancies SET status = ?, responded_at = datetime('now') WHERE id = ?",
            (status, vacancy_id),
        )


def get_vacancies_by_status(status: Optional[str] = None) -> list:
    with get_db() as db:
        if status:
            rows = db.execute(
                "SELECT * FROM vacancies WHERE status = ? ORDER BY created_at DESC", (status,)
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM vacancies ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]


def get_vacancy(vacancy_id: int) -> Optional[dict]:
    with get_db() as db:
        row = db.execute("SELECT * FROM vacancies WHERE id = ?", (vacancy_id,)).fetchone()
        return dict(row) if row else None


def mark_followup_sent(vacancy_id: int):
    with get_db() as db:
        db.execute(
            "UPDATE vacancies SET followup_sent = followup_sent + 1, last_followup_at = datetime('now') WHERE id = ?",
            (vacancy_id,),
        )


def get_vacancies_for_followup(days: int) -> list:
    with get_db() as db:
        rows = db.execute("""
            SELECT * FROM vacancies
            WHERE status IN ('responded', 'sent')
            AND datetime(responded_at) <= datetime('now', ? || ' days')
            AND (last_followup_at IS NULL OR datetime(last_followup_at) <= datetime('now', ? || ' days'))
        """, (f"-{days}", f"-{days}")).fetchall()
        return [dict(r) for r in rows]
