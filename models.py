"""Data models for the bot."""

from dataclasses import dataclass
from datetime import datetime
import sqlite3
from typing import Literal, Optional


@dataclass
class ChannelMessaage:
    id: int
    message_id: int
    channel_id: int

    @classmethod
    def from_db_row(cls, row: sqlite3.Row) -> 'ChannelMessaage':
        """Expects sqlite3.Row with named columns"""
        return cls(
            id=int(row["id"]),
            message_id=int(row["message_id"]),
            channel_id=int(row["channel_id"])
        )

@dataclass
class Player:
    id: int
    player_id: str
    discord_id: str
    player_name: str
    created_at: datetime

    @classmethod
    def from_db_row(cls, row: sqlite3.Row) -> "Player":
        """Expects sqlite3.Row with named columns"""
        return cls(
            id=int(row["id"]),
            player_id=row["player_id"],
            discord_id=row["discord_id"],
            player_name=row["player_name"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )


@dataclass
class Training:
    id: str
    name: str
    description: str
    img: str
    level: Literal["komunita", "rekrut", "valkyria"]
    is_mandatory: bool
    required_roles: list[str]
    assigned_role: str
    created_at: datetime

    @classmethod
    def from_db_row(cls, row: sqlite3.Row) -> "Training":
        """Expects sqlite3.Row with named columns"""
        if row["required_roles"] == "":
            required_roles = []
        else:
            required_roles = [
                r.strip() for r in (row["required_roles"] or "").split(",")
            ]

        return cls(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            img=row["img"],
            level=row["level"],
            is_mandatory=bool(row["is_mandatory"]),
            required_roles=required_roles,
            assigned_role=row["assigned_role"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )


@dataclass
class PlayerTraining:
    id: int
    player_id: int
    training_id: str
    message_id: Optional[int]
    status: Literal["assigned", "interested", "completed", "failed", "withdrawn"]
    notes: str
    completed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_db_row(cls, row: sqlite3.Row) -> "PlayerTraining":
        """Expects sqlite3.Row with named columns"""
        return cls(
            id=int(row["id"]),
            player_id=row["player_id"],
            training_id=row["training_id"],
            message_id=int(row["message_id"]),
            status=row["status"],
            notes=row["notes"],
            completed_at = datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

@dataclass(frozen=True)
class PlayerTrainingDetail:
    id: int
    player_id: int
    training_id: str
    status: Literal["assigned", "interested", "completed", "failed", "withdrawn"]
    channel_message_id: Optional[int]
    message_id: Optional[int]
    channel_id: Optional[int]
    notes: str
    completed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    # Joined fields from trainings table
    training_name: str

    @classmethod
    def from_db_row(cls, row: sqlite3.Row) -> "PlayerTrainingDetail":
        return cls(
            id=int(row["id"]),
            player_id=int(row["player_id"]),
            training_id=row["training_id"],
            channel_message_id=int(row["channel_message_id"]) if row["channel_message_id"] else None,
            message_id=int(row["message_id"]) if row["message_id"] else None,
            channel_id=int(row["channel_id"]) if row["channel_id"] else None,
            status=row["status"],
            notes=row["notes"],
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            training_name=row["training_name"],
        )

@dataclass
class API_Player:
    """Represents a player profile from the game API."""

    player_id: str  # identifier used by the API for this player
    display_name: str
    is_vip: bool
    vips: list
    account_name: Optional[str]
    account_discord_id: Optional[str]
    account_is_member: bool
    account_country: Optional[str]
    account_lang: Optional[str]
    level: int


@dataclass
class PlayerSearchResult:
    """Represents a player search result."""

    player_id: str
    display_name: str  # Most recent name from names array
