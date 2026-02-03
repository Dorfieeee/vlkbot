import discord
from discord import ui, Interaction

from api_client import get_api_client
from config import MEMBER_ROLE_ID, COMMUNITY_ROLE_ID
from discord_config.dev import REKRUT_ROLE_ID
from utils import send_log_message
from components.modals import GetPlayerProfileModal, SearchTypeSelectView
from views.user_select import PaginatedMemberSelect


class MemberManagementView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.api_client = get_api_client()

    @ui.button(label="Přidat člena", style=discord.ButtonStyle.green, custom_id="mm:add")
    async def add_member(self, interaction: Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)

        recruit_role = interaction.guild.get_role(REKRUT_ROLE_ID)
        if not recruit_role:
            try:
                recruit_role = await interaction.guild.fetch_role(REKRUT_ROLE_ID)
            except discord.NotFound:
                await interaction.response.send_message("Rekrut role nebyla nalezena", ephemeral=True)

        members = recruit_role.members
        view = PaginatedMemberSelect(members=members, confirm_callback=self.promote_recruit)
        await interaction.followup.send(
            f"### [1/2] Discord Roles\n"
            f"Našli jsme **{len(members)}** rekrutu.",
            view=view,
            ephemeral=True
        )

    @ui.button(label="Odebrat člena", style=discord.ButtonStyle.red, custom_id="mm:remove")
    async def remove_member(self, interaction: Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)

        member_role = interaction.guild.get_role(MEMBER_ROLE_ID)
        if not member_role:
            try:
                member_role = await interaction.guild.fetch_role(MEMBER_ROLE_ID)
            except discord.NotFound:
                await interaction.response.send_message("Člen role nebyla nalezena", ephemeral=True)
                return

        members = member_role.members
        view = PaginatedMemberSelect(members=members, confirm_callback=self.demote_member)
        await interaction.followup.send(
            f"Našli jsme **{len(members)}** člena.",
            view=view,
            ephemeral=True
        )

    async def promote_recruit(self, interaction: Interaction, selected_user: discord.Member):
        """Promote a recruit to a full member."""
        try:
            # Check if user already has member role
            member_role = interaction.guild.get_role(MEMBER_ROLE_ID)
            if member_role in selected_user.roles:
                await interaction.edit_original_response(f"{selected_user.mention} už je členem!", ephemeral=True, view=None)
                return
                
            recruit_role = interaction.guild.get_role(REKRUT_ROLE_ID)

            # Add member role, remove recruit role
            await selected_user.add_roles(discord.Object(id=MEMBER_ROLE_ID))
            if recruit_role and recruit_role in selected_user.roles:
                await selected_user.remove_roles(recruit_role)

            # Send confirmation
            log_msg = f"✅ Přidán člen: {selected_user} - základní členství"

            await send_log_message(interaction.client, log_msg)
            await interaction.edit_original_response(
                content=f"### [1/2] Discord Roles\n"
                f"{selected_user.mention} je nyní člen!",
                view=None
            )
            view = ui.View()
            button = discord.ui.Button(label="Propojit s CRCON", style=discord.ButtonStyle.green, custom_id="mm:link_crcon")
            async def link_crcon_callback(interaction: Interaction):
                search_view = SearchTypeSelectView(modal_class=GetPlayerProfileModal)
                await interaction.response.send_message(
                    "Vyber způsob vyhledávání:",
                    view=search_view,
                    ephemeral=True,
                )
            button.callback = link_crcon_callback
            view.add_item(button)
            await interaction.followup.send(
                f"### [2/2] Propojeni s CRCON\n"
                f"Propoj hráče s CRCON profilem pomocí modálu níže.",
                view=view,
                ephemeral=True
            )

        except Exception as e:
            await send_log_message(interaction.client, f"Chyba přidání člena: {e}")
            await interaction.edit_original_response(content="Nastala chyba při přidávání člena.", view=None)

    async def demote_member(self, interaction: Interaction, selected_user: discord.Member):
        """Remove a member from member status."""
        try:
            # Check if user has member role
            member_role = interaction.guild.get_role(MEMBER_ROLE_ID)
            if member_role not in selected_user.roles:
                await interaction.edit_original_response(f"{selected_user.mention} není členem!", ephemeral=True, view=None)
                return

            # Remove member role, add back to community
            await selected_user.remove_roles(member_role)
            await selected_user.add_roles(discord.Object(id=COMMUNITY_ROLE_ID))

            # Add 14-day VIP if we had player data
            # exp = datetime.now(ZoneInfo("UTC")) + timedelta(days=14)
            # await self.api_client.add_vip(player, exp)

            # Send confirmation
            log_msg = f"❌ Odebrán člen: {selected_user} – 14 dní VIP"
            msg = f"{selected_user.mention} byl odebrán z členství."

            await send_log_message(interaction.client, log_msg)
            await interaction.edit_original_response(msg, ephemeral=True, view=None)

        except Exception as e:
            await send_log_message(interaction.client, f"Chyba odebrání člena: {e}")
            await interaction.edit_original_response("Nastala chyba při odebírání člena.", ephemeral=True, view=None)
