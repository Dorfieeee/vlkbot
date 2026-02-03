"""API client for communicating with the game server API."""
from datetime import datetime
from typing import Optional

import httpx

from config import API_BASE_URL, API_BEARER_TOKEN, SERVER_NUMBERS, SERVER_URLS
from models import API_Player, PlayerSearchResult


class ApiClient:
    """Client for interacting with the remote game server API."""

    def __init__(self, base_url: str, bearer_token: str) -> None:
        self.base_url = base_url.rstrip("/")
        # Map server numbers to their specific base URLs (fallback to default)
        self._server_base_urls = {
            number: url.rstrip("/")
            for number, url in zip(SERVER_NUMBERS, SERVER_URLS)
            if url
        }
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {bearer_token}", "Accept": "application/json"},
            timeout=10.0,
        )

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    async def fetch_player_by_game_id(self, game_id: str) -> Optional[API_Player]:
        """
        Fetch a player profile by their game ID.
        GET BASE_URL + get_player_profile?player_id=<ID>
        """
        resp = await self._client.get("/get_player_profile", params={"player_id": game_id})
        resp.raise_for_status()
        data = resp.json()
        result = data.get("result")
        if not result:
            return None

        account = result.get("account") or {}
        names = result.get("names") or []
        soldier = result.get("soldier") or {}

        # Prefer soldier name, then account name, then first historical name, then player_id
        display_name = (
            soldier.get("name")
            or account.get("name")
            or (names[0].get("name") if names else None)
            or str(result.get("player_id"))
        )

        return API_Player(
            player_id=str(result.get("player_id")),
            display_name=display_name,
            is_vip=bool(result.get("is_vip", False)),
            vips=result.get("vips") or [],
            account_name=account.get("name"),
            account_discord_id=account.get("discord_id"),
            account_is_member=bool(account.get("is_member", False)),
            account_country=account.get("country"),
            account_lang=account.get("lang") or "en",
        )

    async def edit_player_account(self, player: API_Player, discord_id: int) -> None:
        """
        Update a player's account information, particularly their Discord ID.
        POST BASE_URL + edit_player_account
        """
        payload = {
            "player_id": player.player_id,
            "name": player.account_name,
            "discord_id": str(discord_id),
            "is_member": player.account_is_member,
            "country": player.account_country,
            "lang": player.account_lang or "en",
        }
        resp = await self._client.post("/edit_player_account", json=payload)
        resp.raise_for_status()

    async def add_vip(self, player: API_Player, expiration: datetime, server_number: int = 1) -> None:
        """
        Add or extend VIP status for a player.
        POST BASE_URL + add_vip
        """
        expiration_str = expiration.replace(tzinfo=None).isoformat() + "Z"
        payload = {
            "player_name": player.display_name,
            "player_id": player.player_id,
            "expiration": expiration_str,
            "description": f"{player.display_name}",
        }
        # If a server-specific base URL is configured, use it for this call only.
        target_base = self._server_base_urls.get(server_number, self.base_url)
        url = f"{target_base}/add_vip"

        resp = await self._client.post(url, json=payload)
        resp.raise_for_status()

    async def search_players(self, **params) -> list[PlayerSearchResult]:
        """
        Search for players by name.
        POST BASE_URL + get_players_history
        Returns up to 25 results.
        """
        payload = {
            "page": 1,
            "page_size": 25,
            "flags": [],
            "blacklisted": False,
            "exact_name_match": False,
            "ignore_accent": False,
            "is_watched": False,
            **params,
        }
        resp = await self._client.post("/get_players_history", json=payload)
        resp.raise_for_status()
        data = resp.json()
        result = data.get("result", {})
        players = result.get("players", [])

        search_results = []
        for player_data in players:
            # Get the most recent name (first in names array)
            names = player_data.get("names", [])
            display_name = names[0].get("name") if names else str(player_data.get("player_id", ""))
            
            search_results.append(
                PlayerSearchResult(
                    player_id=str(player_data.get("player_id", "")),
                    display_name=display_name,
                )
            )

        return search_results

async def get_public_info(base_url) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(base_url + "/api/get_public_info")
        resp.raise_for_status()
        return resp.json()["result"]

# Initialize API client
api_client = ApiClient(API_BASE_URL, API_BEARER_TOKEN)

def get_api_client():
    return api_client