from __future__ import annotations

import asyncio
from pathlib import Path

from .bot_app import DeathWatcherBot


async def main() -> None:
    bot = DeathWatcherBot(Path("config.json"))

    async def background_tasks() -> None:
        await bot.wait_until_ready()
        while not bot.is_closed():
            await bot.poll_logs()
            await bot.process_timers()
            await asyncio.sleep(2)

    bot.loop.create_task(background_tasks())
    await bot.start(bot.config.discord.token)


if __name__ == "__main__":
    asyncio.run(main())
