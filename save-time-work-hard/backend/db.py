import hashlib
import hmac
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(os.environ.get("STWH_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
DB_PATH = DATA_DIR / "app.db"
# Default resumes uploaded from the browser; generated resumes are saved next to them.
UPLOAD_DIR = DATA_DIR / "resumes"

ADMIN_USERNAME = "icaroosu"
ADMIN_PASSWORD = "welcome!@#123"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    username         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    email            TEXT UNIQUE COLLATE NOCASE,
    display_name     TEXT NOT NULL DEFAULT '',
    password_hash    TEXT NOT NULL,
    role             TEXT NOT NULL DEFAULT 'user',
    disabled         INTEGER NOT NULL DEFAULT 0,
    active_resume_id INTEGER,
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS default_resumes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    label      TEXT NOT NULL,
    path       TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bids (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    default_resume_id INTEGER REFERENCES default_resumes(id) ON DELETE SET NULL,
    default_resume_label TEXT NOT NULL DEFAULT '',
    default_resume_path  TEXT NOT NULL DEFAULT '',
    bid_date          TEXT NOT NULL,
    bid_time          TEXT NOT NULL,
    job_title         TEXT NOT NULL DEFAULT '',
    company_name      TEXT NOT NULL DEFAULT '',
    jobsite_name      TEXT NOT NULL DEFAULT '',
    job_url           TEXT NOT NULL DEFAULT '',
    jd_text           TEXT NOT NULL DEFAULT '',
    resume_html       TEXT NOT NULL DEFAULT '',
    resume_text       TEXT NOT NULL DEFAULT '',
    filename          TEXT NOT NULL,
    file_path         TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bids_user_date ON bids(user_id, bid_date);
"""


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000)
    return f"{salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000)
    return hmac.compare_digest(candidate.hex(), digest)


def connect() -> sqlite3.Connection:
    # Several people use the server at once: wait for locks instead of failing.
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


@contextmanager
def get_conn():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        admin = conn.execute("SELECT id FROM users WHERE username = ?", (ADMIN_USERNAME,)).fetchone()
        if admin is None:
            conn.execute(
                "INSERT INTO users (username, email, display_name, password_hash, role, created_at)"
                " VALUES (?, NULL, ?, ?, 'admin', ?)",
                (ADMIN_USERNAME, ADMIN_USERNAME, hash_password(ADMIN_PASSWORD), now_iso()),
            )
