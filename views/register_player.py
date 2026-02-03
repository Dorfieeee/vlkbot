import discord
from api_client import get_api_client
from components.modals import GetPlayerProfileModal
from database import edit_or_create_player, get_player
from models import API_Player, PlayerSearchResult
from views.player_select import PlayerSelect, PlayerSelectView


class RegisterPlayerPlayerSelect(PlayerSelect):
    def __init__(self, search_results: list[PlayerSearchResult]):
        super().__init__(search_results)

    async def handle_callback(self, interaction: discord.Interaction, api_player: API_Player):
        api_client = get_api_client()
        user = interaction.user
        
        player = await get_player(player_id=api_player.player_id)
        if player:
            await interaction.edit_original_response(content=f"⚠️ Herní účet `{api_player.display_name}` ID: `{api_player.player_id}` je již propojený s jiným Discord účtem.\nPokud to není tvůj účet, napiš Admin týmu pomocí tiketu.", view=None, embed=None)
            return


        await edit_or_create_player(api_player.player_id, api_player.display_name, user.id)
        await api_client.edit_player_account(api_player, user.id)
        await interaction.edit_original_response(content=f"Tvůj Discord účet {user.mention} je teď propojený s herním účtem: {api_player.display_name}\n*(pouze s touhle aplikací)*", view=None, embed=None)

class RegisterPlayerPlayerSelectView(PlayerSelectView):
    def __init__(self, search_results: list[PlayerSearchResult]):
        super().__init__()
        self.add_item(RegisterPlayerPlayerSelect(search_results))
        self.modal = RegisterPlayerGetPlayerModal

class RegisterPlayerGetPlayerModal(GetPlayerProfileModal):
    async def handle_submit(self, interaction: discord.Interaction, search_results: list[PlayerSearchResult]):
        view = RegisterPlayerPlayerSelectView(search_results)

        result_text = "hráče" if len(search_results) == 1 else "hráčů"
        # Get the search value that was used
        search_value = self.player_name.value if self.search_by == "player_name" else self.player_id.value
        search_type_label = "jménem obsahujícím" if self.search_by == "player_name" else "HLL ID"
        await interaction.edit_original_response(
            content=f"Našli jsme **{len(search_results)}** {result_text} s {search_type_label} **{search_value}**.\n"
            "Vyber prosím svůj účet ze seznamu ⤵️",
            view=view,
        )