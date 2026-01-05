"""Data models for the bot."""
from dataclasses import dataclass
from typing import Optional


@dataclass
class Player:
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


@dataclass
class PlayerSearchResult:
    """Represents a player search result."""
    player_id: str
    display_name: str  # Most recent name from names array

