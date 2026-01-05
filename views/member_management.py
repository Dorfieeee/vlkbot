import discord
from discord import ui, Interaction, SelectOption
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from api_client import ApiClient
from config import INFINITE_VIP_DATE, MEMBER_ROLE_ID, COMMUNITY_ROLE_ID
from utils import send_log_message, send_response_or_followup
from views.player_select import PlayerSelectView  # reuse existing


class MemberManagementView(ui.View):
    def __init__(self, api_client: ApiClient):
        super().__init__(timeout=None)
        self.api_client = api_client

    @ui.button(label="Přidat člena", style=discord.ButtonStyle.green, custom_id="mm:add")
    async def add_member(self, interaction: Interaction, button: ui.Button):
        modal = UserModal(self.api_client, mode="add")
        await interaction.response.send_modal(modal)

    @ui.button(label="Odebrat člena", style=discord.ButtonStyle.red, custom_id="mm:remove")
    async def remove_member(self, interaction: Interaction, button: ui.Button):
        modal = UserModal(self.api_client, mode="remove")
        await interaction.response.send_modal(modal)


class UserModal(ui.Modal):
    def __init__(self, api_client: ApiClient, mode: str):
        super().__init__(title="Správa členství")
        self.api_client = api_client
        self.mode = mode
        self.user_input = ui.TextInput(
            label="Discord uživatel (ID nebo @mention)",
            placeholder="např. 123456789 nebo @Uživatel",
            required=True,
        )
        self.add_item(self.user_input)

    async def on_submit(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)

        # Extract user ID
        text = self.user_input.value.strip()
        if text.startswith(("<@", "<@!")) and text.endswith(">"):
            text = text[2:-1].lstrip("!")  # Handles both <@id> and <@!id>
        try:
            target_id = int(text)
        except ValueError:
            await interaction.followup.send("Neplatné ID nebo mention.", ephemeral=True)
            return

        member = interaction.guild.get_member(target_id)
        if not member:
            try:
                member = await interaction.guild.fetch_member(target_id)
            except discord.NotFound:
                await interaction.followup.send("Uživatel není na serveru.", ephemeral=True)
                return
        print(member)
        # Start player search
        player_modal = PlayerNameModal(self.api_client, member.id, self.mode)
        await player_modal.send(interaction)


class PlayerNameModal(ui.Modal):
    def __init__(self, api_client: ApiClient, discord_id: int, mode: str):
        super().__init__(title="Hledání hráče")
        self.api_client = api_client
        self.discord_id = discord_id
        self.mode = mode
        self.name_input = ui.TextInput(label="Jméno hráče", placeholder="Zadej jméno")
        self.add_item(self.name_input)

    async def send(self, interaction: Interaction):
        await interaction.followup.send("Zadej jméno hráče:", ephemeral=True)

    async def on_submit(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        name = self.name_input.value
        results = await self.api_client.search_players(name)
        if not results:
            await interaction.followup.send("Žádný hráč nenalezen.", ephemeral=True)
            return

        options = [SelectOption(label=r.display_name[:100], value=r.player_id) for r in results[:25]]
        view = PlayerSelectView(options, self.on_player_selected)
        await interaction.followup.send("Vyber hráče:", view=view, ephemeral=True)

    async def on_player_selected(self, select_inter: Interaction, player_id: str):
        await select_inter.response.defer(ephemeral=True)
        player = await self.api_client.fetch_player_by_game_id(player_id)
        if not player:
            await select_inter.followup.send("Hráč nenalezen.", ephemeral=True)
            return

        member = select_inter.guild.get_member(self.discord_id)
        if not member:
            await select_inter.followup.send("Uživatel není na serveru.", ephemeral=True)
            return

        try:
            if self.mode == "add":
                # Link + make member
                updated_player = player._replace(
                    account_discord_id=str(self.discord_id),
                    account_is_member=True
                )
                await self.api_client.edit_player_account(updated_player)
                infinite = datetime.strptime(INFINITE_VIP_DATE, "%Y-%m-%dT%H:%M:%S%z")
                await self.api_client.add_vip(player, infinite)

                await member.add_roles(discord.Object(id=MEMBER_ROLE_ID))
                await member.remove_roles(discord.Object(id=COMMUNITY_ROLE_ID))

                log_msg = f"✅ Přidán člen: {member} → {player.display_name} ({player.player_id}) – nekonečné VIP"
                msg = f"{member.mention} je nyní člen (nekonečné VIP)."

            else:  # remove
                if player.account_discord_id != str(self.discord_id):
                    await select_inter.followup.send("Hráč není propojen s tímto Discordem.", ephemeral=True)
                    return

                updated_player = player._replace(account_is_member=False)
                await self.api_client.edit_player_account(updated_player)
                exp = datetime.now(ZoneInfo("UTC")) + timedelta(days=14)
                await self.api_client.add_vip(player, exp)

                await member.add_roles(discord.Object(id=COMMUNITY_ROLE_ID))
                await member.remove_roles(discord.Object(id=MEMBER_ROLE_ID))

                log_msg = f"❌ Odebrán člen: {member} → {player.display_name} ({player.player_id}) – 14 dní VIP"
                msg = f"{member.mention} byl odebrán z členství (14 dní VIP)."

            await send_log_message(select_inter.client, log_msg)
            await select_inter.followup.send(msg, ephemeral=True)

        except Exception as e:
            await send_log_message(select_inter.client, f"Chyba správy členství: {e}")
            await select_inter.followup.send("Nastala chyba.", ephemeral=True)