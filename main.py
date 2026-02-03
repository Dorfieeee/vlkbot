"""Entry point for the VIP Discord bot."""
import discord
from discord.ext import commands
import asyncio
import signal
import logging

from api_client import get_api_client
from bot import get_bot, get_token


handler = logging.FileHandler(filename="discord.log", encoding="UTF-8", mode="w")

async def shutdown_handler(bot: commands.Bot):
    await bot.dispatch('shutdown')
    await bot.close()

async def main() -> None:
    api_client = get_api_client()
    token = get_token()
    bot = get_bot()
    
    discord.utils.setup_logging(
        handler=handler,
        level=logging.DEBUG,
    )

    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGINT, lambda: asyncio.create_task(shutdown_handler(bot)))

    try:
        await bot.start(token)
    except KeyboardInterrupt:
        pass  # Handled by signal
    finally:
        await api_client.close()


if __name__ == "__main__":
    asyncio.run(main())
