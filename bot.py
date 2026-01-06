"""Bot setup, commands, and event handlers."""
import discord
from discord import app_commands
from discord.ext import commands, tasks

from api_client import get_api_client
from config import DISCORD_TOKEN, GUILD_ID
from database import init_db, set_server_channel_id
from views import MemberManagementView, VipClaimView
from views.vip_claim import ThreadCloseView
import httpx
from database import get_server_channel_id


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


@bot.event
async def setup_hook() -> None:  # type: ignore[override]
    """
    Called by discord.py before the bot connects.
    Register persistent views here so the button continues working after restarts.
    """
    init_db()
    bot.add_view(VipClaimView())
    bot.add_view(MemberManagementView())
    bot.add_view(ThreadCloseView())  # Register thread close button for VIP help threads

    # Reset & sync application (slash) commands on every startup.
    # For a single-guild bot this keeps the command list fresh.
    if GUILD_ID:
        guild_obj = discord.Object(id=GUILD_ID)
        await bot.tree.sync(guild=guild_obj)


# --- Commands ---------------------------------------------------------------


@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guilds(discord.Object(id=GUILD_ID))
@bot.tree.command(
    name="post_vip_claim",
    description="Odešle zprávu s tlačítkem pro vyzvednutí VIP do tohoto kanálu.",
    guild=discord.Object(id=GUILD_ID),
)
async def post_vip_claim_app(interaction: discord.Interaction) -> None:
    """
    Admin-only slash command to post the VIP claim message in the current channel.
    Run this once in your dedicated VIP channel.
    """
    view = VipClaimView()
    await interaction.response.send_message(
        "# ⭐ VIP GIVEAWAY ⭐\n"
        "Klikni na tlačítko níže, najdi se podle HLL jména a vyzvedni si **10 dní VIP** na VLK serveru.\n"
        "*Držitel VIP na serveru má zaručenou lepší pozici v čekací frontě.*\n"
        "- *Každý Discord účet a herní účet může tuto odměnu využít jen jednou.*\n"
        "- *Alespoň jednou ses musel/a připojit na náš HLL server.*\n",
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
    channel: discord.VoiceChannel,
) -> None:
    await interaction.response.defer(ephemeral=True)

    # Delete old channel reference if exists
    old_id = get_server_channel_id()
    if old_id and old_id != channel.id:
        set_server_channel_id(None)

    # Set new channel
    set_server_channel_id(channel.id)

    # Initial update
    try:
        await channel.edit(name="🔄 Načítání...", reason="Server status setup")
    except discord.HTTPException:
        await interaction.followup.send(
            "Nepodařilo se upravit název kanálu. Ujisti se, že mám oprávnění Manage Channels.",
            ephemeral=True,
        )
        return

    # Start task if not running
    if not server_status_task.is_running():
        server_status_task.start()

    await interaction.followup.send(
        f"Kanál {channel.mention} byl nastaven pro zobrazení stavu serveru. Aktualizace spuštěna.",
        ephemeral=True,
    )


@app_commands.checks.has_permissions(manage_roles=True)
@bot.tree.command(
    name="post_member_management",
    description="Odešle panel pro správu členství.",
    guild=discord.Object(id=GUILD_ID),
)
async def post_member_management(interaction: discord.Interaction):
    view = MemberManagementView()
    await interaction.response.send_message("**Správa členství** (pouze admin)", view=view)

# --- Tasks ------------------------------------------------------------------

@tasks.loop(minutes=5)
async def server_status_task() -> None:
    guild = bot.get_guild(GUILD_ID) if GUILD_ID else None
    if not guild:
        return

    channel_id = get_server_channel_id()
    channel = guild.get_channel(channel_id) if channel_id else None

    try:
        api_client = get_api_client()
        info = await api_client.get_public_info()
        players = info["player_count"]
        server_name = f"VLK #1 @ {info["current_map"]["map"]["map"]["shortname"]}"
    except httpx.HTTPError:
        players = None
        server_name = "VLK #1"

    if players is None:
        icon = "❌"
        players = "?"
    elif players == 0:
        icon = "😴"
        players = "0"
    elif players <= 30:
        icon = f"🌱"
    elif players <= 95:
        icon = f"🟢"
    else:
        icon = f"🔥"

    new_name = f"{icon} {server_name} ({players})"

    if channel:
        try:
            await channel.edit(name=new_name, reason="Server status update")
            return
        except discord.HTTPException:
            pass

# --- Bot running functions --------------------------------------------------


def get_bot() -> commands.Bot:
    """Return the bot instance."""
    return bot


def get_token() -> str:
    """Return the Discord bot token."""
    return DISCORD_TOKEN

