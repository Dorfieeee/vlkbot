"""Bot setup, commands, and event handlers."""

import asyncio
from collections import Counter
import datetime
import random
from typing import Dict, List, Optional, Tuple
import discord
from discord import app_commands
from discord.ext import commands, tasks

from api_client import get_api_client, get_public_info
from config import (
    BASE_URL,
    DISCORD_TOKEN,
    GUILD_ID,
    INFINITE_VIP_DATE,
    MEMBER_ROLE_ID,
    MIX_EVENT_ROLE_ID,
    REKRUT_ROLE_ID,
    COMMUNITY_ROLE_ID,
    REKRUT_TANK_ROLE_ID,
    MEMBER_TANK_ROLE_ID,
    REKRUT_CHAT_CHANNEL_ID,
    REKRUT_TANK_CHAT_CHANNEL_ID,
    REKRUT_INF_ROLE_ID,
    MEMBER_CHAT_CHANNEL_ID,
)
from database import (
    del_counter_channel,
    del_tracked_server,
    get_counter_channels,
    get_player,
    get_player_trainings,
    get_players,
    get_tracked_servers,
    get_training,
    get_trainings,
    init_db,
    set_counter_channel,
    set_tracked_server,
)
from models import PlayerTrainingDetail, Training
from scripts.fetch_player_profile import fetch_profile_page, scrape_with_regex
from utils import InfiniteVipException, extend_vip, get_player_data, send_log_message
from views import MemberManagementView, VipClaimView
from views.training_grounds import (
    TrainingSelectView,
    TrainingSignupListView,
    TrainingSignupLogButton,
    training_player_signup,
)
from views.hledam_spoluhrace import (
    hledam_spoluhrace,
    LfpCogItem,
    LfpJoinItem,
)
from views.vip_claim import ThreadCloseView
import httpx

# --- Bot initialization -----------------------------------------------------

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# --- Event handlers ---------------------------------------------------------

async def player_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    players = await get_players(player_name=current)
    return [
        app_commands.Choice(name=p.player_name, value=str(p.id))
        for p in players
        if current.lower() in p.player_name.lower()
    ]


async def training_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    trainings = await get_trainings()
    return [
        app_commands.Choice(name=t.name, value=t.id)
        for t in trainings
        if current.lower() in t.name
    ]


@bot.event
async def on_ready() -> None:
    """Called when the bot successfully connects to Discord."""
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("------")
    server_status_task.start()
    counter_channels_task.start()


@bot.event
async def setup_hook() -> None:  # type: ignore[override]
    """
    Called by discord.py before the bot connects.
    Register persistent views here so the button continues working after restarts.
    """
    await init_db()

    bot.add_view(VipClaimView())
    bot.add_view(MemberManagementView())
    bot.add_view(ThreadCloseView())
    bot.add_view(await TrainingSelectView.create())
    bot.add_dynamic_items(
        TrainingSignupLogButton,
        LfpCogItem,
        LfpJoinItem,
    )
    bot.tree.add_command(hledam_spoluhrace)

    if GUILD_ID:
        guild_obj = discord.Object(id=GUILD_ID)
        await bot.tree.sync(guild=guild_obj)


@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guilds(discord.Object(id=GUILD_ID))
@bot.tree.command(
    name="send_training_panel",
    description="Odešle training panel message",
    guild=discord.Object(id=GUILD_ID),
)
async def send_training_panel(interaction: discord.Interaction) -> None:
    view = await TrainingSelectView.create()
    await interaction.response.send_message(view=view)


@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guilds(discord.Object(id=GUILD_ID))
@bot.tree.command(
    name="post_vip_claim",
    description="Odešle zprávu s tlačítkem pro vyzvednutí VIP do tohoto kanálu.",
    guild=discord.Object(id=GUILD_ID),
)
async def post_vip_claim_app(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(
        view=VipClaimView(),
    )


@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guilds(discord.Object(id=GUILD_ID))
@bot.tree.command(
    name="setup_server_status",
    description="Nastaví existující hlasový kanál pro zobrazení stavu serveru.",
    guild=discord.Object(id=GUILD_ID),
)
@app_commands.describe(channel="Hlasový kanál, který se má používat pro stav serveru")
async def setup_server_status(
    interaction: discord.Interaction,
    server_name: str,
    server_url: str,
    channel: discord.VoiceChannel,
) -> None:
    await interaction.response.defer(ephemeral=True)

    await set_tracked_server(server_name, server_url, str(channel.id))

    try:
        await channel.edit(name="🔄 Načítání...", reason="Server status setup")
    except discord.HTTPException:
        await interaction.followup.send(
            "Nepodařilo se upravit název kanálu. Ujisti se, že mám oprávnění Manage Channels.",
            ephemeral=True,
        )
        return

    if not server_status_task.is_running():
        server_status_task.start()

    await interaction.followup.send(
        f"Kanál {channel.mention} byl nastaven pro zobrazení stavu serveru. Aktualizace spuštěna.",
        ephemeral=True,
    )


@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.guilds(discord.Object(id=GUILD_ID))
@bot.tree.command(
    name="zobraz_progres_hrace",
    description="Zobrazí výcvikový progres daného hráče.",
    guild=discord.Object(id=GUILD_ID),
)
async def show_player_training_progress(
    interaction: discord.Interaction,
    user: discord.User,
    private: bool = True,
) -> None:
    await interaction.response.defer(ephemeral=private)

    player = await get_player(discord_id=user.id)

    if not player:
        await interaction.followup.send(
            f"Uživatel {user.display_name} nemá propojený Discord účet s touto aplikací.",
            ephemeral=private,
        )
        return

    pts = await get_player_trainings(player_id=player.id)
    if not pts:
        await interaction.followup.send(
            content=f"Hráč {player.player_name} nemá žádnou historii výcviků."
        )
        return

    embed = discord.Embed(
        title=f"Historie výcviků pro {player.player_name}",
        color=discord.Color.blurple(),
    )

    filtered_pts = sorted(pts, key=lambda pt: pt.updated_at, reverse=True)

    try:
        data = {}
        player_profile_html = await fetch_profile_page(player.player_id, "30d")
        api_client = get_api_client()
        api_player = await api_client.fetch_player_by_game_id(player.player_id)
        if api_player:
            player_level = f" [{api_player.level}] "
        else:
            player_level = ""
        data = scrape_with_regex(player_profile_html)
        data["hll_id"] = data.get("hll_id")
        data["profile_url"] = data.get("profile_url")
        since = datetime.datetime.now() - datetime.timedelta(days=30)
        since_ts = f"<t:{int(since.timestamp())}:d>"
        value = f"↘ {player_level}[{player.player_name}]({data["profile_url"] if data["profile_url"] else ""}) odehrál `{int(data["hours_played"])}` hodin a `{int(data["matches_played"])}` her od {since_ts}\n"
        embed.set_thumbnail(url=data["profile_avatar_url"])
        embed.add_field(
            name=f"Aktivita hráče",
            value=value,
            inline=False,
        )
    except Exception:
        pass

    from views.training_grounds import EMOJIS, STATUS_TO_TEXT

    for pt in filtered_pts:
        emoji = EMOJIS[pt.status]
        text = f"↳ {STATUS_TO_TEXT[pt.status]} <t:{int(pt.updated_at.timestamp())}:D>"
        if pt.completed_at and pt.status != "completed":
            text += f"\n↳ *Tento výcvik si poprvé dokončil <t:{int(pt.completed_at.timestamp())}:D>*"
        embed.add_field(
            name=f"{emoji} {pt.training_name}",
            value=text,
            inline=False,
        )

    await interaction.followup.send(embed=embed, ephemeral=private)


@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.guilds(discord.Object(id=GUILD_ID))
@bot.tree.command(
    name="zobraz_progres_rekrutu",
    description="Zobrazí seznam rekrutů a jejich pokrok v povinných výcvicích.",
    guild=discord.Object(id=GUILD_ID),
)
async def show_rekruts_progress(
    interaction: discord.Interaction,
) -> None:
    await interaction.response.defer(ephemeral=True)

    # Get the recruit role
    rekrut_role = interaction.guild.get_role(REKRUT_ROLE_ID)
    if not rekrut_role:
        await interaction.followup.send(content="Role rekrut nenalezena.")
        return

    # Get all members with the recruit role, sorted by display name
    rekruts = sorted(rekrut_role.members, key=lambda m: m.display_name.lower())
    api_client = get_api_client()

    if not rekruts:
        await interaction.followup.send(content="Žádní členové s rolí rekrut.")
        return

    # Get all trainings and filter mandatory recruit-level ones
    all_trainings = await get_trainings()
    mandatory_trainings: List[Training] = [
        t for t in all_trainings if t.level == "rekrut" and t.is_mandatory
    ]

    # Sort mandatory trainings by name for consistent base order
    mandatory_trainings.sort(key=lambda t: t.name)

    # Collect all fields
    fields: List[Dict[str, str]] = []

    for member in rekruts:
        player = await get_player(discord_id=member.id)

        if not player:
            fields.append(
                {
                    "name": member.display_name,
                    "value": "Nemá záznam hráče.",
                }
            )
            continue

        # Get all player trainings
        player_pts: List[PlayerTrainingDetail] = await get_player_trainings(
            player_id=player.id
        )
        pt_dict: Dict[str, PlayerTrainingDetail] = {
            pt.training_id: pt for pt in player_pts
        }

        # Collect training info
        training_info: List[Tuple[int, str, str, Optional[datetime.datetime]]] = []
        completed_count = 0
        has_any = 0

        for training in mandatory_trainings:
            if training.id not in pt_dict:
                status_key = 0
                status_text = "nepřihlášen"
                date = None
            else:
                has_any += 1
                pt = pt_dict[training.id]
                if pt.status == "completed":
                    status_key = 2
                    status_text = "dokončen"
                    date = pt.completed_at
                    completed_count += 1
                else:
                    status_key = 1
                    if pt.status in ["failed", "withdrawn"]:
                        status_text = "neúspěšný"
                    else:
                        status_text = "přihlášen"
                    date = pt.created_at  # Signup date

            training_info.append((status_key, training.name, status_text, date))

        # Sort by status_key ascending (not signup first, then signup, then completed)
        training_info.sort(key=lambda x: x[0])

        # Build value
        value = ""
        for _, name, status_text, date in training_info:
            ts = ""
            if date:
                unix = int(date.timestamp())
                ts = f" <t:{unix}:d>"  # DD/MM/YYYY format
            value += f"↳ {name}: {status_text}{ts}\n"

        # Determine emoji for name
        total = len(mandatory_trainings)
        if completed_count == total:
            emoji = " ✅"
        elif has_any == 0:
            emoji = " ❌"
        elif has_any == total and completed_count < total:
            emoji = " ⏳"  # Intermediate for signed up to all but not all completed
        else:
            emoji = " ⚠️"  # Partial signups

        data = {}

        try:
            player_profile_html = await fetch_profile_page(player.player_id, "30d")
            api_player = await api_client.fetch_player_by_game_id(player.player_id)
            if api_player:
                player_level = f" [{api_player.level}] "
            else:
                player_level = ""
            data = scrape_with_regex(player_profile_html)
            data["hll_id"] = data.get("hll_id")
            data["profile_url"] = data.get("profile_url")
            since = datetime.datetime.now() - datetime.timedelta(days=30)
            since_ts = f"<t:{int(since.timestamp())}:d>"
            value += f"↘ {player_level}[{player.player_name}]({data["profile_url"] if data["profile_url"] else ""}) odehrál `{int(data["hours_played"])}` hodin a `{int(data["matches_played"])}` her od {since_ts}\n"
        except Exception:
            pass

        name = f"{member.display_name}{emoji}"

        fields.append(
            {
                "name": name,
                "value": value,
            }
        )

    # Split fields into chunks of 20 max per embed (Discord limit 25, but safe margin)
    max_fields_per_embed = 20
    embeds = []
    for i in range(0, len(fields), max_fields_per_embed):
        chunk = fields[i : i + max_fields_per_embed]
        title = (
            "Pokrok rekrutů v povinných výcvicích"
            if i == 0
            else "Pokrok rekrutů - pokračování"
        )
        embed = discord.Embed(
            title=title,
            color=discord.Color.blurple(),
        )
        for field in chunk:
            embed.add_field(
                name=field["name"],
                value=field["value"],
                inline=False,
            )
        embeds.append(embed)

    # Send all embeds
    for embed in embeds:
        await interaction.followup.send(embed=embed, ephemeral=True)


@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.describe(obdobi="Za jaké období chcete zobrazit hráčovi údaje")
@app_commands.choices(
    obdobi=[
        app_commands.Choice(name="30 dní", value=30),
        app_commands.Choice(name="90 dní", value=90),
        app_commands.Choice(name="180 dní", value=180),
        app_commands.Choice(name="356 dní", value=365),
        app_commands.Choice(name="Všechno", value=0),
    ]
)
@bot.tree.command(
    name="zobraz_stats_hracu",
    description="Zobrazí seznam hráčů a herní profil.",
    guild=discord.Object(id=GUILD_ID),
)
async def show_players_profile(
    interaction: discord.Interaction,
    role: discord.Role,
    obdobi: app_commands.Choice[int],
    private: bool = True,
) -> None:
    await interaction.response.defer(ephemeral=private)

    members = sorted(role.members, key=lambda m: m.display_name.lower())
    api_client = get_api_client()

    if not members:
        await interaction.followup.send(content="Žádní členové s rolí rekrut.")
        return

    # Collect fields and tasks
    fields: List[Dict[str, str]] = []
    tasks = []
    player_member_map = []  # To keep track of members with players

    for member in members:
        player = await get_player(discord_id=member.id)

        if not player:
            fields.append(
                {
                    "name": member.display_name,
                    "value": "Nemá záznam hráče.",
                }
            )
            continue

        # For players with records, queue a task
        tasks.append(get_player_data(player, obdobi))
        player_member_map.append(member)

    if tasks:
        # Run all data fetches in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(results):
            member = player_member_map[i]
            if isinstance(result, Exception):
                value = "Data se nepovedla načíst."
            else:
                value = result

            fields.append(
                {
                    "name": member.display_name,
                    "value": value,
                }
            )

    # Split fields into chunks of 20 max per embed (Discord limit 25, but safe margin)
    max_fields_per_embed = 20
    embeds = []
    for i in range(0, len(fields), max_fields_per_embed):
        chunk = fields[i : i + max_fields_per_embed]
        title = f"Hráčské profily pro {role.name}"
        embed = discord.Embed(
            title=title,
            color=discord.Color.blurple(),
        )
        for field in chunk:
            embed.add_field(
                name=field["name"],
                value=field["value"],
                inline=False,
            )
        embeds.append(embed)

    # Send all embeds
    for embed in embeds:
        await interaction.followup.send(embed=embed, ephemeral=private)


@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.describe(obdobi="Za jaké období chcete zobrazit hráčovi údaje")
@app_commands.choices(
    obdobi=[
        app_commands.Choice(name="30 dní", value=30),
        app_commands.Choice(name="90 dní", value=90),
        app_commands.Choice(name="180 dní", value=180),
        app_commands.Choice(name="356 dní", value=365),
        app_commands.Choice(name="Všechno", value=0),
    ]
)
@bot.tree.command(
    name="zobraz_stats_hrace",
    description="Zobrazí herní profil hráče.",
    guild=discord.Object(id=GUILD_ID),
)
async def show_player_profile(
    interaction: discord.Interaction,
    user: discord.Member,
    obdobi: app_commands.Choice[int],
    private: bool = True,
) -> None:
    await interaction.response.defer(ephemeral=private)

    player = await get_player(discord_id=user.id)

    embed = discord.Embed(
        title=f"Profil hráče",
        color=discord.Color.blurple(),
    )

    if not player:
        embed.add_field(
            name=user.display_name,
            value="Nemá záznam hráče.",
        )
        await interaction.followup.send(embed=embed, ephemeral=private)
        return

    stats = await get_player_data(player, obdobi)

    embed.add_field(
        name=user.display_name,
        value=stats,
    )

    await interaction.followup.send(embed=embed, ephemeral=private)


@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.guilds(discord.Object(id=GUILD_ID))
@bot.tree.command(
    name="povys_na_rekruta",
    description="Přidá a odebere potřebné role a přidá VIP na serveru",
    guild=discord.Object(id=GUILD_ID),
)
async def promote_user_to_recrut(
    interaction: discord.Interaction,
    user: discord.Member,
    tankista: bool = False,
):
    await interaction.response.defer(thinking=True, ephemeral=True)

    extend_by = 14
    api_client = get_api_client()

    guild = interaction.guild
    if not guild:
        await interaction.followup.send(
            content=f"Chyba: Nebyla nalezena guilda. Zkus to znova!"
        )
        return

    local_player = await get_player(discord_id=user.id)
    if not local_player:
        await interaction.followup.send(
            content=f"Uživatel {user.mention} nemá propojený Discord s HLL účtem. Uživatel se musí napřed zaregistrovat."
        )
        return

    player = await api_client.fetch_player_by_game_id(local_player.player_id)
    if not player:
        await interaction.followup.send(
            content=f"Chyba: Nepodařilo se načíst údaje o HLL profilu uživatele {user.mention}."
        )
        return

    _roles_to_add = [REKRUT_ROLE_ID, MIX_EVENT_ROLE_ID]

    if tankista:
        _roles_to_add.append(REKRUT_TANK_ROLE_ID)
    else:
        _roles_to_add.append(REKRUT_INF_ROLE_ID)

    roles_to_add = [guild.get_role(r_id) for r_id in _roles_to_add]

    if not (all(roles_to_add)):
        await interaction.followup.send(
            content=f"Chyba: Nepodařilo se načíst vše potřebné role. Zkus to znova!"
        )
        return

    # await user.remove_roles(*roles_to_remove, reason="Povyseni na Rekruta")
    try:
        await user.add_roles(*roles_to_add, reason="Povyseni na Rekruta")
    except Exception:
        await interaction.followup.send(
            content=f"Chyba: Nepodařilo se přidat vše potřebné role. Zkus to znova!\nZkontroluj, zda má bot práva na přidání rolí."
        )
        return

    message = f"Uživatel {user.mention} byl úspěšně povýšen na Rekruta Valkyria.\n"

    for server_number in [1]:
        try:
            new_expiration = await extend_vip(
                api_client, player, server_number, extend_by
            )
        except InfiniteVipException as e:
            message += f"- Hráč už má trvalé VIP na VLK#{server_number}\n"
        except httpx.HTTPError as exc:
            await send_log_message(
                interaction.client,
                f"❌ Chyba API při `add_vip` pro herní ID `{player.player_id}` - server: `{server_number}` "
                f"od {user.mention} (`{user.id}`): `{exc}`",
            )
            message += f"- ❌ Něco se pokazilo běhěm přidávání VIP na VLK#{server_number}.\nAdmin tým byl kontaktován a podívá se na to, hned jak bude čas. Díky za pochopení.\n"
        else:
            message += f"- Hráč obdržel 2 týdny VIP na VLK#{server_number}.\n"

    await send_log_message(
        interaction.client,
        f"✅ Nové povýšení na Rekruta:\n"
        f"- Hráč: [{player.display_name}]({BASE_URL}/records/players/{player.player_id})\n"
        f"- Discord účet: {user.mention} (`{user.id}`)",
        suppress_embeds=True,
    )

    if tankista:
        member_chat = guild.get_channel(REKRUT_TANK_CHAT_CHANNEL_ID)
    else:
        member_chat = guild.get_channel(REKRUT_CHAT_CHANNEL_ID)

    if member_chat and member_chat.type == discord.ChannelType.text:
        embed = discord.Embed(title=player.display_name, color=discord.Colour.green())
        if tankista:
            i = round(random.random())
            images = [
                "https://media.discordapp.net/attachments/1450826189903237284/1472954919236669629/grok-video-fdb1f729-7e51-43fe-8540-6b60d3077d65.gif?ex=699473aa&is=6993222a&hm=12d78f065d05aefa003917390785d425cc0f0dfdbfd363cf50197a00b6eaabd1&=&width=800&height=1186",
                "https://media.discordapp.net/attachments/1450826189903237284/1472954918489952378/grok-video-167ada96-b297-49ea-ad39-13b6bdc65eef.gif?ex=699473aa&is=6993222a&hm=563c028f25e46790d656e6254903b55d30a10231fe5dd7a7f14286e61f68a30f&=&width=800&height=1186"
            ]
            embed.set_image(url=images[i])
        else:
            embed.set_image(url="https://cdn.discordapp.com/attachments/1450826189903237284/1471892968343474390/grok-video-e5f1f650-54db-40b6-8b91-087d44fc7bbc1-ezgif.com-video-to-gif-converter.gif?ex=699096a6&is=698f4526&hm=5679f4a3ca0aa88e91e12c0d85b4c7c5014822203feb7df027e89c1c3df04f72&")
        await member_chat.send(content=f"Hey {user.mention}!\nVítej v řadách rekrutů Valkyrie!", embed=embed)


    await interaction.followup.send(content=message)


@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.guilds(discord.Object(id=GUILD_ID))
@bot.tree.command(
    name="povys_na_clena",
    description="Přidá a odebere potřebné role a přidá VIP na serveru",
    guild=discord.Object(id=GUILD_ID),
)
async def promote_user_to_member(
    interaction: discord.Interaction,
    user: discord.Member,
    tankista: bool = False,
):
    await interaction.response.defer(thinking=True, ephemeral=True)

    extend_by = INFINITE_VIP_DATE
    api_client = get_api_client()

    guild = interaction.guild
    if not guild:
        await interaction.followup.send(
            content=f"Chyba: Nebyla nalezena guilda. Zkus to znova!"
        )
        return

    local_player = await get_player(discord_id=user.id)
    if not local_player:
        await interaction.followup.send(
            content=f"Uživatel {user.mention} nemá propojený Discord s HLL účtem. Uživatel se musí napřed zaregistrovat."
        )
        return

    player = await api_client.fetch_player_by_game_id(local_player.player_id)
    if not player:
        await interaction.followup.send(
            content=f"Chyba: Nepodařilo se načíst údaje o HLL profilu uživatele {user.mention}."
        )
        return

    _roles_to_remove = [COMMUNITY_ROLE_ID, REKRUT_ROLE_ID]
    _roles_to_add = [MEMBER_ROLE_ID]

    if tankista:
        _roles_to_remove.append(REKRUT_TANK_ROLE_ID)
        _roles_to_add.append(MEMBER_TANK_ROLE_ID)
    else:
        _roles_to_remove.append(REKRUT_INF_ROLE_ID)

    try:
        roles_to_remove = [guild.get_role(r_id) for r_id in _roles_to_remove]
        roles_to_add = [guild.get_role(r_id) for r_id in _roles_to_add]
    except Exception:
        await interaction.followup.send(
            content=f"Chyba: Nepodařilo se přidat či odebrat vše potřebné role. Zkus to znova!\nZkontroluj, zda má bot práva na přidání rolí."
        )
        return

    if not (all(roles_to_remove) and all(roles_to_add)):
        await interaction.followup.send(
            content=f"Chyba: Nepodařilo se načíst vše potřebné role. Zkus to znova!"
        )
        return

    await user.remove_roles(*roles_to_remove, reason="Povyseni na Clena")
    await user.add_roles(*roles_to_add, reason="Povyseni na Clena")

    message = f"Uživatel {user.mention} byl úspěšně povýšen na Člena Valkyria.\n"

    for server_number in [1]:
        try:
            await api_client.add_vip(player, datetime.datetime.fromisoformat(extend_by), server_number)
        except httpx.HTTPError as exc:
            await send_log_message(
                interaction.client,
                f"❌ Chyba API při `add_vip` pro herní ID `{player.player_id}` - server: `{server_number}` "
                f"od {user.mention} (`{user.id}`): `{exc}`",
            )
            message += f"- ❌ Něco se pokazilo běhěm přidávání VIP na VLK#{server_number}.\nAdmin tým byl kontaktován a podívá se na to, hned jak bude čas. Díky za pochopení.\n"
        else:
            message += f"- Hráč obdržel trvalé VIP na VLK#{server_number}.\n"

    await send_log_message(
        interaction.client,
        f"✅ Nové povýšení na Člena:\n"
        f"- Hráč: [{player.display_name}]({BASE_URL}/records/players/{player.player_id})\n"
        f"- Discord účet: {user.mention} (`{user.id}`)",
        suppress_embeds=True,
    )

    member_chat = guild.get_channel(MEMBER_CHAT_CHANNEL_ID)
    if member_chat and member_chat.type == discord.ChannelType.text:
        embed = discord.Embed(title=player.display_name, color=discord.Colour.gold())
        embed.set_image(url="https://cdn.discordapp.com/attachments/1450826189903237284/1471890238241771520/grok-video-e5f1f650-54db-40b6-8b91-087d44fc7bbc-ezgif.com-video-to-gif-converter.gif?ex=6990941b&is=698f429b&hm=a9f7992966e64103beaea5b3be3980994b027cc7a207697582a6eadfe7da9dc7&")
        await member_chat.send(content=f"Hey {user.mention}!\nVítej v řadách členů Valkyrie!", embed=embed)

    await interaction.followup.send(content=message)


@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.guilds(discord.Object(id=GUILD_ID))
@bot.tree.command(
    name="zobraz_pocet_prihlasek_vycviky",
    description="Zobrazí výpis výcviků a počet přihlášených.",
    guild=discord.Object(id=GUILD_ID),
)
async def show_trainings_states(
    interaction: discord.Interaction,
) -> None:
    await interaction.response.defer(ephemeral=True)

    trs = await get_trainings()
    if not trs:
        await interaction.followup.send(content=f"Nejsou vypsané žádné výcviky.")
        return

    pts = await get_player_trainings(limit=1_000_000)

    pts_counter = Counter(
        [
            pt.training_id
            for pt in pts
            if pt.status == "assigned" or pt.status == "interested"
        ]
    )

    embed = discord.Embed(
        title=f"Výpis všech výcviků",
        color=discord.Color.blurple(),
    )

    for t in trs:
        role = f"<@{t.assigned_role}>"
        try:
            role = interaction.guild.get_role(int(t.assigned_role)).mention
        except:
            pass
        text = f"↳ Počet přihlášených: {pts_counter[t.id]} {role}"
        embed.add_field(
            name=f"{t.name}",
            value=text,
            inline=False,
        )
    await interaction.followup.send(embed=embed, ephemeral=True)


@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.guilds(discord.Object(id=GUILD_ID))
@bot.tree.command(
    name="spravuj_prihlasky_vycviku",
    description="Zobrazí přihlášky na vybraný výcvik a umožní změnit jejich stav.",
    guild=discord.Object(id=GUILD_ID),
)
@app_commands.describe(training="Vyber výcvik")
@app_commands.autocomplete(training=training_autocomplete)
async def manage_training_signups(
    interaction: discord.Interaction,
    training: str,
) -> None:
    await interaction.response.defer(ephemeral=True)

    # Load only player trainings for this training in 'assigned' or 'interested' state
    assigned_pts = await get_player_trainings(
        training_id=training,
        status="assigned",
        limit=500,
    )
    interested_pts = await get_player_trainings(
        training_id=training,
        status="interested",
        limit=500,
    )

    pts = assigned_pts + interested_pts

    if not pts:
        await interaction.followup.send(
            content="Pro tento výcvik nejsou žádné přihlášky ve stavu *interested* nebo *assigned*.",
            ephemeral=True,
        )
        return

    training_name = pts[0].training_name

    view = TrainingSignupListView(training_name, pts)
    await interaction.followup.send(view=view, ephemeral=True)

@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.guilds(discord.Object(id=GUILD_ID))
@bot.tree.command(
    name="prihlas_hrace_na_vycvik",
    description="Vyber hrace, ktere chces zapsat na výcvik.",
    guild=discord.Object(id=GUILD_ID),
)
@app_commands.describe(training="Vyber vycvik")
@app_commands.autocomplete(training=training_autocomplete)
@app_commands.describe(player="Vyber hrace")
@app_commands.autocomplete(player=player_autocomplete)
async def assign_training(
    interaction: discord.Interaction,
    training: str,
    player: str,
) -> None:
    await interaction.response.defer(ephemeral=True)

    if not training or not player:
        await interaction.followup.send(content="Trenink a Hrac musi byt vyplneni")
        return

    t = await get_training(id=training)
    p = await get_player(id=int(player))

    if not t or not p:
        await interaction.followup.send(content="Trenink nebo Hrac nebyli nalezeni")
        return

    pt = await get_player_trainings(player_id=p.id, training_id=t.id)

    await training_player_signup(interaction, t, p, pt, "assigned")


@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guilds(discord.Object(id=GUILD_ID))
@bot.tree.command(
    name="cleanup_completed_training_roles",
    description="Projde všechny výcviky a odstraní přiřazené role u dokončených player_trainings.",
    guild=discord.Object(id=GUILD_ID),
)
async def cleanup_completed_training_roles(
    interaction: discord.Interaction,
) -> None:
    await interaction.response.defer(ephemeral=True)

    trainings: List[Training] = await get_trainings()
    if not trainings:
        await interaction.followup.send(content="Žádné výcviky nenalezeny.")
        return

    changes = 0

    for training in trainings:
        if not training.assigned_role:
            continue  # No role to remove

        try:
            assigned_role_id = int(training.assigned_role)
        except ValueError:
            print(
                f"Invalid role ID for training {training.id}: {training.assigned_role}"
            )
            continue

        role = interaction.guild.get_role(assigned_role_id)
        if not role:
            print(f"Role not found for ID {assigned_role_id} in training {training.id}")
            continue

        pts: List[PlayerTrainingDetail] = await get_player_trainings(
            training_id=training.id
        )

        for pt in pts:
            if pt.status != "completed":
                continue

            player = await get_player(id=pt.player_id)
            if not player or not player.discord_id:
                print(f"Player not found or no discord_id for player_id {pt.player_id}")
                continue

            try:
                discord_id = int(player.discord_id)
            except ValueError:
                print(f"Invalid discord_id for player {player.id}: {player.discord_id}")
                continue

            member = interaction.guild.get_member(discord_id)
            if not member:
                print(f"Member not found for discord_id {discord_id}")
                continue

            if role in member.roles:
                await member.remove_roles(role)
                print(
                    f"Removed role {role.name} from user {member.display_name} (ID: {discord_id}) for training {training.name} (ID: {training.id})"
                )
                changes += 1

    await interaction.followup.send(
        content=f"Cleanup dokončen. Provedeno {changes} změn.", ephemeral=True
    )


@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guilds(discord.Object(id=GUILD_ID))
@bot.tree.command(
    name="remove_server_status",
    description="Odstraní existující hlasový kanál pro zobrazení stavu serveru.",
    guild=discord.Object(id=GUILD_ID),
)
async def remove_server_status(
    interaction: discord.Interaction,
    channel: discord.VoiceChannel,
) -> None:
    await interaction.response.defer(ephemeral=True)

    await del_tracked_server(str(channel.id))
    channel_name = channel.name

    try:
        await channel.delete(reason="remove_server_status")
    except discord.HTTPException:
        await interaction.followup.send(
            "Nepodařilo se smazat kanál. Ujisti se, že má bot oprávnění Manage Channels.",
            ephemeral=True,
        )
        return

    await interaction.followup.send(
        f"Kanál {channel_name} byl smazán.",
        ephemeral=True,
    )


@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guilds(discord.Object(id=GUILD_ID))
@bot.tree.command(
    name="setup_counter_channel",
    description="Nastaví existující hlasový kanál pro zobrazení počtu členů s danou rolí.",
    guild=discord.Object(id=GUILD_ID),
)
@app_commands.describe(
    channel="Hlasový kanál, který se má používat jako počítadlo",
    role="Role, která se bude započítavat",
    name="Počátační název kanálu. Například '<name>: 1234'",
)
async def setup_counter_channel(
    interaction: discord.Interaction,
    name: str,
    role: discord.Role,
    channel: discord.VoiceChannel,
) -> None:
    await interaction.response.defer(ephemeral=True)

    await set_counter_channel(str(channel.id), name, str(role.id))

    try:
        await channel.edit(
            name=f"{name}: {len(role.members)}",
            reason="Counter channel update",
        )
    except discord.HTTPException:
        await interaction.followup.send(
            "Nepodařilo se upravit název kanálu. Ujisti se, že mám oprávnění Manage Channels.",
            ephemeral=True,
        )
        return

    if not counter_channels_task.is_running():
        counter_channels_task.start()

    await interaction.followup.send(
        f"Kanál {channel.mention} byl nastaven pro zobrazení počtu členů s rolí {role.name}. Aktualizace spuštěna.",
        ephemeral=True,
    )


@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guilds(discord.Object(id=GUILD_ID))
@bot.tree.command(
    name="remove_counter_channel",
    description="Odstraní existující počítadlo rolí.",
    guild=discord.Object(id=GUILD_ID),
)
async def remove_counter_channel(
    interaction: discord.Interaction,
    channel: discord.VoiceChannel,
) -> None:
    await interaction.response.defer(ephemeral=True)

    await del_counter_channel(str(channel.id))
    channel_name = channel.name

    try:
        await channel.delete(reason="remove_counter_channel")
    except discord.HTTPException:
        await interaction.followup.send(
            "Nepodařilo se smazat kanál. Ujisti se, že má bot oprávnění Manage Channels.",
            ephemeral=True,
        )
        return

    await interaction.followup.send(
        f"Kanál {channel_name} byl smazán.",
        ephemeral=True,
    )


@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guilds(discord.Object(id=GUILD_ID))
@bot.tree.command(
    name="list_users",
    description="Vypise list uzivatelu s danou roli.",
    guild=discord.Object(id=GUILD_ID),
)
async def list_users(
    interaction: discord.Interaction,
    role: discord.Role,
) -> None:

    members = []
    for m in role.members:
        members.append(f"{m.display_name},{m.id}")

    await interaction.response.send_message(
        "\n".join(members),
        ephemeral=True,
    )


@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.describe(
    source_role="Role, podle které se vyberou uživatelé",
    target_role="Role, která se má přidat nebo odebrat",
    action="Akce nad target rolí",
)
@app_commands.choices(
    action=[
        app_commands.Choice(name="Přidat", value="add"),
        app_commands.Choice(name="Odebrat", value="remove"),
    ]
)
@bot.tree.command(
    name="uprav_roli_podle_role",
    description="Přidá nebo odebere roli všem uživatelům s vybranou rolí.",
    guild=discord.Object(id=GUILD_ID),
)
async def update_role_for_role_members(
    interaction: discord.Interaction,
    source_role: discord.Role,
    target_role: discord.Role,
    action: app_commands.Choice[str],
) -> None:
    await interaction.response.defer(ephemeral=True, thinking=True)

    if not interaction.guild:
        await interaction.followup.send("Chyba: Nebyla nalezena guilda.")
        return

    members = list(source_role.members)
    if not members:
        await interaction.followup.send(
            f"Role {source_role.mention} nemá žádné členy.", ephemeral=True
        )
        return

    changed = 0
    already_ok = 0
    failed = 0

    for member in members:
        try:
            if action.value == "add":
                if target_role in member.roles:
                    already_ok += 1
                    continue
                await member.add_roles(
                    target_role,
                    reason=(
                        f"Bulk role update by {interaction.user} "
                        f"({interaction.user.id}) via slash command"
                    ),
                )
                changed += 1
            else:
                if target_role not in member.roles:
                    already_ok += 1
                    continue
                await member.remove_roles(
                    target_role,
                    reason=(
                        f"Bulk role update by {interaction.user} "
                        f"({interaction.user.id}) via slash command"
                    ),
                )
                changed += 1
        except discord.HTTPException:
            failed += 1

    action_text = "přidána" if action.value == "add" else "odebrána"
    await interaction.followup.send(
        (
            f"Hromadná úprava dokončena.\n"
            f"- Zdrojová role: {source_role.mention}\n"
            f"- Cílová role: {target_role.mention} ({action_text})\n"
            f"- Změněno: **{changed}**\n"
            f"- Beze změny: **{already_ok}**\n"
            f"- Chyby: **{failed}**"
        ),
        ephemeral=True,
    )


# --- Tasks ------------------------------------------------------------------


@tasks.loop(minutes=5)
async def server_status_task() -> None:
    guild = bot.get_guild(GUILD_ID) if GUILD_ID else None
    if not guild:
        return

    tracked_servers = await get_tracked_servers()

    for server_name, server_url, channel_id in tracked_servers:
        channel = guild.get_channel(int(channel_id)) if channel_id else None

        try:
            info = await get_public_info(server_url)
            players = info["player_count"]
            name_and_map = (
                f'{server_name} @ {info["current_map"]["map"]["map"]["shortname"]}'
            )
        except httpx.HTTPError:
            players = None
            name_and_map = server_name

        if players is None:
            icon = "❌"
            players = "?"
        elif players == 0:
            icon = "😴"
            players = "0"
        elif players <= 30:
            icon = "🌱"
        elif players < 95:
            icon = "🟢"
        else:
            icon = "🔥"

        new_name = f"{icon} {name_and_map} ({players})"

        if channel:
            try:
                await channel.edit(name=new_name, reason="Server status update")
            except discord.HTTPException:
                pass


@tasks.loop(minutes=60)
async def counter_channels_task() -> None:
    guild = bot.get_guild(GUILD_ID) if GUILD_ID else None
    if not guild:
        return

    counters = await get_counter_channels()

    for channel_id, channel_name, role_id in counters:
        role = guild.get_role(int(role_id))
        channel = guild.get_channel(int(channel_id))

        if channel and role:
            try:
                new_name = f"{channel_name}: {len(role.members)}"
                await channel.edit(name=new_name, reason="Counter channel update")
            except discord.HTTPException:
                pass


# --- Bot running functions --------------------------------------------------


def get_bot() -> commands.Bot:
    return bot


def get_token() -> str:
    return DISCORD_TOKEN
