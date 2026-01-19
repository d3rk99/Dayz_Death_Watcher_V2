from __future__ import annotations

import asyncio
import signal
from pathlib import Path

from .bot_app import DeathWatcherBot


def _build_signal_list() -> list[signal.Signals]:
    signals: list[signal.Signals] = [signal.SIGINT, signal.SIGTERM]
    if hasattr(signal, "SIGBREAK"):
        signals.append(signal.SIGBREAK)
    return signals


async def _run_bot() -> None:
    bot = DeathWatcherBot(Path("config.json"))
    loop = asyncio.get_running_loop()

    async def shutdown() -> None:
        if bot.is_closed():
            return
        await bot.close()

    def handle_signal() -> None:
        asyncio.create_task(shutdown())

    for sig in _build_signal_list():
        try:
            loop.add_signal_handler(sig, handle_signal)
        except NotImplementedError:
            signal.signal(sig, lambda *_: asyncio.create_task(shutdown()))

    try:
        await bot.start(bot.config.discord.token)
    finally:
        await shutdown()


def main() -> None:
    asyncio.run(_run_bot())


if __name__ == "__main__":
    main()
