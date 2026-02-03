import asyncio
import datetime
import re
from typing import Literal, Optional
import discord
from discord import ui

from config import BASE_URL, TRAINING_LOG_CHANNEL_ID
from database import (
    Training,
    create_channel_message,
    create_player_training,
    delete_channel_message,
    get_player,
    get_player_training,
    get_player_trainings,
    get_training,
    get_trainings,
    update_player_training,
)
from models import Player, PlayerTrainingDetail
from utils import start_player_registration

EMOJIS = {
    "rekrut": "<:rekrut:1320447015754137640>",
    "valkyria": "<:valkyria:1096506595497758801>",
    "komunita": "<:HelmaValkyriaKlan:979144403551674449>",
    "hll": "<:hll:1193953513412251819>",
    "reg": "🆕",
    "completed": "✅",
    "assigned": "🟨",
    "interested": "🟨",
    "failed": "🟥",
    "withdrawn": "🟧",
}

STATUS_TO_TEXT = {
    "completed": "Výcvik úspěšně dokončen",
    "assigned": "Zájem o výcvik ti byl přiřazen",
    "interested": "Zájem o výcvik byl podán",
    "withdrawn": "Byl jsi odhlášen",
    "failed": "Výcvik neúspěšně dokončen",
}

# ────────────────────────────────────────────────


class TrainingSelectView(ui.View):
    @classmethod
    async def create(cls):
        self = cls(timeout=None)  # persistent view

        trainings = await get_trainings()  # List[Training]

        # Sort trainings in desired order: komunita < rekrut < valkyria
        level_order = {"komunita": 0, "rekrut": 1, "valkyria": 2}
        sorted_trainings = sorted(
            trainings, key=lambda t: level_order.get(t.level, 999)
        )

        # Group by level just for clarity (optional – you can skip grouping if you prefer flat list)
        by_level = {"komunita": [], "rekrut": [], "valkyria": []}
        for t in sorted_trainings:
            by_level[t.level].append(t)

        # Flatten back — we just needed the sort
        sorted_trainings = (
            by_level["komunita"] + by_level["rekrut"] + by_level["valkyria"]
        )

        # Now create buttons dynamically
        row = 0
        buttons_in_row = 0

        for training in sorted_trainings:
            # Skip if no custom id (shouldn't happen, but safety)
            if not training.id:
                continue

            # Determine emoji based on level
            emoji = EMOJIS.get(training.level, "❔")

            # Create button dynamically
            style = discord.ButtonStyle.blurple
            if training.level == "rekrut":
                style = discord.ButtonStyle.green
            elif training.level == "valkyria":
                style = discord.ButtonStyle.danger
            button = ui.Button(
                label=training.name,
                style=style,
                custom_id=f"training:{training.id}",
                emoji=emoji,
                row=row,
            )

            button.callback = self.create_callback(training.id)

            # Add to view
            self.add_item(button)

            # Layout control: max 5 per row (Discord limit)
            buttons_in_row += 1
            if buttons_in_row >= 5:
                buttons_in_row = 0
                row += 1

            # Safety – Discord has max 5 rows
            if row > 4:
                break

        # Add player progress button
        progress_button = ui.Button(
            label="Tvůj progres",
            style=discord.ButtonStyle.grey,
            custom_id=f"training:dashboard",
            emoji=EMOJIS["hll"],
            row=4,
        )

        progress_button.callback = self.show_player_progress

        self.add_item(progress_button)

        # Add player registration button
        reg_button = ui.Button(
            label="Registrace",
            style=discord.ButtonStyle.grey,
            custom_id=f"training:registration",
            emoji=EMOJIS["reg"],
            row=4,
        )

        reg_button.callback = self.start_registration_process

        self.add_item(reg_button)

        return self

    async def start_registration_process(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)        
        await start_player_registration(interaction, "## Registrace\nPropoj svůj Discord účet s HLL účtem vedeným na našich serverech")

    

    async def show_player_progress(self, interaction: discord.Interaction):
        """Show player's training progress"""
        await interaction.response.defer(ephemeral=True, thinking=True)

        player = await get_player(discord_id=interaction.user.id)
        if not player:
            await interaction.followup.send(content="Nemáš u nás vedený žádný profil.")
            return

        pts = await get_player_trainings(player_id=player.id)
        if not pts:
            await interaction.followup.send(content="Nemáš žádné výcviky.")
            return

        embed = discord.Embed(
            title="Tvůj progres",
            color=discord.Color.blurple(),
        )

        filtered_pts = sorted(pts, key=lambda pt: pt.updated_at, reverse=True)

        for pt in filtered_pts:
            emoji = EMOJIS[pt.status]
            text = f"↳ {STATUS_TO_TEXT[pt.status]} <t:{int(pt.updated_at.timestamp())}:D>"
            if pt.completed_at and pt.status != "completed":
                text += f"\n↳ *Tento výcvik si poprvé dokončil <t:{int(pt.completed_at.timestamp())}:D>*"
            # if pt.status == "withdrawn" and not pt.completed_at:
                # continue
            embed.add_field(
                name=f"{emoji} {pt.training_name}",
                value=text,
                inline=False,
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def show_training_info(
        self, interaction: discord.Interaction, training_id: str
    ):
        """Show detailed info about selected training"""
        # Defer immediately to extend timeout (thinking=True for user feedback)
        await interaction.response.defer(ephemeral=True, thinking=True)

        training = await get_training(training_id)
        if not training:
            await interaction.followup.send(content="Training not found.")
            return

        player = await get_player(discord_id=interaction.user.id)
        player_training = None
        if player:
            player_trainings = await get_player_trainings(player_id=player.id)
            player_training = next(
                (t for t in player_trainings if t.training_id == training.id), None
            )

        view = TrainingSignupView(
            training=training,
            player=player,
            player_training=player_training,
            user=interaction.user,
        )

        embed = discord.Embed(
            title=training.name,
            description=training.description,
            color=discord.Color.blurple(),
        )

        embed.set_image(url=training.img)
        embed.add_field(
            name="Musíš mít jednu z těchto rolí",
            value=", ".join([f"<@&{role_id}>" for role_id in training.required_roles])
            or "—",
            inline=True,
        )
        embed.add_field(
            name="Přiřazená role", value=f"<@&{training.assigned_role}>", inline=True
        )

        # Update the deferred "thinking" message directly
        await interaction.followup.send(embed=embed, view=view)

    def create_callback(self, training_id: str):
        async def callback(interaction: discord.Interaction):
            await self.show_training_info(interaction, training_id)

        return callback


class TrainingSignupView(ui.View):
    def __init__(
        self,
        training: Training,
        player: Optional[Player],
        player_training: Optional[PlayerTrainingDetail],
        user: discord.User | discord.Member,
    ):
        super().__init__(timeout=3 * 60)  # 3 minutes is enough here (not persistent)
        self.training = training
        self.player = player
        self.player_training = player_training
        self.user = user
        self.has_permission_to_sign_up = False

        if len(self.training.required_roles) == 0:
            self.has_permission_to_sign_up = True
        else:
            for role in self.training.required_roles:
                has_perm = int(role) in [r.id for r in user.roles]
                if has_perm:
                    self.has_permission_to_sign_up = True
                    break

        self.is_signed_up = False
        if player_training:
            self.is_signed_up = player_training.status in ["assigned", "interested"]

        self.btn_signup = ui.Button(
            custom_id=f"signup:{training.id}:{user.id}",
            label="Přihlásit se",
            style=discord.ButtonStyle.green,
            disabled=self.is_signed_up or not self.has_permission_to_sign_up,
        )
        self.btn_signup.callback = self.signup
        self.add_item(self.btn_signup)

        if self.is_signed_up and self.has_permission_to_sign_up:
            self.btn_cancel = ui.Button(
                custom_id=f"cancel:{training.id}:{user.id}",
                label="Odhlásit se",
                style=discord.ButtonStyle.red,
            )
            self.btn_cancel.callback = self.cancel
            self.add_item(self.btn_cancel)

    async def signup(self, interaction: discord.Interaction):
        # Defer silently to handle potential delays
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        if not guild:
            await interaction.followup.send(
                "Nepodařilo se vytvořit přihlášku! Důvod: Guild neexistuje.",
                ephemeral=True,
            )
            return

        if not self.player:
            await start_player_registration(interaction)
            return

        role = guild.get_role(int(self.training.assigned_role))
        if not role:
            await interaction.edit_original_response(
                content="Nepodařilo se vytvořit přihlášku! Důvod: Role neexistuje.",
                view=None,
            )
            return

        log_channel = guild.get_channel(TRAINING_LOG_CHANNEL_ID)
        message = None
        channel_message_id = None
        if log_channel and log_channel.type == discord.ChannelType.text:
            if self.player_training and self.player_training.message_id:
                message = await log_channel.fetch_message(
                    self.player_training.message_id
                )
                channel_message_id = self.player_training.message_id
            if not message:
                message = await log_channel.send(
                    content=f"Vytváření přihlášky pro {self.player.player_name} na výcvik: {self.training.name}"
                )
                channel_message_id = await create_channel_message(
                    log_channel.id, message.id
                )

        if not message:
            await interaction.edit_original_response(
                content="Nepodařilo se vytvořit přihlášku! Důvod: Problém s odesláním admin zprávy.",
                view=None,
            )
            return

        try:
            if self.player_training:
                await update_player_training(
                    pt_id=self.player_training.id,
                    status="interested",
                    message_id=channel_message_id,
                )
                pt_id = self.player_training.id
            else:
                pt_id = await create_player_training(
                    player_id=self.player.id,
                    training_id=self.training.id,
                    status="interested",
                    message_id=channel_message_id,
                )
                if not pt_id:
                    raise TrainingNotCreatedException()

            await interaction.user.add_roles(role)

        except discord.Forbidden:
            await interaction.edit_original_response(
                content="Bot nemá právo přidávat tuto roli!", view=None
            )
            return
        except TrainingNotCreatedException:
            await message.delete()
            if channel_message_id:
                await delete_channel_message(channel_message_id)
            return

        embed = discord.Embed(
            title=f"Přihláška na {self.training.name}",
            timestamp=discord.utils.utcnow(),
        )
        embed.set_thumbnail(url=self.training.img)
        embed.add_field(
            name="Uživatel",
            value=f"Discord účet: {interaction.user.mention}\nHráč: [{self.player.player_name}]({BASE_URL}/records/players/{self.player.player_id})",
            inline=False,
        )
        view = TrainingSignupAdminLogView(pt_id)

        await message.edit(content=None, embed=embed, view=view)

        await interaction.edit_original_response(
            content=f"Úspěšně přihlášen na **{self.training.name}**! Role {role.mention} ti byla přidána.",
            view=None,
            embed=None,
        )

    async def cancel(self, interaction: discord.Interaction):
        # Defer already present; keep for consistency
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        if not guild:
            await interaction.edit_original_response(content="Guild neexistuje!")
            return

        pt = await get_player_training(self.player_training.id)

        if not pt:
            await interaction.edit_original_response(
                content="Nepodařilo se odhlásit! Důvod: Výcvik nebyl nalazen."
            )
            return

        role = guild.get_role(int(self.training.assigned_role))

        if role:
            try:
                await interaction.user.remove_roles(role)
            except discord.Forbidden:
                await interaction.edit_original_response(
                    content="Bot nemá právo odebírat roli!"
                )
                return

        log_channel = guild.get_channel(TRAINING_LOG_CHANNEL_ID)
        message = None
        if log_channel and log_channel.type == discord.ChannelType.text:
            if pt.channel_message_id and pt.message_id:
                message = await log_channel.fetch_message(pt.message_id)
                await message.delete()
                await delete_channel_message(pt.channel_message_id)

        await update_player_training(pt_id=pt.id, status="withdrawn")

        await interaction.edit_original_response(
            content=f"Úspěšně odhlášen z **{self.training.name}**.",
            view=None,
            embed=None,
        )


class TrainingSignupLogButton(
    ui.DynamicItem[ui.Button],
    template=r"tsl:(?P<command>\w+):(?P<player_training_id>\d+)?",
):
    def __init__(
        self,
        button: discord.ui.Button,
        command: Literal["completed", "failed", "withdrawn"],
        player_training_id: int,
    ):
        self.command = command
        self.player_training_id = player_training_id

        button.custom_id = f"tsl:{self.command}:{self.player_training_id}"

        super().__init__(button)

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /):  # type: ignore

        command = match["command"]

        if command not in ("completed", "failed", "withdrawn"):
            raise ValueError(
                f"Expected command to be one of ['completed', 'failed', 'withdrawn'], got '{command}'"
            )

        return cls(
            button=item,
            command=command,
            player_training_id=int(match["player_training_id"]),
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()

        pt = await get_player_training(int(self.player_training_id))

        if not pt:
            await interaction.followup.send(
                content=f"Záznam o přihlášce s ID:`{self.player_training_id}` nebyl nalezen",
                ephemeral=True,
            )
            return

        match self.command:
            case "completed":
                await update_player_training(
                    pt_id=pt.id,
                    status=self.command,
                    completed_at=(
                        datetime.datetime.now() if not pt.completed_at else None
                    ),
                )
            case "failed":
                await update_player_training(
                    pt_id=pt.id,
                    status=self.command,
                )
            case "withdrawn":
                await update_player_training(
                    pt_id=pt.id,
                    status=self.command,
                )

        try:
            confirmation = await interaction.followup.send(
                content="Přihláška byla úspěšně vyřešena."
            )
            await interaction.message.delete()
            await delete_channel_message(pt.channel_message_id)
            await asyncio.sleep(3)
            await confirmation.delete()
        except Exception as e:
            print(e)
            pass


class TrainingSignupAdminLogView(ui.View):
    def __init__(self, player_training_id: int = 0):
        super().__init__(timeout=None)
        self.player_training_id = player_training_id

        complete_btn = TrainingSignupLogButton(
            button=ui.Button(
                label="Úspěšně dokončil",
                style=discord.ButtonStyle.green,
                custom_id=f"completed:{player_training_id}",
            ),
            command="completed",
            player_training_id=player_training_id,
        )

        fail_btn = TrainingSignupLogButton(
            button=ui.Button(
                label="Neúspěšně dokončil",
                style=discord.ButtonStyle.danger,
                custom_id=f"fail:{player_training_id}",
            ),
            command="failed",
            player_training_id=player_training_id,
        )

        withdraw_btn = TrainingSignupLogButton(
            button=ui.Button(
                label="Odhlaš z výcviku",
                style=discord.ButtonStyle.grey,
                custom_id=f"withdraw:{player_training_id}",
            ),
            command="withdrawn",
            player_training_id=player_training_id,
        )

        self.add_item(complete_btn)
        self.add_item(fail_btn)
        self.add_item(withdraw_btn)

async def training_player_signup(interaction: discord.Interaction, training: Training, player: Player, player_training: Optional[PlayerTrainingDetail], status: Literal["assigned", "interested"] = "interested"):
    guild = interaction.guild
    if not guild:
        await interaction.followup.send(
            "Nepodařilo se vytvořit přihlášku! Důvod: Guild neexistuje.",
            ephemeral=True,
        )
        return

    role = guild.get_role(int(training.assigned_role))
    if not role:
        await interaction.edit_original_response(
            content="Nepodařilo se vytvořit přihlášku! Důvod: Role neexistuje.",
            view=None,
        )
        return

    user = guild.get_member(int(player.discord_id))
    if not user:
        await interaction.edit_original_response(
            content=f"Nepodařilo se vytvořit přihlášku! Důvod: Discord uživatel neexistuje pro hráče `{player.player_name}` s Discord ID: `{player.discord_id}`.",
            view=None,
        )
        return

    log_channel = guild.get_channel(TRAINING_LOG_CHANNEL_ID)
    message = None
    channel_message_id = None
    if log_channel and log_channel.type == discord.ChannelType.text:
        if player_training and player_training.message_id:
            message = await log_channel.fetch_message(
                player_training.message_id
            )
            channel_message_id = player_training.message_id
        if not message:
            message = await log_channel.send(
                content=f"Vytváření přihlášky pro {player.player_name} na výcvik: {training.name}"
            )
            channel_message_id = await create_channel_message(
                log_channel.id, message.id
            )

    if not message:
        await interaction.edit_original_response(
            content="Nepodařilo se vytvořit přihlášku! Důvod: Problém s odesláním admin zprávy.",
            view=None,
        )
        return

    try:
        if player_training:
            await update_player_training(
                pt_id=player_training.id,
                status=status,
                message_id=channel_message_id,
            )
            pt_id = player_training.id
        else:
            pt_id = await create_player_training(
                player_id=player.id,
                training_id=training.id,
                status=status,
                message_id=channel_message_id,
            )
            if not pt_id:
                raise TrainingNotCreatedException()

        await user.add_roles(role)

    except discord.Forbidden:
        await interaction.edit_original_response(
            content="Bot nemá právo přidávat tuto roli!", view=None
        )
        return
    except TrainingNotCreatedException:
        await message.delete()
        if channel_message_id:
            await delete_channel_message(channel_message_id)
        return

    embed = discord.Embed(
        title=f"Přihláška na {training.name}",
        timestamp=discord.utils.utcnow(),
    )
    embed.set_thumbnail(url=training.img)
    embed.add_field(
        name="Uživatel",
        value=f"Discord účet: {interaction.user.mention}\nHráč: [{player.player_name}]({BASE_URL}/records/players/{player.player_id})",
        inline=False,
    )
    view = TrainingSignupAdminLogView(pt_id)

    await message.edit(content=None, embed=embed, view=view)

    await interaction.edit_original_response(
        content=f"Úspěšně přihlášen na **{training.name}**! Role {role.mention} ti byla přidána.",
        view=None,
        embed=None,
    )

class TrainingNotCreatedException(Exception):
    """When the creation was unsuccessful"""
