"""Player selection view and dropdown for confirming player identity."""
import discord
import httpx

from api_client import ApiClient
from models import PlayerSearchResult
from utils import process_vip_reward, send_log_message, unregister_search


class PlayerSelect(discord.ui.Select):
    """Dropdown menu for selecting a player from search results."""

    def __init__(self, api_client: ApiClient, search_results: list[PlayerSearchResult], user: discord.User | discord.Member):
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
        self.api_client = api_client
        self.user = user

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle player selection from the dropdown."""
        if interaction.user.id != self.user.id:
            await interaction.response.send_message(
                "Tento výběr není pro tebe určený.",
                ephemeral=True,
            )
            return

        selected_player_id = self.values[0]

        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            player = await self.api_client.fetch_player_by_game_id(selected_player_id)
        except httpx.HTTPError as exc:
            await interaction.followup.send(
                "Při načítání profilu hráče nastala chyba.\n"
                "Zkus to prosím za chvíli znovu, nebo kontaktuj administrátora.",
                ephemeral=True,
            )
            await send_log_message(
                interaction.client,
                f"❌ Chyba API při `get_player_profile` pro player_id `{selected_player_id}` "
                f"od {interaction.user.mention} (`{interaction.user.id}`): `{exc}`",
            )
            return

        if player is None:
            await interaction.followup.send(
                "Nepodařilo se načíst profil vybraného hráče.\n"
                "Zkus to prosím za chvíli znovu.",
                ephemeral=True,
            )
            return

        # Process VIP reward
        await process_vip_reward(interaction, self.api_client, player, self.user)
        
        # Unregister search when flow completes
        unregister_search(self.user.id)


class PlayerSelectView(discord.ui.View):
    """View containing player selection dropdown and action buttons."""

    def __init__(self, api_client: ApiClient, search_results: list[PlayerSearchResult], user: discord.User | discord.Member, user_id: int):
        super().__init__(timeout=300)  # 5 minute timeout
        self.api_client = api_client
        self.user = user
        self.user_id = user_id
        self.add_item(PlayerSelect(api_client, search_results, user))

    async def on_timeout(self) -> None:
        """Called when the view times out. Clean up the search registration."""
        unregister_search(self.user_id)
        # Note: We can't send a message here as the interaction is expired
        # The view will automatically become non-interactive

    @discord.ui.button(label="Hledat znovu", style=discord.ButtonStyle.secondary, row=1)
    async def search_again_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,  # type: ignore[override]
    ) -> None:
        """Allow user to perform a new search."""
        if interaction.user.id != self.user.id:
            await interaction.response.send_message(
                "Toto tlačítko není pro tebe určené.",
                ephemeral=True,
            )
            return

        # Import here to avoid circular import
        from views.vip_claim import VipClaimModal

        # Unregister current search before opening new one
        unregister_search(self.user_id)
        # Open the modal again for a new search
        await interaction.response.send_modal(VipClaimModal(self.api_client))

    @discord.ui.button(label="Zrušit", style=discord.ButtonStyle.danger, row=1)
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,  # type: ignore[override]
    ) -> None:
        """Allow user to cancel the search."""
        if interaction.user.id != self.user.id:
            await interaction.response.send_message(
                "Toto tlačítko není pro tebe určené.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "Vyhledávání bylo zrušeno.",
            ephemeral=True,
        )
        # Unregister search when user cancels
        unregister_search(self.user_id)
        self.stop()

