from __future__ import annotations

from pathlib import Path

from .bot_app import DeathWatcherBot


def main() -> None:
    bot = DeathWatcherBot(Path("config.json"))
    bot.run(bot.config.discord.token)


if __name__ == "__main__":
    main()
