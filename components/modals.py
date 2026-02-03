import discord
import httpx

from api_client import get_api_client
from models import PlayerSearchResult
from utils import send_log_message


class SearchTypeSelectView(discord.ui.View):
    """View with a select menu to choose search type, then shows appropriate modal."""
    
    def __init__(self, modal_class):
        super().__init__(timeout=300)  # 5 minute timeout
        self.modal_class = modal_class
    
    @discord.ui.select(
        placeholder="Vyber způsob vyhledávání...",
        options=[
            discord.SelectOption(label='Jméno ve hře', value='player_name', description='Vyhledat podle jména hráče'),
            discord.SelectOption(label='HLL ID', value='player_id', description='Vyhledat podle HLL ID'),
        ],
    )
    async def search_type_select(
        self, 
        interaction: discord.Interaction, 
        select: discord.ui.Select
    ):
        """Handle search type selection and show appropriate modal."""
        search_type = select.values[0]
        
        # Show the appropriate modal based on selection
        if search_type == 'player_name':
            modal = self.modal_class(search_by='player_name')
        else:  # player_id
            modal = self.modal_class(search_by='player_id')
        
        await interaction.response.send_modal(modal)


class GetPlayerProfileModal(discord.ui.Modal, title="Hledat hráče"):
    """Modal for collecting player details to search its game profile."""

    def __init__(self, search_by: str = "player_name"):
        super().__init__()
        self.api_client = get_api_client()
        self.search_by = search_by

        # Conditionally add text inputs based on search type
        if search_by == "player_name":
            self.player_name = discord.ui.TextInput(
                label="Jméno hráče",
                placeholder="Zadej alespoň 2 znaky jména hráče",
                min_length=2,
                max_length=64,
            )
            self.add_item(self.player_name)
        else:  # player_id
            self.player_id = discord.ui.TextInput(
                label="HLL ID hráče",
                placeholder="Zadej alespoň 6 znaků ID hráče",
                min_length=6,
                max_length=32,
            )
            self.add_item(self.player_id)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle the modal submission and search for players."""
        await interaction.response.defer(ephemeral=True)
        user = interaction.user
        
        # Get the search value based on search type
        if self.search_by == "player_name":
            search_value = str(self.player_name.value).strip()
            min_length = 2
            error_msg = "Prosím zadej alespoň 2 znaky pro vyhledávání."
        else:  # player_id
            search_value = str(self.player_id.value).strip()
            min_length = 6
            error_msg = "Prosím zadej alespoň 6 znaků pro vyhledávání."

        if len(search_value) < min_length:
            await interaction.edit_original_response(
                content=error_msg,
                view=None,
            )
            return


        try:
            # Build params dict with dynamic key based on search type
            params = {self.search_by: search_value}
            search_results = await self.api_client.search_players(**params)
        except httpx.HTTPError as exc:
            await interaction.edit_original_response(
                content="Omlouváme se, při komunikaci s herní API nastala chyba.\n"
                "Zkus to prosím za chvíli znovu, nebo kontaktuj administrátora.",
                view=None,
            )
            await send_log_message(
                interaction.client,
                f"❌ Chyba API při `search_players` pro {self.search_by} `{search_value}` "
                f"od {user.mention} (`{user.id}`): `{exc}`",
            )
            return

        if not search_results:
            search_type_label = "jméno" if self.search_by == "player_name" else "HLL ID"
            await interaction.edit_original_response(
                content=f"Pro {search_type_label} **{search_value}** jsme nenašli žádného hráče.\n"
                "Zkus zadat jiné údaje nebo se ujisti, že se hráč alespoň jednou připojil na server.",
                view=None,
            )
            return
        
        await self.handle_submit(interaction, search_results)

    async def handle_submit(self, interaction: discord.Interaction, search_results: list[PlayerSearchResult]):
        '''To be overriden'''
        print(search_results)
        raise NotImplementedError()
