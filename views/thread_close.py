import discord

from config import SUPPORT_ROLE_ID
from database import close_thread, get_thread_creator

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
        if SUPPORT_ROLE_ID and any(role.id == SUPPORT_ROLE_ID for role in user.roles):
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