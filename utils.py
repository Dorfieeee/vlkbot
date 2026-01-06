"""Utility functions for the bot."""
from datetime import UTC, datetime, timedelta
from typing import Optional

import discord
import httpx

from config import (
    BASE_URL,
    HLL_ROLE_ID,
    SERVER_NUMBER,
    FREE_VIP_REWARD_LENGTH,
    LOG_CHANNEL_ID,
)
from database import has_claimed, is_player_claimed, record_claim
from models import Player


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
    content: str,
    ephemeral: bool = True,
) -> None:
    """Helper to send message via response or followup depending on interaction state."""
    if interaction.response.is_done():
        await interaction.followup.send(content, ephemeral=ephemeral)
    else:
        await interaction.response.send_message(content, ephemeral=ephemeral)


# --- VIP processing ---------------------------------------------------------


async def process_vip_reward(
    interaction: discord.Interaction,
    api_client,  # ApiClient type hint would create circular import
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
            await send_response_or_followup(
                interaction,
                "Pro vyzvednutí této odměny musíš být členem komunity.\n"
                "Běž do kanálu <id:customize> a přidej se ke komunitě vybráním odpovědi Hraní Hell Let Loose.",
            )
            return

    # Local check: has this Discord ID already claimed?
    if has_claimed(user.id):
        await send_response_or_followup(
            interaction,
            "Tento Discord účet už si jednorázovou VIP odměnu vybral.\n"
        )
        return

    # Check if this game/player ID has already been used from another Discord account
    if is_player_claimed(player.player_id, user.id):
        await send_response_or_followup(
            interaction,
            "Tento **herní účet** už využil VIP odměnu z **jiného Discord účtu**.\n"
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
        from config import INFINITE_VIP_DATE
        if current_exp_str == INFINITE_VIP_DATE:
            add_vip_needed = False
        else:
            base_dt = datetime.fromisoformat(current_exp_str.replace("Z", "+00:00"))
            new_expiration = base_dt + timedelta(days=FREE_VIP_REWARD_LENGTH)
    else:
        # Not VIP (or no record for this server): start counting from now
        new_expiration = datetime.now(UTC) + timedelta(days=FREE_VIP_REWARD_LENGTH)

    # Link Discord ID on the remote side (edit_player_account)
    try:
        await api_client.edit_player_account(player, user.id)
    except httpx.HTTPError as exc:
        await send_response_or_followup(
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
            await send_response_or_followup(
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
            "Na tomto serveru už máš **trvalé VIP**, proto se ti nepočítají žádné další dny.\n"
        )
    elif vip_was_added and player.is_vip:
        ts = (
            f"<t:{int(new_expiration.timestamp())}:F>"
            if new_expiration is not None
            else "neznámé datum"
        )
        msg = (
            f"Tvůj Discord účet je nyní propojený s herním účtem `{player.display_name}`.\n"
            f"Tvé VIP na tomto serveru bylo **prodlouženo o {FREE_VIP_REWARD_LENGTH} dní** "
            f"(nové vypršení: {ts}).\n"
        )
    else:
        ts = (
            f"<t:{int(new_expiration.timestamp())}:F>"
            if new_expiration is not None
            else "neznámé datum"
        )
        msg = (
            f"Tvůj Discord účet je nyní propojený s herním účtem `{player.display_name}`.\n"
            f"Získáváš **{FREE_VIP_REWARD_LENGTH} dní VIP** "
            f"(vypršení: {ts}).\n"
        )

    await send_response_or_followup(interaction, msg)

