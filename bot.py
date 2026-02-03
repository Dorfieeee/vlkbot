"""Bot setup, commands, and event handlers."""
from collections import Counter
import discord
from discord import app_commands
from discord.ext import commands, tasks

from api_client import get_public_info
from config import DISCORD_TOKEN, GUILD_ID, MEMBER_ROLE_ID
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
from views import MemberManagementView, VipClaimView
from views.training_grounds import TrainingSelectView, TrainingSignupLogButton, training_player_signup
from views.user_select import PaginatedMemberSelect
from views.vip_claim import ThreadCloseView
import httpx

# --- Bot initialization -----------------------------------------------------

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# --- Event handlers ---------------------------------------------------------


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
    )

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
    await interaction.response.defer()
    view = await TrainingSelectView.create()
    embed = discord.Embed(
        title="Výcvikové centrum Valkyria — Přihlaš se!",
        description="Klikni na tlačítko výcviku → zobrazí se popis + možnost přihlášení.",
        color=discord.Color.red(),
    )
    await interaction.followup.send(embed=embed, view=view)


@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guilds(discord.Object(id=GUILD_ID))
@bot.tree.command(
    name="post_vip_claim",
    description="Odešle zprávu s tlačítkem pro vyzvednutí VIP do tohoto kanálu.",
    guild=discord.Object(id=GUILD_ID),
)
async def post_vip_claim_app(interaction: discord.Interaction) -> None:
    view = VipClaimView()
    embed = discord.Embed(
        title="⭐ VIP GIVEAWAY ⭐",
        description="""
        Vyzvedni si **10 dní VIP** na VLK serveru.
        *Držitel VIP na serveru má zaručenou lepší pozici v čekací frontě.*
        - *Každý Discord účet a herní účet může tuto odměnu využít jen jednou.*\n- *Alespoň jednou ses musel/a připojit na náš HLL server.*
        """
    )
    await interaction.response.send_message(
        embed=embed,
        view=view,
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
    name="show_player_training_progress",
    description="Zobrazí výcvikový progres daného hráče.",
    guild=discord.Object(id=GUILD_ID),
)
async def show_player_training_progress(
    interaction: discord.Interaction,
    user: discord.User,
) -> None:
    await interaction.response.defer(ephemeral=True)

    player = await get_player(discord_id=user.id)

    if not player:
        await interaction.followup.send(
            f"Uživatel {user.display_name} nemá propojený Discord účet s touto aplikací.",
            ephemeral=True,
        )

    pts = await get_player_trainings(player_id=player.id)
    if not pts:
        await interaction.followup.send(content=f"Hráč {player.player_name} nemá žádnou historii výcviků.")
        return

    embed = discord.Embed(
        title=f"Historie výcviků pro {player.player_name}",
        color=discord.Color.blurple(),
    )

    filtered_pts = sorted(pts, key=lambda pt: pt.updated_at, reverse=True)

    from views.training_grounds import EMOJIS , STATUS_TO_TEXT

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
    await interaction.followup.send(embed=embed, ephemeral=True)
        


@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.guilds(discord.Object(id=GUILD_ID))
@bot.tree.command(
    name="show_trainings_states",
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

    pts = await get_player_trainings()

    pts_counter = Counter([pt.training_id for pt in pts])

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
        

async def player_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    players = await get_players(player_name=current)
    return [
        app_commands.Choice(name=p.player_name, value=str(p.id)) for p in players if current.lower() in p.player_name.lower()   
    ]

async def training_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    trainings = await get_trainings()
    return [
        app_commands.Choice(name=t.name, value=t.id) for t in trainings if current.lower() in t.name   
    ]

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
