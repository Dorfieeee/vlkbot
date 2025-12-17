import asyncio
import os
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Optional

import discord
import httpx
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv


# --- Configuration & environment ------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "claims.sqlite3"

load_dotenv()  # Load variables from .env if present

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
API_BASE_URL = os.getenv("API_BASE_URL")  # e.g. https://api.example.com
BASE_URL = os.getenv("BASE_URL")  # e.g. https://api.example.com
API_BEARER_TOKEN = os.getenv("API_BEARER_TOKEN")

INFINITE_VIP_DATE = "3000-01-01T00:00:00+00:00"
SERVER_NUMBER = 1
PREFIX = "VANOCE "
GUILD_ID = int(os.getenv("GUILD_ID", "0")) or None
HLL_ROLE_ID = int(os.getenv("HLL_ROLE_ID", "0")) or None
VIP_LOG_CHANNEL_ID = int(os.getenv("VIP_LOG_CHANNEL_ID", "0")) or None

# Optional: restrict where the view is used
VIP_CHANNEL_ID = int(os.getenv("VIP_CHANNEL_ID", "0")) or None


if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN is not set. Add it to your environment or .env file.")

if not API_BASE_URL or not API_BEARER_TOKEN:
    raise RuntimeError(
        "API_BASE_URL and API_BEARER_TOKEN must be set to talk to your remote API. "
        "Add them to your environment or .env file."
    )


# --- SQLite helpers -------------------------------------------------------------

def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    try:
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
        conn.commit()
    finally:
        conn.close()


def has_claimed(discord_id: int) -> bool:
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
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO claims (discord_id, player_id, claimed_at) VALUES (?, ?, ?)",
            (str(discord_id), str(player_id), datetime.now(UTC).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


# --- Logging helpers ------------------------------------------------------------


async def send_log_message(
    client: discord.Client,
    content: str,
    suppress_embeds: bool = False,
) -> None:
    """
    Send a message to the configured log channel, if any.
    Fail-closed: logging problems must never affect user flow.
    """
    if VIP_LOG_CHANNEL_ID is None:
        return

    try:
        channel = client.get_channel(VIP_LOG_CHANNEL_ID)
        if isinstance(channel, discord.TextChannel):
            await channel.send(content, suppress_embeds=suppress_embeds)
    except Exception:
        # Never crash on logging errors
        pass


# --- Remote API client ----------------------------------------------------------

@dataclass
class Player:
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
    player_id: str
    display_name: str  # Most recent name from names array


class ApiClient:
    def __init__(self, base_url: str, bearer_token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {bearer_token}", "Accept": "application/json"},
            timeout=10.0,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def fetch_player_by_game_id(self, game_id: str) -> Optional[Player]:
        """
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

        return Player(
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

    async def edit_player_account(self, player: Player, discord_id: int) -> None:
        """
        POST BASE_URL + edit_player_account
        payload taken from api_examples/edit_player_account.json (14-21),
        enriched with discord_id.
        """
        payload = {
            "player_id": player.player_id,
            "name": player.account_name or player.display_name,
            "discord_id": str(discord_id),
            "is_member": player.account_is_member,
            "country": player.account_country,
            "lang": player.account_lang or "en",
        }
        resp = await self._client.post("/edit_player_account", json=payload)
        resp.raise_for_status()

    async def add_vip(self, player: Player, expiration: datetime) -> None:
        """
        POST BASE_URL + add_vip
        payload based on api_examples/add_vip.json (4-12)
        message and reason omitted.
        """
        expiration_str = expiration.replace(tzinfo=None).isoformat() + "Z"
        payload = {
            "player_name": player.display_name,
            "player_id": player.player_id,
            "expiration": expiration_str,
            "description": f"{PREFIX}{player.display_name}",
        }
        resp = await self._client.post("/add_vip", json=payload)
        resp.raise_for_status()

    async def search_players(self, player_name: str) -> list[PlayerSearchResult]:
        """
        POST BASE_URL + get_players_history
        Search for players by name, returns up to 10 results.
        """
        payload = {
            "page": 1,
            "page_size": 10,
            "flags": [],
            "blacklisted": False,
            "exact_name_match": False,
            "ignore_accent": False,
            "is_watched": False,
            "player_name": player_name,
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


# --- Active search tracking -----------------------------------------------------

# Track active searches per user to prevent too many concurrent interactions
# Format: {user_id: [timestamp1, timestamp2, ...]}
_active_searches: dict[int, list[datetime]] = defaultdict(list)
MAX_CONCURRENT_SEARCHES = 3  # Maximum number of active searches per user
SEARCH_TIMEOUT_MINUTES = 10  # Consider searches stale after this time


def _cleanup_stale_searches() -> None:
    """Remove stale search entries older than SEARCH_TIMEOUT_MINUTES."""
    cutoff = datetime.now(UTC) - timedelta(minutes=SEARCH_TIMEOUT_MINUTES)
    for user_id in list(_active_searches.keys()):
        _active_searches[user_id] = [
            ts for ts in _active_searches[user_id] if ts > cutoff
        ]
        if not _active_searches[user_id]:
            del _active_searches[user_id]


def _register_search(user_id: int) -> bool:
    """
    Register a new search for a user.
    Returns True if allowed, False if user has too many active searches.
    """
    _cleanup_stale_searches()
    active_count = len(_active_searches[user_id])
    if active_count >= MAX_CONCURRENT_SEARCHES:
        return False
    _active_searches[user_id].append(datetime.now(UTC))
    return True


def _unregister_search(user_id: int) -> None:
    """Remove the most recent search entry for a user."""
    if user_id in _active_searches and _active_searches[user_id]:
        _active_searches[user_id].pop(0)
        if not _active_searches[user_id]:
            del _active_searches[user_id]


# --- Discord UI: modal & view ---------------------------------------------------

VIP_DAYS = 10


async def _send_response_or_followup(
    interaction: discord.Interaction,
    content: str,
    ephemeral: bool = True,
) -> None:
    """Helper to send message via response or followup depending on interaction state."""
    if interaction.response.is_done():
        await interaction.followup.send(content, ephemeral=ephemeral)
    else:
        await interaction.response.send_message(content, ephemeral=ephemeral)


async def process_vip_reward(
    interaction: discord.Interaction,
    api_client: ApiClient,
    player: Player,
    user: discord.User | discord.Member,
) -> None:
    """
    Process the VIP reward for a selected player. This function handles all the logic
    after a player has been selected (either from search or direct ID).
    """
    # First check: user must have the Hell Let Loose role on Discord
    if HLL_ROLE_ID is not None and isinstance(user, discord.Member):
        has_hll_role = any(role.id == HLL_ROLE_ID for role in user.roles)
        if not has_hll_role:
            await _send_response_or_followup(
                interaction,
                "Pro vyzvednutí této odměny potřebuješ mít na Discordu roli **Hell Let Loose**.\n"
                "Můžeš si ji sám přidat v kanálu <id:customize> výběrem příslušné role.",
            )
            return

    # Local check: has this Discord ID already claimed?
    if has_claimed(user.id):
        await _send_response_or_followup(
            interaction,
            "Tento Discord účet už si jednorázovou **vánoční VIP odměnu** vybral. 🎄\n"
            "Díky, že u nás hraješ, a přejeme veselé Vánoce & šťastný nový rok 2026!",
        )
        return

    # Check if this game/player ID has already been used from another Discord account
    if is_player_claimed(player.player_id, user.id):
        await _send_response_or_followup(
            interaction,
            "Tento **herní účet** už využil vánoční VIP odměnu z **jiného Discord účtu**.\n"
            "Každý herní účet může odměnu čerpat jen jednou.",
        )
        return

    # Determine VIP extension logic
    vip_for_server = next(
        (v for v in player.vips if v.get("server_number") == SERVER_NUMBER),
        None,
    )

    add_vip_needed = True
    new_expiration: Optional[datetime] = None

    if player.is_vip and vip_for_server:
        current_exp_str = vip_for_server.get("expiration")
        if current_exp_str == INFINITE_VIP_DATE:
            add_vip_needed = False
        else:
            base_dt = datetime.fromisoformat(current_exp_str.replace("Z", "+00:00"))
            new_expiration = base_dt + timedelta(days=VIP_DAYS)
    else:
        # Not VIP (or no record for this server): start counting from now
        new_expiration = datetime.now(UTC) + timedelta(days=VIP_DAYS)

    # Link Discord ID on the remote side (edit_player_account)
    try:
        await api_client.edit_player_account(player, user.id)
    except httpx.HTTPError as exc:
        await _send_response_or_followup(
            interaction,
            "Našli jsme tvůj herní profil, ale nepodařilo se ho propojit s tvým Discord účtem.\n"
            "Zkus to prosím za chvíli znovu, nebo kontaktuj administrátora.",
        )
        await send_log_message(
            interaction.client,
            f"❌ Chyba API při `edit_player_account` pro herní ID `{player.player_id}` "
            f"od {user.mention} (`{user.id}`): `{exc}`",
        )
        return

    vip_was_added = False
    if add_vip_needed and new_expiration is not None:
        try:
            await api_client.add_vip(player, new_expiration)
            vip_was_added = True
        except httpx.HTTPError as exc:
            await _send_response_or_followup(
                interaction,
                "Tvůj účet jsme úspěšně propojili, ale při udělování/ prodlužování VIP "
                "nastala chyba v herní API.\n"
                "Prosím kontaktuj administrátora, ať ti VIP dořeší ručně.",
            )
            await send_log_message(
                interaction.client,
                f"❌ Chyba API při `add_vip` pro herní ID `{player.player_id}` "
                f"od {user.mention} (`{user.id}`): `{exc}`",
            )
            return

    # Record locally so we don't process this Discord ID or player again
    record_claim(user.id, player.player_id)

    # Log successful claim to a dedicated channel, if configured
    url = f"{BASE_URL}/records/players/{player.player_id}" if BASE_URL else f"(BASE_URL nedefinováno) `{player.player_id}`"
    await send_log_message(
        interaction.client,
        f"✅ Nové úspěšné vyzvednutí VIP:\n"
        f"- Herní ID: {url}\n"
        f"- Discord účet: {user.mention} (`{user.id}`)",
        suppress_embeds=True,
    )

    if not add_vip_needed:
        msg = (
            f"Tvůj Discord účet je nyní propojený s herním účtem `{player.display_name}`.\n"
            "Na tomto serveru už máš **trvalé VIP**, proto se ti nepočítají žádné další dny.\n\n"
            "Děkujeme, že u nás hraješ, a přejeme ti **veselé Vánoce & šťastný nový rok 2026! 🎄**"
        )
    elif vip_was_added and player.is_vip:
        ts = (
            f"<t:{int(new_expiration.timestamp())}:F>"
            if new_expiration is not None
            else "neznámé datum"
        )
        msg = (
            f"Tvůj Discord účet je nyní propojený s herním účtem `{player.display_name}`.\n"
            f"Tvé VIP na tomto serveru bylo **prodlouženo o {VIP_DAYS} dní** "
            f"(nové vypršení: {ts}).\n\n"
            "Děkujeme, že u nás hraješ, a přejeme ti **veselé Vánoce & šťastný nový rok 2026! 🎄**"
        )
    else:
        ts = (
            f"<t:{int(new_expiration.timestamp())}:F>"
            if new_expiration is not None
            else "neznámé datum"
        )
        msg = (
            f"Tvůj Discord účet je nyní propojený s herním účtem `{player.display_name}`.\n"
            f"Získáváš **{VIP_DAYS} dní VIP** "
            f"(vypršení: {ts}).\n\n"
            "Děkujeme, že u nás hraješ, a přejeme ti **veselé Vánoce & šťastný nový rok 2026! 🎄**"
        )

    await _send_response_or_followup(interaction, msg)


class VipClaimModal(discord.ui.Modal, title="Vánoční VIP odměna"):
    player_name: discord.ui.TextInput = discord.ui.TextInput(
        label="Jméno hráče",
        placeholder="Zadej alespoň 2 znaky jména hráče",
        min_length=2,
        max_length=64,
    )

    def __init__(self, api_client: ApiClient):
        super().__init__()
        self.api_client = api_client

    async def on_submit(self, interaction: discord.Interaction) -> None:
        user = interaction.user
        player_name = str(self.player_name.value).strip()

        if len(player_name) < 2:
            await interaction.response.send_message(
                "Prosím zadej alespoň 2 znaky pro vyhledávání.",
                ephemeral=True,
            )
            return

        # Check if user has too many active searches
        if not _register_search(user.id):
            await interaction.response.send_message(
                f"Máš příliš mnoho aktivních vyhledávání (maximum {MAX_CONCURRENT_SEARCHES}).\n"
                "Počkej prosím, až některé z nich vyprší, nebo je dokonči/zruš.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            search_results = await self.api_client.search_players(player_name)
        except httpx.HTTPError as exc:
            _unregister_search(user.id)  # Clean up on error
            await interaction.followup.send(
                "Omlouváme se, při komunikaci s herní API nastala chyba.\n"
                "Zkus to prosím za chvíli znovu, nebo kontaktuj administrátora.",
                ephemeral=True,
            )
            await send_log_message(
                interaction.client,
                f"❌ Chyba API při `get_players_history` pro jméno `{player_name}` "
                f"od {user.mention} (`{user.id}`): `{exc}`",
            )
            return

        if not search_results:
            _unregister_search(user.id)  # Clean up when no results
            await interaction.followup.send(
                f"Pro jméno **{player_name}** jsme nenašli žádného hráče.\n"
                "Zkus zadat jiné jméno nebo se ujisti, že se hráč alespoň jednou připojil na server.",
                ephemeral=True,
            )
            return

        # Always show select menu for confirmation (even for single result)
        view = PlayerSelectView(self.api_client, search_results, user, user.id)

        result_text = "hráče" if len(search_results) == 1 else "hráčů"
        await interaction.followup.send(
            f"Našli jsme **{len(search_results)}** {result_text} s jménem obsahujícím **{player_name}**.\n"
            "Vyber prosím svůj účet ze seznamu:",
            view=view,
            ephemeral=True,
        )


class PlayerSelect(discord.ui.Select):
    def __init__(self, api_client: ApiClient, search_results: list[PlayerSearchResult], user: discord.User | discord.Member):
        options = []
        for result in search_results[:25]:  # Discord limit is 25 options
            # Truncate display name if too long (Discord limit is 100 chars for label)
            label = result.display_name[:100]
            options.append(
                discord.SelectOption(
                    label=label,
                    value=result.player_id,
                    description=f"ID: {result.player_id[:50]}",  # Description limit is 100 chars
                )
            )

        super().__init__(
            placeholder="Vyber hráče ze seznamu...",
            options=options,
        )
        self.api_client = api_client
        self.user = user

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.user.id:
            await interaction.response.send_message(
                "Tento výběr není pro tebe určený.",
                ephemeral=True,
            )
            return

        selected_player_id = self.values[0]

        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            player = await self.api_client.fetch_player_by_game_id(selected_player_id)
        except httpx.HTTPError as exc:
            await interaction.followup.send(
                "Při načítání profilu hráče nastala chyba.\n"
                "Zkus to prosím za chvíli znovu, nebo kontaktuj administrátora.",
                ephemeral=True,
            )
            await send_log_message(
                interaction.client,
                f"❌ Chyba API při `get_player_profile` pro player_id `{selected_player_id}` "
                f"od {interaction.user.mention} (`{interaction.user.id}`): `{exc}`",
            )
            return

        if player is None:
            await interaction.followup.send(
                "Nepodařilo se načíst profil vybraného hráče.\n"
                "Zkus to prosím za chvíli znovu.",
                ephemeral=True,
            )
            return

        # Process VIP reward
        await process_vip_reward(interaction, self.api_client, player, self.user)
        
        # Unregister search when flow completes
        _unregister_search(self.user.id)


class PlayerSelectView(discord.ui.View):
    def __init__(self, api_client: ApiClient, search_results: list[PlayerSearchResult], user: discord.User | discord.Member, user_id: int):
        super().__init__(timeout=300)  # 5 minute timeout
        self.api_client = api_client
        self.user = user
        self.user_id = user_id
        self.add_item(PlayerSelect(api_client, search_results, user))

    async def on_timeout(self) -> None:
        """Called when the view times out. Clean up the search registration."""
        _unregister_search(self.user_id)
        # Note: We can't send a message here as the interaction is expired
        # The view will automatically become non-interactive

    @discord.ui.button(label="Hledat znovu", style=discord.ButtonStyle.secondary, row=1)
    async def search_again_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,  # type: ignore[override]
    ) -> None:
        if interaction.user.id != self.user.id:
            await interaction.response.send_message(
                "Toto tlačítko není pro tebe určené.",
                ephemeral=True,
            )
            return

        # Unregister current search before opening new one
        _unregister_search(self.user_id)
        # Open the modal again for a new search
        await interaction.response.send_modal(VipClaimModal(self.api_client))

    @discord.ui.button(label="Zrušit", style=discord.ButtonStyle.danger, row=1)
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,  # type: ignore[override]
    ) -> None:
        if interaction.user.id != self.user.id:
            await interaction.response.send_message(
                "Toto tlačítko není pro tebe určené.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "Vyhledávání bylo zrušeno.",
            ephemeral=True,
        )
        # Unregister search when user cancels
        _unregister_search(self.user_id)
        self.stop()


class VipClaimView(discord.ui.View):
    def __init__(self, api_client: ApiClient):
        # timeout=None makes the view persistent across restarts (if re-added in setup_hook)
        super().__init__(timeout=None)
        self.api_client = api_client

    @discord.ui.button(
        label="Vybrat 10 dní VIP zdarma",
        style=discord.ButtonStyle.green,
        custom_id="vip_claim_button",
    )
    async def claim_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,  # type: ignore[override]
    ) -> None:
        # Log every button click
        await send_log_message(
            interaction.client,
            f"🔔 Kliknutí na VIP tlačítko od {interaction.user.mention} "
            f"(`{interaction.user.id}`) v kanálu <#{interaction.channel_id}>.",
        )

        # Absolutely first check: this Discord user must not have claimed VIP before.
        if has_claimed(interaction.user.id):
            await interaction.response.send_message(
                "Tento Discord účet už si jednorázovou **vánoční VIP odměnu** vybral. 🎄\n"
                "Díky, že u nás hraješ, a přejeme veselé Vánoce & šťastný nový rok 2026!",
                ephemeral=True,
            )
            return

        # Optionally restrict which channel this can be used in
        if VIP_CHANNEL_ID is not None and interaction.channel_id != VIP_CHANNEL_ID:
            await interaction.response.send_message(
                "Toto tlačítko můžeš použít jen v určeném kanálu pro vyzvednutí VIP.",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(VipClaimModal(self.api_client))


# --- Bot setup ------------------------------------------------------------------

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

api_client = ApiClient(API_BASE_URL, API_BEARER_TOKEN)


@bot.event
async def on_ready() -> None:
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("------")


@bot.event
async def setup_hook() -> None:  # type: ignore[override]
    """
    Called by discord.py before the bot connects.
    Register persistent views here so the button continues working after restarts.
    """
    init_db()
    bot.add_view(VipClaimView(api_client))

    # Reset & sync application (slash) commands on every startup.
    # For a single-guild bot this keeps the command list fresh.
    if GUILD_ID:
        guild_obj = discord.Object(id=GUILD_ID)
        await bot.tree.sync(guild=guild_obj)


@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guilds(discord.Object(id=GUILD_ID))
@bot.tree.command(
    name="post_vip_claim",
    description="Odešle zprávu s tlačítkem pro vyzvednutí vánočního VIP do tohoto kanálu.",
    guild=discord.Object(id=GUILD_ID),
)
async def post_vip_claim_app(interaction: discord.Interaction) -> None:
    """
    Admin-only slash command to post the VIP claim message in the current channel.
    Run this once in your dedicated VIP channel.
    """
    view = VipClaimView(api_client)
    await interaction.response.send_message(
        "🎁 **Vánoční VIP giveaway** 🎁\n\n"
        "Klikni na tlačítko níže, propojíš svůj herní účet s Discordem a vyzvedneš si "
        "**10 dní VIP zdarma**.\n"
        "Každý Discord účet a herní účet může tuto odměnu využít jen jednou.",
        view=view,
    )


async def main() -> None:
    try:
        await bot.start(DISCORD_TOKEN)
    finally:
        await api_client.close()


if __name__ == "__main__":
    asyncio.run(main())
