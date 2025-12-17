import asyncio
import os
import sqlite3
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


# --- Discord UI: modal & view ---------------------------------------------------

VIP_DAYS = 10


class VipClaimModal(discord.ui.Modal, title="Vánoční VIP odměna"):
    game_id: discord.ui.TextInput = discord.ui.TextInput(
        label="Herní ID",
        placeholder="Zadej svoje herní ID (HLL -> Settings - text vpravo nahoře)",
        min_length=1,
        max_length=64,
    )

    def __init__(self, api_client: ApiClient):
        super().__init__()
        self.api_client = api_client

    async def on_submit(self, interaction: discord.Interaction) -> None:
        user = interaction.user

        # First check: user must have the Hell Let Loose role on Discord
        if HLL_ROLE_ID is not None and isinstance(user, discord.Member):
            has_hll_role = any(role.id == HLL_ROLE_ID for role in user.roles)
            if not has_hll_role:
                await interaction.response.send_message(
                    "Pro vyzvednutí této odměny potřebuješ mít na Discordu roli **Hell Let Loose**.\n"
                    "Můžeš si ji sám přidat v kanálu <id:browse> výběrem příslušné role.",
                    ephemeral=True,
                )
                return

        # Local check: has this Discord ID already claimed?
        if has_claimed(user.id):
            await interaction.response.send_message(
                "Tento Discord účet už si jednorázovou **vánoční VIP odměnu** vybral. 🎄\n"
                "Díky, že u nás hraješ, a přejeme veselé Vánoce & šťastný nový rok 2026!",
                ephemeral=True,
            )
            return

        # Look up player via remote API
        game_id = str(self.game_id.value).strip()

        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            player = await self.api_client.fetch_player_by_game_id(game_id)
        except httpx.HTTPError as exc:
            await interaction.followup.send(
                "Omlouváme se, při komunikaci s herní API nastala chyba.\n"
                "Zkus to prosím za chvíli znovu, nebo kontaktuj administrátora.",
                ephemeral=True,
            )
            await send_log_message(
                interaction.client,
                f"❌ Chyba API při `get_player_profile` pro herní ID `{game_id}` "
                f"od {user.mention} (`{user.id}`): `{exc}`",
            )
            return

        if player is None:
            await interaction.followup.send(
                "Pro zadané **herní ID** jsme nenašli žádného hráče.\n"
                "Nejprve se prosím alespoň jednou připoj na náš server a pak to zkus znovu.",
                ephemeral=True,
            )
            return

        # Check if this game/player ID has already been used from another Discord account
        if is_player_claimed(player.player_id, user.id):
            await interaction.followup.send(
                "Tento **herní účet** už využil vánoční VIP odměnu z **jiného Discord účtu**.\n"
                "Každý herní účet může odměnu čerpat jen jednou.",
                ephemeral=True,
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
            await self.api_client.edit_player_account(player, user.id)
        except httpx.HTTPError as exc:
            await interaction.followup.send(
                "Našli jsme tvůj herní profil, ale nepodařilo se ho propojit s tvým Discord účtem.\n"
                "Zkus to prosím za chvíli znovu, nebo kontaktuj administrátora.",
                ephemeral=True,
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
                await self.api_client.add_vip(player, new_expiration)
                vip_was_added = True
            except httpx.HTTPError as exc:
                await interaction.followup.send(
                    "Tvůj účet jsme úspěšně propojili, ale při udělování/ prodlužování VIP "
                    "nastala chyba v herní API.\n"
                    "Prosím kontaktuj administrátora, ať ti VIP dořeší ručně.",
                    ephemeral=True,
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

        await interaction.followup.send(msg, ephemeral=True)


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
