"""VIP claim view and modal for initiating the VIP claim flow."""
import discord
import httpx

from api_client import ApiClient
from config import MAX_CONCURRENT_SEARCHES, VIP_CLAIM_SUPPORT_ROLE_ID
from database import close_thread, create_thread_record, get_thread_creator, has_claimed
from utils import register_search, send_log_message, unregister_search
from views.player_select import PlayerSelectView


class ThreadCloseView(discord.ui.View):
    """View with a button to close/resolve support threads."""
    
    def __init__(self):
        # timeout=None makes the view persistent across restarts
        super().__init__(timeout=None)
    
    def _has_permission(self, user: discord.Member, guild: discord.Guild) -> bool:
        """Check if user has permission to close threads."""
        # Check if user has manage_guild permission
        if user.guild_permissions.manage_guild:
            return True
        
        # Check if user has VIP claim support role
        if VIP_CLAIM_SUPPORT_ROLE_ID and any(role.id == VIP_CLAIM_SUPPORT_ROLE_ID for role in user.roles):
            return True
        
        return False
    
    @discord.ui.button(
        label="Vyřešit a uzavřít",
        style=discord.ButtonStyle.success,
        custom_id="thread_close_resolve",
        emoji="✅",
    )
    async def close_thread_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,  # type: ignore[override]
    ) -> None:
        """Handle the thread close button click."""
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message(
                "Toto tlačítko lze použít pouze ve vlákně.",
                ephemeral=True,
            )
            return
        
        if not isinstance(interaction.user, discord.Member) or not interaction.guild:
            await interaction.response.send_message(
                "Nastala chyba při ověřování oprávnění.",
                ephemeral=True,
            )
            return
        
        # Check permissions
        if not self._has_permission(interaction.user, interaction.guild):
            await interaction.response.send_message(
                "Nemáš oprávnění uzavřít toto vlákno. "
                "Pouze členové s rolí pro podporu nebo správci serveru mohou vlákna uzavírat.",
                ephemeral=True,
            )
            return
        
        thread = interaction.channel

        # Check if thread is already archived
        if thread.archived:
            await interaction.response.send_message(
                "Toto vlákno je již uzavřené.",
                ephemeral=True,
            )
            return

        # Get the ticket creator ID from the database
        ticket_creator_id = get_thread_creator(thread.id)

        # Remove the user who created the ticket (not the bot who created the thread)
        creator_removed = False
        if ticket_creator_id:
            creator = interaction.guild.get_member(ticket_creator_id)
            if creator:
                # Check if bot has permission to manage threads (required to remove users)
                if interaction.guild.me.guild_permissions.manage_threads:
                    try:
                        await thread.remove_user(creator)
                        creator_removed = True
                    except (discord.Forbidden, discord.HTTPException):
                        # Ignore if we can't remove the user
                        pass

        # Mark thread as closed in database
        close_thread(thread.id)

        # Send response first before archiving
        if creator_removed:
            await interaction.response.send_message(
                "✅ Vlákno bylo úspěšně uzavřeno a označeno jako vyřešené. Uživatel byl odstraněn z vlákna.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "✅ Vlákno bylo úspěšně uzavřeno a označeno jako vyřešené.",
                ephemeral=True,
            )

        # Then close the thread (archive and lock it)
        try:
            await thread.edit(archived=True, locked=True, reason=f"Uzavřeno uživatelem {interaction.user}")
        except (discord.Forbidden, discord.HTTPException):
            # Thread is already closed in user's view, ignore errors
            pass


class VipClaimModal(discord.ui.Modal, title="VIP odměna"):
    """Modal for collecting player name to search."""

    player_name: discord.ui.TextInput = discord.ui.TextInput(
        label="Jméno hráče",
        placeholder="Zadej alespoň 2 znaky jména hráče",
        min_length=2,
        max_length=64,
    )

    def __init__(self, api_client: ApiClient):
        super().__init__()
        self.api_client = api_client

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Handle the modal submission and search for players."""
        user = interaction.user
        player_name = str(self.player_name.value).strip()

        if len(player_name) < 2:
            await interaction.response.send_message(
                "Prosím zadej alespoň 2 znaky pro vyhledávání.",
                ephemeral=True,
            )
            return

        # Check if user has too many active searches
        if not register_search(user.id):
            await interaction.response.send_message(
                f"Máš příliš mnoho aktivních vyhledávání (maximum {MAX_CONCURRENT_SEARCHES}).\n"
                "Počkej prosím, až některé z nich vyprší, nebo je dokonči/zruš.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            search_results = await self.api_client.search_players(player_name)
        except httpx.HTTPError as exc:
            unregister_search(user.id)  # Clean up on error
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
            unregister_search(user.id)  # Clean up when no results
            await interaction.followup.send(
                f"Pro jméno **{player_name}** jsme nenašli žádného hráče.\n"
                "Zkus zadat jiné jméno nebo se ujisti, že se hráč alespoň jednou připojil na server.",
                ephemeral=True,
            )
            return

        # Always show select menu for confirmation (even for single result)
        view = PlayerSelectView(self.api_client, search_results, user, user.id)

        result_text = "hráče" if len(search_results) == 1 else "hráčů"
        await interaction.followup.send(
            f"Našli jsme **{len(search_results)}** {result_text} s jménem obsahujícím **{player_name}**.\n"
            "Vyber prosím svůj účet ze seznamu:",
            view=view,
            ephemeral=True,
        )


class VipClaimView(discord.ui.View):
    """Persistent view with a button to initiate VIP claiming."""

    def __init__(self, api_client: ApiClient):
        # timeout=None makes the view persistent across restarts (if re-added in setup_hook)
        super().__init__(timeout=None)
        self.api_client = api_client

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

        await interaction.response.send_modal(VipClaimModal(self.api_client))


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
        admin_role = interaction.guild.get_role(VIP_CLAIM_SUPPORT_ROLE_ID) if VIP_CLAIM_SUPPORT_ROLE_ID else None

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