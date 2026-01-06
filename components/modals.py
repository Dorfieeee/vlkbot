import discord
import httpx

from api_client import get_api_client
from models import PlayerSearchResult
from utils import send_log_message

class GetPlayerProfileModal(discord.ui.Modal, title="Hledat hráče"):
    """Modal for collecting player name to search."""

    player_name: discord.ui.TextInput = discord.ui.TextInput(
        label="Jméno hráče",
        placeholder="Zadej alespoň 2 znaky jména hráče",
        min_length=2,
        max_length=64,
    )

    def __init__(self):
        super().__init__()
        self.api_client = get_api_client()

    async def on_submit(self, interaction: discord.Interaction):
        """Handle the modal submission and search for players."""
        user = interaction.user
        player_name = str(self.player_name.value).strip()

        if len(player_name) < 2:
            await interaction.response.send_message(
                "Prosím zadej alespoň 2 znaky pro vyhledávání.",
                ephemeral=True,
            )
            return


        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            search_results = await self.api_client.search_players(player_name)
        except httpx.HTTPError as exc:
            await interaction.followup.send(
                "Omlouváme se, při komunikaci s herní API nastala chyba.\n"
                "Zkus to prosím za chvíli znovu, nebo kontaktuj administrátora.",
                ephemeral=True,
            )
            await send_log_message(
                interaction.client,
                f"❌ Chyba API při `get_players_history` pro jméno `{player_name}` "
                f"od {user.mention} (`{user.id}`): `{exc}`",
            )
            return

        if not search_results:
            await interaction.followup.send(
                f"Pro jméno **{player_name}** jsme nenašli žádného hráče.\n"
                "Zkus zadat jiné jméno nebo se ujisti, že se hráč alespoň jednou připojil na server.",
                ephemeral=True,
            )
            return
        
        await self.handle_submit(interaction, search_results)

    async def handle_submit(self, interaction: discord.Interaction, search_results: list[PlayerSearchResult]):
        '''To be overriden'''
        pass
