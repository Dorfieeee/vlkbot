import discord
from typing import Optional


class PaginatedMemberSelect(discord.ui.View):
    """View with paginated select component showing only users with a specific role."""
    
    def __init__(self, members: discord.Member, confirm_callback, placeholder: str = "Select user...", timeout: Optional[float] = 300):
        super().__init__(timeout=timeout)

        # Filter members to only those with the specified role
        self.members = members
        self.confirm_callback = confirm_callback
        self.placeholder = placeholder
        self.current_page = 0
        self.items_per_page = 25

        # Calculate total pages
        self.total_pages = (len(self.members) + self.items_per_page - 1) // self.items_per_page

        # Create initial select with first page
        self.user_select = self._create_select()
        self.add_item(self.user_select)

        # Add pagination buttons if needed
        if self.total_pages > 1:
            self.add_item(self.prev_button)
            self.add_item(self.page_label)
            self.add_item(self.next_button)
    
    def _create_select(self) -> discord.ui.Select:
        """Create select component for current page."""
        start_idx = self.current_page * self.items_per_page
        end_idx = start_idx + self.items_per_page
        page_members = self.members[start_idx:end_idx]
        
        options = []
        for member in page_members:
            options.append(discord.SelectOption(
                label=member.display_name[:100],  # Discord label limit
                value=str(member.id),
                description=f"@{member.name}"
            ))
        
        # If no options, add a disabled placeholder
        if not options:
            options.append(discord.SelectOption(
                label="No users found",
                value="none",
                description="No users available"
            ))
        
        select = discord.ui.Select(
            placeholder=f"{self.placeholder} (Page {self.current_page + 1}/{self.total_pages})",
            options=options,
            min_values=1,
            max_values=1,
            disabled=len(options) == 1 and options[0].value == "none"
        )
        select.callback = self.select_callback
        return select
    
    async def select_callback(self, interaction: discord.Interaction):
        """Handle user selection."""
        if self.user_select.values[0] == "none":
            return
        
        selected_user_id = int(self.user_select.values[0])
        selected_user = interaction.guild.get_member(selected_user_id)
        
        # Disable all components to prevent further interaction
        for item in self.children:
            item.disabled = True
        
        async def cancel_callback(interaction: discord.Interaction):
            await interaction.followup.send("Výběr zrušen.", ephemeral=True)

        async def confirm_callback_wrapper(interaction: discord.Interaction):
            await self.confirm_callback(interaction, selected_user)

        confirm_view = ConfirmCancelView(
            text=f"Opravdu chcete vybrat uživatele {selected_user.mention}?",
            confirm_callback=confirm_callback_wrapper,
            cancel_callback=cancel_callback,
        )

        # Then edit the stored message with confirmation view
        await interaction.response.edit_message(
            content=f"Vybrali jste: {selected_user.mention}\n\nOpravdu chcete pokračovat?",
            view=confirm_view
        )
    
    async def handle_user_selection(self, interaction: discord.Interaction, selected_user: discord.Member):
        """Override this method to handle the selected user."""
        await interaction.followup.edit_message(f"Selected user: {selected_user.mention}", ephemeral=True)
    
    @property
    def prev_button(self) -> discord.ui.Button:
        """Previous page button."""
        button = discord.ui.Button(
            emoji="⬅️",
            style=discord.ButtonStyle.secondary,
            disabled=self.current_page == 0
        )
        button.callback = self.prev_page
        return button
    
    @property 
    def next_button(self) -> discord.ui.Button:
        """Next page button."""
        button = discord.ui.Button(
            emoji="➡️", 
            style=discord.ButtonStyle.secondary,
            disabled=self.current_page >= self.total_pages - 1
        )
        button.callback = self.next_page
        return button
    
    @property
    def page_label(self) -> discord.ui.Button:
        """Page indicator button (disabled)."""
        button = discord.ui.Button(
            label=f"{self.current_page + 1}/{self.total_pages}",
            style=discord.ButtonStyle.secondary,
            disabled=True
        )
        return button
    
    async def prev_page(self, interaction: discord.Interaction):
        """Go to previous page."""
        if self.current_page > 0:
            self.current_page -= 1
            await self._update_view(interaction)
    
    async def next_page(self, interaction: discord.Interaction):
        """Go to next page."""
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            await self._update_view(interaction)
    
    async def _update_view(self, interaction: discord.Interaction):
        """Update the view with new page content."""
        # Remove old components
        self.clear_items()
        
        # Create new select for current page
        self.user_select = self._create_select()
        self.add_item(self.user_select)
        
        # Add pagination buttons if needed
        if self.total_pages > 1:
            self.add_item(self.prev_button)
            self.add_item(self.page_label)
            self.add_item(self.next_button)
        
        await interaction.followup.edit_message(view=self)

class ConfirmCancelView(discord.ui.View):
    """View that displays text with confirm and cancel buttons."""

    def __init__(self, text: str, confirm_callback=None, cancel_callback=None, timeout: Optional[float] = 300):
        super().__init__(timeout=timeout)
        self.text = text
        self.confirm_callback = confirm_callback
        self.cancel_callback = cancel_callback

        # Add confirm button
        confirm_button = discord.ui.Button(
            label="Potvrdit",
            style=discord.ButtonStyle.green
        )
        confirm_button.callback = self.confirm_action
        self.add_item(confirm_button)

        # Add cancel button
        cancel_button = discord.ui.Button(
            label="Zrušit",
            style=discord.ButtonStyle.red
        )
        cancel_button.callback = self.cancel_action
        self.add_item(cancel_button)

    async def confirm_action(self, interaction: discord.Interaction):
        """Handle confirm button click."""
        # Disable buttons to prevent multiple clicks
        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(view=self)

        # Call the confirm callback if provided
        if self.confirm_callback:
            await self.confirm_callback(interaction)

    async def cancel_action(self, interaction: discord.Interaction):
        """Handle cancel button click."""
        # Disable buttons to prevent multiple clicks
        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(view=self)

        # Call the cancel callback if provided
        if self.cancel_callback:
            await self.cancel_callback(interaction)