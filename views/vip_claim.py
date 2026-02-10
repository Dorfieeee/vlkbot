"""VIP claim view and modal for initiating the VIP claim flow."""

from datetime import datetime
import discord

from config import SUPPORT_ROLE_ID, INFINITE_VIP_DATE
from api_client import get_api_client
from database import create_thread_record, get_player
from utils import process_vip_reward, start_player_registration
from views.thread_close import ThreadCloseView

BRAND_EMOJIS = {
    "paypal": "<:paypal:1469077619940262010>",
    "kofi": "<:kofi:1469077105454219305>",
    "moneta": "<:moneta:1469080159922552883>",
    "valkyria": "<:valkyria:1096506595497758801>",
}


class VipClaimView(discord.ui.LayoutView):
    """Persistent view with a button to initiate VIP claiming."""

    def __init__(self):
        # timeout=None makes the view persistent across restarts (if re-added in setup_hook)
        super().__init__(timeout=None)
        self.api_client = get_api_client()

    action_row = discord.ui.ActionRow()

    @action_row.button(
        label="Vyzvedni si VIP",
        style=discord.ButtonStyle.gray,
        custom_id="vip_claim_get",
        emoji="⭐",
    )
    async def claim_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,  # type: ignore[override]
    ) -> None:
        """Handle the VIP claim button click."""

        await interaction.response.defer(ephemeral=True, thinking=True)

        player = await get_player(discord_id=interaction.user.id)
        if not player:
            await start_player_registration(interaction)
            return

        try:
            api_player = await self.api_client.fetch_player_by_game_id(player.player_id)
            if not api_player:
                raise Exception(f"No player found with player_id: {player.player_id}")
        except:
            await interaction.edit_original_response(
                content="Z nějakého důvodu se nepodařilo načíst tvůj profil.\nZkus to prosím později.",
                view=None,
            )
            return

        await process_vip_reward(
            interaction, self.api_client, api_player, interaction.user
        )

    @action_row.button(
        label="Tvůj VIP status",
        style=discord.ButtonStyle.gray,
        custom_id="vip_claim_status",
        emoji="📰",
    )
    async def status_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,  # type: ignore[override]
    ) -> None:
        """Handle the VIP status button click."""
        await interaction.response.defer(ephemeral=True, thinking=True)

        player = await get_player(discord_id=interaction.user.id)
        if not player:
            await start_player_registration(interaction)
            return

        try:
            api_player = await self.api_client.fetch_player_by_game_id(player.player_id)
            if not api_player:
                raise Exception(f"No player found with player_id: {player.player_id}")
        except:
            await interaction.edit_original_response(
                content="Z nějakého důvodu se nepodařilo načíst tvůj profil.\nZkus to prosím později.",
                view=None,
            )
            return

        embed = discord.Embed(
            color=discord.Color.blue(),
            title=f"VIP Status pro {api_player.display_name}",
        )

        for server_number in [1, 2]:
            server_name = f"VLK #{server_number}"
            vip = next(
                (v for v in api_player.vips if v.get("server_number") == server_number),
                None,
            )

            if not vip:
                text = "↳ momentálně **nemáš VIP**"
            else:
                current_exp_str = vip.get("expiration")

                if current_exp_str != INFINITE_VIP_DATE:
                    expiration = datetime.fromisoformat(
                        current_exp_str.replace("Z", "+00:00")
                    ).timestamp()
                    text = f"↳ máš **VIP do <t:{int(expiration)}:D>**"
                else:
                    text = f"↳ máš **trvalé VIP**"
            embed.add_field(name=server_name, value=text, inline=False)

        await interaction.edit_original_response(embed=embed, content=None, view=None)

    @action_row.button(
        label="Registrace",
        style=discord.ButtonStyle.gray,
        custom_id="vip_claim_reg",
        emoji="🆕",
    )
    async def reg_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,  # type: ignore[override]
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        await start_player_registration(
            interaction,
            "## Registrace\nPropoj svůj Discord účet s HLL účtem vedeným na našich serverech",
        )

    @action_row.button(
        label="Potřebuji pomoc",
        style=discord.ButtonStyle.gray,
        custom_id="vip_claim_help",
        emoji="❓",
    )
    async def help_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        if (
            not interaction.channel
            or interaction.channel.type is not discord.ChannelType.text
            or not interaction.guild
        ):
            return

        thread = await interaction.channel.create_thread(
            name=f"Žádost o pomoc - {interaction.user.display_name}",
            reason="VIP claim help request",
            type=discord.ChannelType.private_thread,
        )

        # Store the thread in the database
        await create_thread_record(thread.id, interaction.user.id)

        # First: Add the user who created the ticket to the thread
        try:
            await thread.add_user(interaction.user)
        except (discord.Forbidden, discord.HTTPException):
            # User might already be in thread, ignore
            pass

        # Get the support role
        admin_role = (
            interaction.guild.get_role(SUPPORT_ROLE_ID) if SUPPORT_ROLE_ID else None
        )

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

    @action_row.button(
        label="Přispěj na servery",
        style=discord.ButtonStyle.danger,
        custom_id="vip_donate",
        emoji="💌",
    )
    async def donate_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        embed = discord.Embed(
            title="Příspěvek",
            description=f"""
            Jako každý projekt tvořený pro zábavu lidí, i tento vyžaduje velké úsilí a náklady.
            Každý má možnost přispět finančním příspěvkem, ať už jen na chod serverů nebo na rozvoj komunity.

            Celkové náklady pro běh serverů a všech služeb jsou pro rok 2026 zhruba 30.000 Kč.

            Možnosti plateb:    
            ↳ {BRAND_EMOJIS["kofi"]} Kofi | [Odkaz](https://ko-fi.com/valkyriahll)
            ↳ {BRAND_EMOJIS["paypal"]} Paypal | [Odkaz](https://www.paypal.com/paypalme/valkyriahll?country.x=CZ&locale.x=cs_CZ)
            ↳ {BRAND_EMOJIS["moneta"]} Moneta | [Odkaz](https://transparentniucty.moneta.cz/256862392)

            Děkujeme předem za jakýkoli finanční příspěvek!

            {BRAND_EMOJIS["valkyria"]} Valkyria
            """
        )
        embed.set_image(
            url="https://media.discordapp.net/attachments/1072205500806070312/1224092520686813386/qrkod.png?ex=6985a5bf&is=6984543f&hm=9e21e76bb9c7b1e8cfb941c5047c1853ab14a6fc89f172eee7bc67546af2e939&=&format=webp&quality=lossless&width=800&height=800"
        )
        try:
            guild_logo = interaction.guild.icon.url # type: ignore
        except:
            guild_logo = "https://cdn.discordapp.com/icons/963323629242826762/8391d3fa3283562da0afed0cab476241.webp?size=160&quality=lossless"

        embed.set_author(name="Valkyria", icon_url=guild_logo)
        await interaction.response.send_message(embed=embed, ephemeral=True)    
