"""Utility functions for the bot."""

from datetime import UTC, datetime, timedelta
from typing import Optional

import discord
import httpx

from config import (
    BASE_URL,
    HLL_ROLE_ID,
    FREE_VIP_REWARD_LENGTH,
    LOG_CHANNEL_ID,
)
from database import edit_or_create_player, get_player, has_claimed, is_player_claimed, record_claim
from models import API_Player
from scripts.fetch_player_profile import fetch_profile_page, scrape_with_regex


# --- Logging helpers --------------------------------------------------------


async def send_log_message(
    client: discord.Client,
    content: str,
    suppress_embeds: bool = False,
) -> None:
    """
    Send a message to the configured log channel, if any.
    Fail-closed: logging problems must never affect user flow.
    """
    if LOG_CHANNEL_ID is None:
        return

    try:
        channel = client.get_channel(LOG_CHANNEL_ID)
        if isinstance(channel, discord.TextChannel):
            await channel.send(content, suppress_embeds=suppress_embeds)
    except Exception:
        # Never crash on logging errors
        pass


# --- Interaction helpers ----------------------------------------------------


async def send_response_or_followup(
    interaction: discord.Interaction,
    *args,
    **kwargs,
) -> None:
    """Helper to send message via response or followup depending on interaction state."""
    if interaction.response.is_done():
        await interaction.followup.send(*args, **kwargs)
    else:
        await interaction.response.send_message(*args, **kwargs)


# --- VIP processing ---------------------------------------------------------


async def register_player(
    api_client,
    player: API_Player,
    user: discord.User | discord.Member,
):
    await edit_or_create_player(player.player_id, player.display_name, user.id)
    await api_client.edit_player_account(player, user.id)

async def extend_vip(api_client, player: API_Player, server_number: int, days: int) -> datetime:
    vip_for_server = next(
        (v for v in player.vips if v.get("server_number") == server_number),
        None,
    )

    new_expiration = datetime.now(UTC) + timedelta(days=days)

    if player.is_vip and vip_for_server:
        current_exp_str = vip_for_server.get("expiration")
        from config import INFINITE_VIP_DATE

        if current_exp_str != INFINITE_VIP_DATE:
            base_dt = datetime.fromisoformat(current_exp_str.replace("Z", "+00:00"))
            new_expiration = base_dt + timedelta(days=days)
        else:
            raise InfiniteVipException(f"⁉️ Na VLK#{server_number} už máš **trvalé VIP**, proto se ti nepočítají žádné další dny.\n")

    await api_client.add_vip(player, new_expiration, server_number)

    return new_expiration

async def process_vip_reward(
    interaction: discord.Interaction,
    api_client,  # ApiClient type hint would create circular import
    player: API_Player,
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
            await send_log_message(
                interaction.client,
                "⛔ VIP claim zamítnut: uživatel nemá požadovanou roli.\n"
                f"- Hráč: [{player.display_name}]({BASE_URL}/records/players/{player.player_id})\n"
                f"- Discord účet: {user.mention} (`{user.id}`)",
                suppress_embeds=True,
            )
            await interaction.edit_original_response(
                content="Pro vyzvednutí této odměny musíš být členem komunity.\n"
                "Běž do kanálu <id:customize> a přidej se ke komunitě vybráním odpovědi Hraní Hell Let Loose.",
                view=None,
            )
            return

    # Local check: has this Discord ID already claimed?
    if await has_claimed(user.id):
        await send_log_message(
            interaction.client,
            "⛔ VIP claim zamítnut: Discord účet už VIP odměnu čerpal.\n"
            f"- Hráč: [{player.display_name}]({BASE_URL}/records/players/{player.player_id})\n"
            f"- Discord účet: {user.mention} (`{user.id}`)",
            suppress_embeds=True,
        )
        await interaction.edit_original_response(
            content="Tento Discord účet už si jednorázovou VIP odměnu vybral.\n",
            view=None,
        )
        return

    # Check if this game/player ID has already been used from another Discord account
    if await is_player_claimed(player.player_id, user.id):
        await send_log_message(
            interaction.client,
            "⛔ VIP claim zamítnut: herní účet už VIP odměnu čerpal z jiného Discord účtu.\n"
            f"- Hráč: [{player.display_name}]({BASE_URL}/records/players/{player.player_id})\n"
            f"- Discord účet: {user.mention} (`{user.id}`)",
            suppress_embeds=True,
        )
        await interaction.edit_original_response(
            content="Tento **herní účet** už využil VIP odměnu z **jiného Discord účtu**.\n"
            "Každý herní účet může odměnu čerpat jen jednou.",
            view=None,
        )
        return

    # Link Discord ID on the remote side (edit_player_account)
    try:
        await register_player(api_client, player, user)
    except httpx.HTTPError as exc:
        await send_log_message(
            interaction.client,
            f"❌ Chyba API při `edit_player_account` pro herní ID `{player.player_id}` "
            f"od {user.mention} (`{user.id}`): `{exc}`",
        )

    messages = []
    for server_number in [1]:
        try:
            new_expiration = await extend_vip(api_client, player, server_number, FREE_VIP_REWARD_LENGTH)
        except InfiniteVipException as e:
            messages.append(str(e))
        except httpx.HTTPError as exc:
            await send_log_message(
                interaction.client,
                f"❌ Chyba API při `add_vip` pro herní ID `{player.player_id}` - server: `{server_number}` "
                f"od {user.mention} (`{user.id}`): `{exc}`",
            )
            messages.append(
                f"❌ Něco se pokazilo běhěm přidávání VIP na VLK#{server_number}.\n"
                f"Admin tým byl kontaktován a podívá se na to, hned jak bude čas. Díky za pochopení.\n"
            )
        else:
            messages.append(
                f"✅ Tvé VIP na VLK#{server_number} bylo **prodlouženo o {FREE_VIP_REWARD_LENGTH} dní**\n"
                f"(nové vypršení: <t:{int(new_expiration.timestamp())}:F>).\n"
            )

    # Record locally so we don't process this Discord ID or player again
    await record_claim(user.id, player.player_id)

    # Log successful claim to a dedicated channel, if configured
    await send_log_message(
        interaction.client,
        f"✅ Nové úspěšné vyzvednutí VIP:\n"
        f"- Hráč: [{player.display_name}]({BASE_URL}/records/players/{player.player_id})\n"
        f"- Discord účet: {user.mention} (`{user.id}`)",
        suppress_embeds=True,
    )

    msg = "\n".join(messages)
    await interaction.edit_original_response(content=msg, view=None)

async def start_player_registration(interaction: discord.Interaction, content: Optional[str] = None):
    """Overrides the initial message and starts registration process(discord->hll crcon account)"""
    from views.register_player import RegisterPlayerGetPlayerModal
    from components.modals import SearchTypeSelectView

    player = await get_player(discord_id=interaction.user.id)
    if player:
        await interaction.edit_original_response(content=f"Už u tebe vedeme profil s HLL účetem: Jméno: `{player.player_name}` ID: `{player.player_id}`\nPokud to není tvůj účet nebo ho potřebuješ změnit, napiš Admin týmu pomocí tiketu.")
        return

    view = SearchTypeSelectView(
        modal_class=RegisterPlayerGetPlayerModal,
    )
    await interaction.edit_original_response(
        content=f"{"Napřed nám musíš dát vědět, s jakým účtem hraješ na našem serveru." if content is None else content} ⤵️\n",
        view=view,
        embed=None,
    )

def get_embeds(msg: dict) -> list[discord.Embed]:
    """Convert msg dictionary embeds to discord.py Embed objects"""
    embeds = []
    for embed_data in msg["embeds"]:
        embed = discord.Embed()

        # Add color if present
        if "color" in embed_data:
            embed.color = embed_data["color"]

        # Add image if present
        if "image" in embed_data and "url" in embed_data["image"]:
            embed.set_image(url=embed_data["image"]["url"])

        # Add title if present
        if "title" in embed_data:
            embed.title = embed_data["title"]

        # Add description if present
        if "description" in embed_data:
            embed.description = embed_data["description"]

        # Add fields if present
        if "fields" in embed_data:
            for field in embed_data["fields"]:
                embed.add_field(
                    name=field["name"],
                    value=field["value"],
                    inline=field.get("inline", False),
                )

        embeds.append(embed)
    return embeds

def _normalize_obdobi_to_period(obdobi) -> str:
    """
    Convert different obdobi representations (Choice, int, '90d', etc.)
    into the 'Xd' period string expected by fetch_profile_page.
    """
    days = 0

    try:
        if hasattr(obdobi, "value"):
            days = int(getattr(obdobi, "value"))
        elif isinstance(obdobi, str):
            s = obdobi.strip().lower()
            if s.endswith("d"):
                s = s[:-1]
            days = int(s) if s else 0
        else:
            days = int(obdobi)
    except Exception:
        days = 0

    return f"{days}d" if days > 0 else ""


async def fetch_player_data(api_client, player, obdobi):
    """
    Fetch detailed player statistics for a given period.

    `obdobi` can be:
    - an app_commands.Choice[int] (with `.value`)
    - a plain integer number of days
    - a string like '90d' or '30'
    """
    try:
        api_player = await api_client.fetch_player_by_game_id(player.player_id)
        player_level = api_player.level
        player_name = api_player.display_name
    except Exception:
        player_level = 1
        player_name = player.player_name

    period = _normalize_obdobi_to_period(obdobi)

    try:
        player_profile_html = await fetch_profile_page(player.player_id, period)
        data = scrape_with_regex(player_profile_html)
    except Exception:
        # Fallback if scraping fails for any reason
        data = {}

    data["player_level"] = data.get("player_level", player_level)
    data["player_name"] = data.get("player_name", player_name)
    data["hll_id"] = data.get("hll_id", "")
    data["profile_url"] = data.get("profile_url", "")
    data["comp_matches"] = int(data.get("comp_matches", 0))
    data["kd_ratio"] = data.get("kd_ratio", 0)
    data["kpm"] = data.get("kpm", 0)
    data["win_rate_pct"] = data.get("win_rate_pct", 0)
    data["hours_played"] = int(data.get("hours_played", 0))
    data["matches_played"] = int(data.get("matches_played", 0))
    return data
    


async def get_player_data(player, obdobi) -> str:
    try:
        period = f"{obdobi.value}d" if obdobi.value > 0 else ""
        player_profile_html = await fetch_profile_page(player.player_id, period)
        data = scrape_with_regex(player_profile_html)
        data["hll_id"] = data.get("hll_id")

        if obdobi.value == 0:
            format_string = "%d %b %Y"
            since = datetime.strptime(data["first_seen"], format_string)
        else:
            since = datetime.now() - timedelta(days=obdobi.value)
        since_ts = f"<t:{int(since.timestamp())}:d>"

        value = f"↘ [{data["level"] if data["level"] != "Unknown" else "???"}] [{player.player_name}]({data["profile_url"]}) odehrál `{int(data["hours_played"])}` hodin a `{int(data["matches_played"])}` her od {since_ts}\n"
        value += "↳ "
        stats = ["KD", "KPM", "WR"]
        stats_keys = ["kd_ratio", "kpm", "win_rate_pct"]
        for i, key in enumerate(stats_keys):
            if key in data:
                value += f"{stats[i]}: `{data[key]}`;"
        value += "\n"
        if "comp_matches" in data:
            value += f"↳ Odehráno comp zápasů: `{int(data["comp_matches"])}`\n"
        return value
    except Exception as e:
        return "Data se nepovedla načíst."


class InfiniteVipException(Exception):
    "The player already has a permanent VIP"