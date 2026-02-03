"""Database operations for managing VIP claims."""

import aiosqlite
from datetime import UTC, datetime
from typing import List, Literal, Optional

from config import DB_PATH
from models import Player, PlayerTraining, PlayerTrainingDetail, Training


async def init_db() -> None:
    """Initialize the SQLite database and ensure tables exist."""
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS players (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id TEXT UNIQUE NOT NULL,
                player_name TEXT NOT NULL,
                discord_id TEXT UNIQUE NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id INTEGER UNIQUE NOT NULL
                    REFERENCES players(id)
                    ON DELETE CASCADE,
                active BOOLEAN DEFAULT TRUE,
                joined_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tracked_servers (
                server_name TEXT PRIMARY KEY,
                server_url TEXT UNIQUE,
                channel_id TEXT UNIQUE
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS counter_channels (
                channel_id TEXT PRIMARY KEY,
                channel_name TEXT,
                role_id TEXT
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS claims (
                discord_id TEXT PRIMARY KEY,
                player_id TEXT,
                claimed_at TEXT NOT NULL
            )
            """
        )

        # Create threads table for tracking all threads created by the bot
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS threads (
                thread_id TEXT PRIMARY KEY,
                creator_id TEXT NOT NULL,
                is_open INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            )
            """
        )

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trainings (
            id TEXT PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,              
            description TEXT,   
            img TEXT,                    
            level TEXT NOT NULL DEFAULT 'komunita'   
                CHECK(level IN ('komunita', 'rekrut', 'valkyria')),
            is_mandatory BOOLEAN DEFAULT FALSE,     -- For recruits: true if required for full membership
            required_roles TEXT,                    -- Comma separated Discord IDs for required roles
            assigned_role TEXT,                     -- The role assigned to Discord user on signup
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS player_trainings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
            training_id INTEGER NOT NULL REFERENCES trainings(id) ON DELETE RESTRICT,  -- Prevents deleting a training if players are linked
            message_id INTEGER REFERENCES channel_messages(id) ON DELETE SET NULL,
            status TEXT NOT NULL DEFAULT 'assigned'
                CHECK(status IN ('assigned', 'interested', 'completed', 'failed', 'withdrawn')),
            completed_at DATETIME,                  -- When marked complete
            notes TEXT,                             -- e.g., 'Completed via self-study', 'Failed due to no-show', instructor feedback
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(player_id, training_id)          -- One record per player-training pair; prevents duplicate interests
            )
            """
        )

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS channel_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT NOT NULL,
            message_id TEXT NOT NULL,
            UNIQUE(channel_id, message_id)
            )
            """
        )

        await conn.commit()


async def get_player(id: Optional[int] = None, player_id: Optional[int] = None, discord_id: Optional[int] = None) -> Optional[Player]:
    if id is None and player_id is None and discord_id is None:
        return None

    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row

        query = "SELECT id, player_id, player_name, discord_id, created_at FROM players WHERE 1=1"
        params: List[int] = []

        if id is not None:
            query += " AND id = ?"
            params.append(id)

        if player_id is not None:
            query += " AND player_id = ?"
            params.append(player_id)

        if discord_id is not None:
            query += " AND discord_id = ?"
            params.append(discord_id)

        async with conn.execute(query, params) as cur:
            row = await cur.fetchone()
            return Player.from_db_row(row) if row else None


async def get_players(player_name: Optional[str] = None) -> list[Player]:
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row

        query = "SELECT id, player_id, player_name, discord_id, created_at FROM players WHERE 1=1"

        params: List = []

        if player_name is not None and player_name != "":
            query += " AND player_name LIKE ?"
            params.append(f'%{player_name}%')

        query += " ORDER BY player_name ASC LIMIT ?"
        params.append(25)

        async with conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [Player.from_db_row(row) for row in rows]


async def edit_or_create_player(
    player_id: str,
    player_name: str,
    discord_id: Optional[int] = None,
) -> int:
    """
    Insert a player if missing, otherwise update their data.

    Returns the row ID of the affected player record.
    """
    async with aiosqlite.connect(DB_PATH) as conn:
        cur = await conn.execute(
            "SELECT id, discord_id FROM players WHERE player_id = ?",
            (str(player_id),),
        )
        row = await cur.fetchone()

        if row:
            player_row_id, existing_discord = row
            await conn.execute(
                "UPDATE players SET player_name = ?, discord_id = ? WHERE player_id = ?",
                (
                    player_name,
                    str(discord_id) if discord_id is not None else existing_discord,
                    str(player_id),
                ),
            )
            await conn.commit()
            return int(player_row_id)

        cur = await conn.execute(
            "INSERT INTO players (player_id, player_name, discord_id) VALUES (?, ?, ?)",
            (
                str(player_id),
                player_name,
                str(discord_id) if discord_id is not None else None,
            ),
        )
        await conn.commit()
        return int(cur.lastrowid)


async def has_claimed(discord_id: int) -> bool:
    """Check if a Discord user has already claimed VIP."""
    async with aiosqlite.connect(DB_PATH) as conn:
        cur = await conn.execute(
            "SELECT 1 FROM claims WHERE discord_id = ?", (str(discord_id),)
        )
        row = await cur.fetchone()
        return row is not None


async def is_player_claimed(player_id: str, discord_id: int) -> bool:
    """
    Returns True if this player_id has already been used to claim VIP
    from a *different* Discord account.
    """
    async with aiosqlite.connect(DB_PATH) as conn:
        cur = await conn.execute(
            "SELECT discord_id FROM claims WHERE player_id = ?",
            (str(player_id),),
        )
        row = await cur.fetchone()
        if row is None:
            return False
        existing_discord_id = row[0]
        return existing_discord_id is not None and existing_discord_id != str(
            discord_id
        )


async def record_claim(discord_id: int, player_id: str) -> None:
    """Record a successful VIP claim."""
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "INSERT OR REPLACE INTO claims (discord_id, player_id, claimed_at) VALUES (?, ?, ?)",
            (str(discord_id), str(player_id), datetime.now(UTC).isoformat()),
        )
        await conn.commit()


async def get_tracked_servers():
    async with aiosqlite.connect(DB_PATH) as conn:
        cur = await conn.execute("SELECT * FROM tracked_servers")
        rows = await cur.fetchall()
        return rows


async def set_tracked_server(server_name: str, server_url: str, channel_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "INSERT OR REPLACE INTO tracked_servers (server_name, server_url, channel_id) VALUES (?, ?, ?)",
            (server_name, server_url, channel_id),
        )
        await conn.commit()


async def del_tracked_server(channel_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("PRAGMA foreign_keys = ON;")
        await conn.execute(
            "DELETE FROM tracked_servers WHERE channel_id = ?",
            (channel_id,),
        )
        await conn.commit()


async def get_counter_channels() -> list[list[str]]:
    async with aiosqlite.connect(DB_PATH) as conn:
        cur = await conn.execute("SELECT * FROM counter_channels")
        rows = await cur.fetchall()
        return rows


async def set_counter_channel(channel_id: str, channel_name: str, role_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "INSERT OR REPLACE INTO counter_channels (channel_id, channel_name, role_id) VALUES (?, ?, ?)",
            (channel_id, channel_name, role_id),
        )
        await conn.commit()


async def del_counter_channel(channel_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("PRAGMA foreign_keys = ON;")
        await conn.execute(
            "DELETE FROM counter_channels WHERE channel_id = ?",
            (channel_id,),
        )
        await conn.commit()


# --- Thread management functions --------------------------------------------


async def create_thread_record(thread_id: int, creator_id: int) -> None:
    """Record a new thread created by the bot."""
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            """
            INSERT INTO threads (thread_id, creator_id, is_open, created_at)
            VALUES (?, ?, 1, ?)
            """,
            (str(thread_id), str(creator_id), datetime.now(UTC).isoformat()),
        )
        await conn.commit()


async def get_thread_creator(thread_id: int) -> Optional[int]:
    """Get the creator ID for a thread."""
    async with aiosqlite.connect(DB_PATH) as conn:
        cur = await conn.execute(
            "SELECT creator_id FROM threads WHERE thread_id = ?",
            (str(thread_id),),
        )
        row = await cur.fetchone()
        if row:
            return int(row[0])
        return None


async def is_thread_open(thread_id: int) -> bool:
    """Check if a thread is currently open."""
    async with aiosqlite.connect(DB_PATH) as conn:
        cur = await conn.execute(
            "SELECT is_open FROM threads WHERE thread_id = ?",
            (str(thread_id),),
        )
        row = await cur.fetchone()
        if row:
            return bool(row[0])
        return False


async def close_thread(thread_id: int) -> None:
    """Mark a thread as closed."""
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "UPDATE threads SET is_open = 0 WHERE thread_id = ?",
            (str(thread_id),),
        )
        await conn.commit()


# --- Trainings functions --------------------------------------------




async def get_training(id: str) -> Optional[Training]:
    """Get a training by id"""
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute("SELECT * FROM trainings WHERE id = ?", (id,))
        row = await cur.fetchone()
        return Training.from_db_row(row) if row else None


async def get_trainings() -> list[Training]:
    """Get all trainings"""
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute("SELECT * FROM trainings")
        rows = await cur.fetchall()
        return [Training.from_db_row(row) for row in rows]


async def create_training(
    id: str,
    name: str,
    description: str,
    img: str,
    level: str,
    assigned_role: str,
    is_mandatory: bool = False,
    required_roles: list[str] = [],
):
    "Creates a training record"
    async with aiosqlite.connect(DB_PATH) as conn:
        try:
            await conn.execute(
                """
            INSERT INTO trainings (id, name, description, img, level, assigned_role, is_mandatory, required_roles)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    id,
                    name,
                    description,
                    img,
                    level,
                    assigned_role,
                    is_mandatory,
                    ",".join(required_roles),
                ),
            )
            await conn.commit()
        except aiosqlite.IntegrityError:
            # e.g. UNIQUE constraint failed if you have (name) unique
            # CHECK(level IN ('komunita', 'rekrut', 'valkyria'))
            await conn.rollback()
            return None


# --- PlayerTraining functions --------------------------------------------


async def get_player_training(pt_id: int) -> Optional[PlayerTrainingDetail]:
    """
    Retrieve a single PlayerTrainingDetail record by its ID.
    Returns None if not found.
    """
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(
            """
            SELECT 
                pt.id AS id, 
                pt.player_id AS player_id,
                pt.training_id AS training_id,
                pt.status AS status,
                pt.notes AS notes,
                pt.completed_at AS completed_at,
                pt.created_at AS created_at,
                pt.updated_at AS updated_at,
                t.name           AS training_name,
                m.id    AS channel_message_id,
                m.message_id    AS message_id,
                m.channel_id    AS channel_id
            FROM player_trainings pt
            LEFT JOIN channel_messages m ON pt.message_id = m.id
            INNER JOIN trainings t ON pt.training_id = t.id
            WHERE pt.id = ?
            """,
            (pt_id,),
        )
        row = await cur.fetchone()
        return PlayerTrainingDetail.from_db_row(row) if row else None


async def get_player_trainings(
    player_id: Optional[int] = None,
    training_id: Optional[str] = None,
    status: Optional[Literal["assigned", "interested", "completed", "failed", "withdrawn"]] = None,
    limit: int = 25,
    offset: int = 0,
) -> List[PlayerTrainingDetail]:
    """
    Retrieve PlayerTraining records with joined training details.
    Returns list of PlayerTrainingDetail (includes training_name, etc.)
    """
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row

        query = """
            SELECT 
                pt.id AS id, 
                pt.player_id AS player_id,
                pt.training_id AS training_id,
                pt.status AS status,
                pt.notes AS notes,
                pt.completed_at AS completed_at,
                pt.created_at AS created_at,
                pt.updated_at AS updated_at,
                t.name           AS training_name,
                m.id    AS channel_message_id,
                m.message_id    AS message_id,
                m.channel_id    AS channel_id
            FROM player_trainings pt
            LEFT JOIN channel_messages m ON pt.message_id = m.id
            INNER JOIN trainings t ON pt.training_id = t.id
            WHERE 1=1
        """
        params: List = []

        if player_id is not None:
            query += " AND pt.player_id = ?"
            params.append(player_id)

        if training_id is not None:
            query += " AND pt.training_id = ?"
            params.append(training_id)

        if status is not None:
            query += " AND pt.status = ?"
            params.append(status)

        query += " ORDER BY pt.created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        async with conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [PlayerTrainingDetail.from_db_row(row) for row in rows]


async def create_player_training(
    player_id: int,
    training_id: str,
    message_id: Optional[int],
    status: Literal["assigned", "interested", "completed", "failed", "withdrawn"] = "assigned",
    notes: str = "",
    completed_at: Optional[datetime] = None,
) -> Optional[int]:
    """
    Create a new PlayerTraining record.
    Returns the new row ID or None if creation failed.
    """
    async with aiosqlite.connect(DB_PATH) as conn:
        try:
            now = datetime.now(tz=UTC).isoformat()

            cur = await conn.execute(
                """
                INSERT INTO player_trainings (
                    player_id, training_id, message_id, status, notes,
                    completed_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    player_id,
                    training_id,
                    message_id,
                    status,
                    notes,
                    completed_at.isoformat() if completed_at else None,
                    now,
                    now,
                ),
            )
            await conn.commit()
            return cur.lastrowid

        except aiosqlite.IntegrityError:
            # e.g. UNIQUE constraint failed if you have (player_id, training_id) unique
            # CHECK(status IN ('assigned', 'interested', 'completed', 'failed', 'withdrawn'))
            await conn.rollback()
            return None


async def update_player_training(
    pt_id: int,
    message_id: Optional[int] = None,
    status: Optional[Literal["assigned", "interested", "completed", "failed", "withdrawn"]] = None,
    notes: Optional[str] = None,
    completed_at: Optional[datetime] = None,
) -> bool:
    """
    Update selected fields of an existing PlayerTraining.
    Only provided fields are updated.
    Returns True if updated, False if not found or no changes.
    """
    if not any([status is not None, notes is not None, completed_at is not None, message_id is not None]):
        return False  # nothing to update

    async with aiosqlite.connect(DB_PATH) as conn:
        try:
            updates = []
            params = []

            now = datetime.now(tz=UTC).isoformat()

            if message_id is not None:
                updates.append("message_id = ?")
                params.append(message_id)

            if status is not None:
                updates.append("status = ?")
                params.append(status)

            if notes is not None:
                updates.append("notes = ?")
                params.append(notes)

            if completed_at is not None:
                updates.append("completed_at = ?")
                params.append(completed_at.isoformat() if completed_at else None)

            # always update timestamp
            updates.append("updated_at = ?")
            params.append(now)


            params.append(pt_id)
            query = f"UPDATE player_trainings SET {', '.join(updates)} WHERE id = ?"
            cur = await conn.execute(query, params)

            updated = cur.rowcount > 0
            await conn.commit()
            return updated

        except aiosqlite.Error:
            await conn.rollback()
            return False


async def delete_player_training(pt_id: int) -> bool:
    """
    Delete a PlayerTraining record.
    Returns True if deleted, False if not found.
    """
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("PRAGMA foreign_keys = ON;")
        try:
            # Get the message_id first
            cur = await conn.execute(
                "SELECT message_id FROM player_trainings WHERE id = ?", (pt_id,)
            )
            row = await cur.fetchone()
            if row:
                message_id = row[0]
                await conn.execute("DELETE FROM channel_messages WHERE id = ?", (message_id,))
            
            cur = await conn.execute("DELETE FROM player_trainings WHERE id = ?", (pt_id,))
            deleted = cur.rowcount > 0
            await conn.commit()
            return deleted
        except:
            await conn.rollback()
            return False

async def create_channel_message(channel_id: int, message_id: int) -> Optional[int]:
    """
    Create a new channel_messages record.
    Returns the new row ID or None if creation failed (e.g., duplicate entry).
    """
    if not channel_id or not message_id:
        return None  # Optional: Early validation for empty inputs

    async with aiosqlite.connect(DB_PATH) as conn:
        try:
            cur = await conn.execute(
                """
                INSERT INTO channel_messages (channel_id, message_id)
                VALUES (?, ?)
                """,
                (channel_id, message_id),
            )
            await conn.commit()
            return cur.lastrowid  # Returns the auto-incremented ID
        except aiosqlite.IntegrityError:
            # Handles UNIQUE violation or NOT NULL
            await conn.rollback()
            return None
        except aiosqlite.Error:
            # General error fallback
            await conn.rollback()
            return None

async def delete_channel_message(id: int) -> bool:
    """
    Create a new channel_messages record.
    Returns the new row ID or None if creation failed (e.g., duplicate entry).
    """
    if not id:
        return False  # Optional: Early validation for empty inputs

    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("PRAGMA foreign_keys = ON;")
        try:
            cur = await conn.execute("DELETE FROM channel_messages WHERE id = ?", (id,))
            deleted = cur.rowcount > 0
            await conn.commit()
            return deleted
        except aiosqlite.Error:
            # General error fallback
            await conn.rollback()
            return False