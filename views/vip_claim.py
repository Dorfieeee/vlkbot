"""VIP claim view and modal for initiating the VIP claim flow."""
import discord

from config import SUPPORT_ROLE_ID
from api_client import get_api_client
from components.modals import GetPlayerProfileModal
from database import create_thread_record, has_claimed
from models import Player, PlayerSearchResult
from utils import process_vip_reward, send_log_message
from views.player_select import PlayerSelect, PlayerSelectView
from views.thread_close import ThreadCloseView


class VipClaimPlayerSelect(PlayerSelect):
    async def handle_callback(interaction: discord.Interaction, player: Player):
        api_client = get_api_client()
        await process_vip_reward(interaction, api_client, player, interaction.user)

class VipClaimPlayerSelectView(PlayerSelectView):
    def __init__(self, search_results: list[PlayerSearchResult]):
        super().__init__()
        self.add_item(VipClaimPlayerSelect(search_results))
        self.modal = VipClaimGetPlayerModal

class VipClaimGetPlayerModal(GetPlayerProfileModal):
    async def handle_submit(self, interaction: discord.Interaction, search_results: list[PlayerSearchResult]):
        view = VipClaimPlayerSelectView(search_results)

        result_text = "hráče" if len(search_results) == 1 else "hráčů"
        await interaction.followup.send(
            f"Našli jsme **{len(search_results)}** {result_text} s jménem obsahujícím **{self.player_name}**.\n"
            "Vyber prosím svůj účet ze seznamu:",
            view=view,
            ephemeral=True,
        )

class VipClaimView(discord.ui.View):
    """Persistent view with a button to initiate VIP claiming."""

    def __init__(self):
        # timeout=None makes the view persistent across restarts (if re-added in setup_hook)
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Vyzvedni si VIP",
        style=discord.ButtonStyle.green,
        custom_id="vip_claim_get",
    )
    async def claim_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,  # type: ignore[override]
    ) -> None:
        """Handle the VIP claim button click."""
        # Log every button click
        await send_log_message(
            interaction.client,
            f"🔔 Kliknutí na VIP tlačítko od {interaction.user.mention} "
            f"(`{interaction.user.id}`) v kanálu <#{interaction.channel_id}>.",
        )

        # Absolutely first check: this Discord user must not have claimed VIP before.
        if has_claimed(interaction.user.id):
            await interaction.response.send_message(
                "Tento Discord účet už si jednorázovou **VIP odměnu** vybral.\n",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(VipClaimGetPlayerModal())


    @discord.ui.button(
        label="Potřebuji pomoc",
        style=discord.ButtonStyle.danger,
        custom_id="vip_claim_help",
    )
    async def help_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        if not interaction.channel or interaction.channel.type is not discord.ChannelType.text or not interaction.guild:
            print(interaction.channel)
            return

        thread = await interaction.channel.create_thread(
            name=f"Žádost o pomoc - {interaction.user.display_name}",
            reason="VIP claim help request",
            type=discord.ChannelType.private_thread,
        )

        # Store the thread in the database
        create_thread_record(thread.id, interaction.user.id)

        # First: Add the user who created the ticket to the thread
        try:
            await thread.add_user(interaction.user)
        except (discord.Forbidden, discord.HTTPException):
            # User might already be in thread, ignore
            pass

        # Get the support role
        admin_role = interaction.guild.get_role(SUPPORT_ROLE_ID) if SUPPORT_ROLE_ID else None

        # Second: Send a message tagging all support roles
        # This automatically adds all members of the role (<100 members) to the thread
        if admin_role:
            await thread.send(f"{admin_role.mention}")

        # Third: Send the view message with content and close ticket button
        close_view = ThreadCloseView()
        close_message = await thread.send(
            f"{interaction.user.mention}\n\n"
            f"{interaction.user.display_name} potřebuje pomoc s vyzvednutím VIP.\n"
            "Prosím popiš svůj problém a počkej na odpověď.",
            view=close_view,
        )
        
        # Pin the message with the close button to the top
        try:
            await close_message.pin()
        except discord.Forbidden:
            # If we can't pin, that's okay - the button will still work
            pass
        except discord.HTTPException:
            # Ignore pinning errors
            pass


        await interaction.followup.send(
            f"Vlákno pro pomoc bylo vytvořeno: {thread.mention}",
            ephemeral=True,
        )