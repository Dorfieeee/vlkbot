import asyncio
import datetime
from math import ceil
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


class TrainingSelectView(discord.ui.LayoutView):

    @classmethod
    async def create(cls):
        self = cls(timeout=None)  # persistent view

        container = discord.ui.Container(
            discord.ui.TextDisplay(
                f"# {EMOJIS["valkyria"]} ValkyriaㆍVýcvikové centrum"
            ),
            discord.ui.MediaGallery(discord.MediaGalleryItem(
                media="https://media.discordapp.net/attachments/1450826189903237284/1473315771034636522/88fe69e2-6457-4ebf-9227-9fd48e4b26ac.webp?ex=6995c3bc&is=6994723c&hm=7d4232e03ecc1ab371ca96542f4147e3e14d179f59b674cedd39250341c2a174&=&format=webp&width=2560&height=838",
            )),
            discord.ui.Separator(),
            discord.ui.TextDisplay(
                "### Tvůj osobní panel"
            ),
        )

        # Add player progress and registration buttons in a dedicated ActionRow
        controls_row = discord.ui.ActionRow()

        progress_button = ui.Button(
            label="Tvůj progres",
            style=discord.ButtonStyle.grey,
            custom_id=f"training:dashboard",
            emoji=EMOJIS["hll"],
        )

        progress_button.callback = self.show_player_progress

        controls_row.add_item(progress_button)

        reg_button = ui.Button(
            label="Registrace",
            style=discord.ButtonStyle.grey,
            custom_id=f"training:registration",
            emoji=EMOJIS["reg"],
        )

        reg_button.callback = self.start_registration_process

        controls_row.add_item(reg_button)
        container.add_item(controls_row)
        container.add_item(discord.ui.Separator())
        container.add_item(
            discord.ui.TextDisplay(
                "### Seznam dostupných výcviků"
            )
        )

        trainings = await get_trainings()  # List[Training]
        by_category = {"komunita": [], "rekrut": [], "valkyria": []}
        for t in trainings:
            by_category[t.level].append(t)

        # Now create buttons dynamically into ActionRows
        rows: list[discord.ui.ActionRow] = []

        for category in by_category.keys():
            current_row = discord.ui.ActionRow()
            rows.append(current_row)
            container.add_item(current_row)
            buttons_in_row = 0
            for training in by_category[category]:
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
                )

                button.callback = self.create_callback(training.id)

                # Add button into an ActionRow (max 5 buttons per row)
                if buttons_in_row >= 5:
                    current_row = discord.ui.ActionRow()
                    rows.append(current_row)
                    container.add_item(current_row)
                    buttons_in_row = 0

                current_row.add_item(button)

                # Layout control: max 5 per row (Discord limit)
                buttons_in_row += 1

        self.add_item(container)

        return self

    async def start_registration_process(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)        
        await start_player_registration(interaction, "## Registrace\nPropoj svůj Discord účet s HLL účtem vedeným na našich serverech")

    async def show_player_progress(self, interaction: discord.Interaction):
        """Show player's training progress"""
        await interaction.response.defer(ephemeral=True, thinking=True)

        player = await get_player(discord_id=interaction.user.id)
        if not player:
            await interaction.followup.send(
                content="Nejdříve se musíš zaregistrovat.",
            )
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
            await interaction.edit_original_response(
                content="Nejdříve se musíš zaregistrovat.",
                view=None,
                embed=None,
            )
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
                try:
                    message = await log_channel.fetch_message(pt.message_id)
                    await message.delete()
                    await delete_channel_message(pt.channel_message_id)
                except discord.Forbidden:
                    await interaction.response.send_message(content="Nepodařilo se odstranit zprávu ve výpisu přihlášek. Bot nemá práva.")
                except:
                    pass # when already deleted or not found

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


class TrainingSignupListView(discord.ui.LayoutView):
    """Layout view that lists player trainings and lets a moderator change their state."""

    def __init__(self, training: str, trainings: list[PlayerTrainingDetail]):
        # This view is meant to be used from a slash command, no need to persist forever
        super().__init__(timeout=5 * 60)
        self.training = training
        self.page = 0
        self.max_per_page = 5
        self.total_pages = ceil(len(trainings) / self.max_per_page)

        # Keep an internal mapping so we can refresh the UI after state changes
        self._trainings: dict[int, PlayerTrainingDetail] = {
            pt.id: pt
            for pt in trainings
        }

        self._build_layout()

    def _build_layout(self) -> None:
        """(Re)build all containers and action rows based on current trainings."""
        self.clear_items()

        if not self._trainings:
            empty_container = discord.ui.Container(
                discord.ui.TextDisplay(
                    "### Žádné přihlášky k vyřízení\n"
                    "Nebyly nalezeny žádné výcviky ve stavu *interested* nebo *assigned*."
                ),
                accent_colour=discord.Colour.dark_grey(),
            )
            self.add_item(empty_container)
            return

        self.add_item(discord.ui.Container(discord.ui.TextDisplay(f"## {self.training} ({len(self._trainings)})")))

        for i, pt in enumerate(self._trainings.values()):
            if i < self.page * self.max_per_page:
                continue
            elif i >= (self.page + 1) * self.max_per_page:
                break

            status_text = STATUS_TO_TEXT.get(pt.status, pt.status)
            buttons_disabled = True

            if pt.status == "assigned" or pt.status == "interested":
                accent_colour = discord.Colour.dark_grey()
                buttons_disabled = False
            elif pt.status == "completed":
                accent_colour = discord.Colour.green()
            elif pt.status == "withdrawn":
                accent_colour = discord.Colour.yellow()
            else:
                accent_colour = discord.Colour.red()


            container = discord.ui.Container(
                discord.ui.TextDisplay(
                    f"<@{pt.player_discord_id}> - {pt.player_name}\n"
                    f"Aktuální stav: **{status_text}**"
                ),
                accent_colour=accent_colour,
            )

            row = discord.ui.ActionRow()

            complete_btn = ui.Button(
                label="Úspěšně dokončil",
                style=discord.ButtonStyle.green,
                disabled=buttons_disabled
            )
            fail_btn = ui.Button(
                label="Neúspěšně dokončil",
                style=discord.ButtonStyle.danger,
                disabled=buttons_disabled
            )
            withdraw_btn = ui.Button(
                label="Odhlaš z výcviku",
                style=discord.ButtonStyle.grey,
                disabled=buttons_disabled
            )

            complete_btn.callback = self._make_update_callback(pt, "completed")
            fail_btn.callback = self._make_update_callback(pt, "failed")
            withdraw_btn.callback = self._make_update_callback(pt, "withdrawn")

            row.add_item(complete_btn)
            row.add_item(fail_btn)
            row.add_item(withdraw_btn)

            container.add_item(row)
            self.add_item(container)

        if self.total_pages == 1: return

        pagination_row = discord.ui.ActionRow()

        start = ui.Button(
            label="<<",
            disabled=self.page == 0
        )
        prev = ui.Button(
            label="<",
            disabled=self.page == 0
        )
        curr = ui.Button(
            label=f"{self.page + 1} of {self.total_pages}",
            disabled=True
        )
        next = ui.Button(
            label=">",
            disabled=self.page == self.total_pages - 1
        )
        end = ui.Button(
            label=">>",
            disabled=self.page == self.total_pages - 1
        )

        start.callback = self._make_pagination_callback("start")
        prev.callback = self._make_pagination_callback("prev")
        next.callback = self._make_pagination_callback("next")
        end.callback = self._make_pagination_callback("end")

        pagination_row.add_item(start)
        pagination_row.add_item(prev)
        pagination_row.add_item(curr)
        pagination_row.add_item(next)
        pagination_row.add_item(end)

        self.add_item(pagination_row)

    def _make_pagination_callback(
        self,
        command: Literal["start", "prev", "next", "end"],
    ):
        async def callback(interaction: discord.Interaction) -> None:
            match command:
                case 'start':
                    self.page = 0
                case 'end':
                    self.page = self.total_pages - 1
                case 'next':
                    self.page += 1
                case 'prev':
                    self.page -= 1                

            # Rebuild the layout and update the message in-place
            self._build_layout()
            await interaction.response.edit_message(view=self)

        return callback

    def _make_update_callback(
        self,
        pt: PlayerTrainingDetail,
        command: Literal["completed", "failed", "withdrawn"],
    ):
        async def callback(interaction: discord.Interaction) -> None:
            # Update DB in the same way as TrainingSignupLogButton, but keep this list view

            guild = interaction.guild
            if not guild:
                await interaction.response.send_message(
                    "Nepodařilo se vytvořit přihlášku! Důvod: Guild neexistuje.",
                    ephemeral=True,
                )
                return

            match command:
                case "completed":
                    await update_player_training(
                        pt_id=pt.id,
                        status=command,
                        completed_at=(
                            datetime.datetime.now() if not pt.completed_at else None
                        ),
                    )
                case "failed":
                    await update_player_training(
                        pt_id=pt.id,
                        status=command,
                    )
                case "withdrawn":
                    await update_player_training(
                        pt_id=pt.id,
                        status=command,
                    )

            log_channel = guild.get_channel(TRAINING_LOG_CHANNEL_ID)
            message = None
            if log_channel and log_channel.type == discord.ChannelType.text:
                if pt.channel_message_id and pt.message_id:
                    try:
                        message = await log_channel.fetch_message(pt.message_id)
                        await message.delete()
                        await delete_channel_message(pt.channel_message_id)
                    except discord.Forbidden:
                        await interaction.response.send_message(content="Nepodařilo se odstranit zprávu ve výpisu přihlášek. Bot nemá práva.")
                    except discord.DiscordException:
                        pass # when already deleted or not found

            # Re-fetch the updated detail so we show the latest status
            refreshed = await get_player_training(pt.id)
            if refreshed:
                self._trainings[pt.id] = refreshed

            # Rebuild the layout and update the message in-place
            self._build_layout()
            await interaction.response.edit_message(view=self)

        return callback

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
