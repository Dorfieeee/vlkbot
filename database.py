"""Database operations for managing VIP claims."""
import sqlite3
from datetime import UTC, datetime
from typing import Optional

from config import DB_PATH


def init_db() -> None:
    """Initialize the SQLite database and ensure tables exist."""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS server_status (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS claims (
                discord_id TEXT PRIMARY KEY,
                player_id TEXT,
                claimed_at TEXT NOT NULL
            )
            """
        )
        # Make sure newer column exists if DB was created with an older schema
        cur = conn.execute("PRAGMA table_info(claims)")
        cols = [row[1] for row in cur.fetchall()]
        if "player_id" not in cols:
            conn.execute("ALTER TABLE claims ADD COLUMN player_id TEXT")
        
        # Create threads table for tracking all threads created by the bot
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS threads (
                thread_id TEXT PRIMARY KEY,
                creator_id TEXT NOT NULL,
                is_open INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def has_claimed(discord_id: int) -> bool:
    """Check if a Discord user has already claimed VIP."""
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute("SELECT 1 FROM claims WHERE discord_id = ?", (str(discord_id),))
        row = cur.fetchone()
        return row is not None
    finally:
        conn.close()


def is_player_claimed(player_id: str, discord_id: int) -> bool:
    """
    Returns True if this player_id has already been used to claim VIP
    from a *different* Discord account.
    """
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute(
            "SELECT discord_id FROM claims WHERE player_id = ?",
            (str(player_id),),
        )
        row = cur.fetchone()
        if row is None:
            return False
        existing_discord_id = row[0]
        return existing_discord_id is not None and existing_discord_id != str(discord_id)
    finally:
        conn.close()


def record_claim(discord_id: int, player_id: str) -> None:
    """Record a successful VIP claim."""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO claims (discord_id, player_id, claimed_at) VALUES (?, ?, ?)",
            (str(discord_id), str(player_id), datetime.now(UTC).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()

def get_server_channel_id() -> Optional[int]:
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute("SELECT value FROM server_status WHERE key = 'channel_id'")
        row = cur.fetchone()
        return int(row[0]) if row else None
    finally:
        conn.close()

def set_server_channel_id(channel_id: int | None) -> None:
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO server_status (key, value) VALUES ('channel_id', ?)",
            (str(channel_id),),
        )
        conn.commit()
    finally:
        conn.close()


# --- Thread management functions --------------------------------------------


def create_thread_record(thread_id: int, creator_id: int) -> None:
    """Record a new thread created by the bot."""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            """
            INSERT INTO threads (thread_id, creator_id, is_open, created_at)
            VALUES (?, ?, 1, ?)
            """,
            (str(thread_id), str(creator_id), datetime.now(UTC).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def get_thread_creator(thread_id: int) -> Optional[int]:
    """Get the creator ID for a thread."""
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute(
            "SELECT creator_id FROM threads WHERE thread_id = ?",
            (str(thread_id),),
        )
        row = cur.fetchone()
        if row:
            return int(row[0])
        return None
    finally:
        conn.close()


def is_thread_open(thread_id: int) -> bool:
    """Check if a thread is currently open."""
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute(
            "SELECT is_open FROM threads WHERE thread_id = ?",
            (str(thread_id),),
        )
        row = cur.fetchone()
        if row:
            return bool(row[0])
        return False
    finally:
        conn.close()


def close_thread(thread_id: int) -> None:
    """Mark a thread as closed."""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "UPDATE threads SET is_open = 0 WHERE thread_id = ?",
            (str(thread_id),),
        )
        conn.commit()
    finally:
        conn.close()
