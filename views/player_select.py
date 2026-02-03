"""API_Player selection view and dropdown for confirming player identity."""
import discord
import httpx

from api_client import get_api_client
from components.modals import SearchTypeSelectView
from models import API_Player, PlayerSearchResult
from utils import send_log_message


class PlayerSelect(discord.ui.Select):
    """Dropdown menu for selecting a player from search results."""

    def __init__(self, search_results: list[PlayerSearchResult]):
        self.api_client = get_api_client()
        options = []
        for result in search_results[:25]:  # Discord limit is 25 options
            # Truncate display name if too long (Discord limit is 100 chars for label)
            label = result.display_name[:100]
            options.append(
                discord.SelectOption(
                    label=label,
                    value=result.player_id,
                    description=f"ID: {result.player_id[:50]}",  # Description limit is 100 chars
                )
            )

        super().__init__(
            placeholder="Vyber hráče ze seznamu...",
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle player selection from the dropdown."""
        await interaction.response.defer(ephemeral=True)

        selected_player_id = self.values[0]

        try:
            player = await self.api_client.fetch_player_by_game_id(selected_player_id)
        except httpx.HTTPError as exc:
            await interaction.edit_original_response(
                content="Při načítání profilu hráče nastala chyba.\n"
                "Zkus to prosím za chvíli znovu, nebo kontaktuj administrátora.",
                view=None,
            )
            await send_log_message(
                interaction.client,
                f"❌ Chyba API při `get_player_profile` pro player_id `{selected_player_id}` "
                f"od {interaction.user.mention} (`{interaction.user.id}`): `{exc}`",
            )
            return

        if player is None:
            await interaction.edit_original_response(
                content="Nepodařilo se načíst profil vybraného hráče.\n"
                "Zkus to prosím za chvíli znovu.",
                view=None,
            )
            return

        await self.handle_callback(interaction, player)
        
    async def handle_callback(self, interaction: discord.Interaction, player: API_Player):
        '''To be overriden'''
        raise NotImplementedError("handle_callback was not implemented")


class PlayerSelectView(discord.ui.View):
    """View containing player selection dropdown and action buttons."""

    def __init__(self):
        super().__init__(timeout=180)  # 3 minute timeout
        self.modal = None  # set by parent (e.g. VipClaimPlayerSelectView)

    @discord.ui.button(label="Hledat znovu", style=discord.ButtonStyle.secondary, row=1)
    async def search_again_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,  # type: ignore[override]
    ) -> None:
        """Allow user to perform a new search."""

        # Disable current controls so the old select cannot be used again
        for item in self.children:
            item.disabled = True

        await interaction.edit_original_response(content=None, view=self)

        # Show select view again for a new search
        if self.modal is not None:
            view = SearchTypeSelectView(modal_class=self.modal)
            await interaction.edit_original_response(
                content="Vyber způsob vyhledávání:",
                view=view,
            )

    @discord.ui.button(label="Zrušit", style=discord.ButtonStyle.danger, row=1)
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,  # type: ignore[override]
    ) -> None:
        """Allow user to cancel the search."""

        # Disable all controls on the original message
        for item in self.children:
            item.disabled = True

        await interaction.edit_original_response(view=self)

        # Inform the user that the search was cancelled
        await interaction.delete_original_response()
        self.stop()

