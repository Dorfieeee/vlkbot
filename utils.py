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
    for server_number in [1, 2]:
        # Determine VIP extension logic
        vip_for_server = next(
            (v for v in player.vips if v.get("server_number") == server_number),
            None,
        )

        new_expiration: Optional[datetime] = None

        if player.is_vip and vip_for_server:
            current_exp_str = vip_for_server.get("expiration")
            from config import INFINITE_VIP_DATE

            if current_exp_str != INFINITE_VIP_DATE:
                base_dt = datetime.fromisoformat(current_exp_str.replace("Z", "+00:00"))
                new_expiration = base_dt + timedelta(days=FREE_VIP_REWARD_LENGTH)
            else:
                messages.append(
                    f"⁉️ Na VLK#{server_number} už máš **trvalé VIP**, proto se ti nepočítají žádné další dny.\n"
                )
                continue
        else:
            # Not VIP (or no record for this server): start counting from now
            new_expiration = datetime.now(UTC) + timedelta(days=FREE_VIP_REWARD_LENGTH)

        if new_expiration is not None:
            try:
                await api_client.add_vip(player, new_expiration, server_number)
                messages.append(
                    f"✅ Tvé VIP na VLK#{server_number} bylo **prodlouženo o {FREE_VIP_REWARD_LENGTH} dní**\n"
                    f"(nové vypršení: <t:{int(new_expiration.timestamp())}:F>).\n"
                )
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