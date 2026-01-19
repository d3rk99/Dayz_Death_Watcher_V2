from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import traceback
from typing import Optional

import discord

from .audit import AuditEvent, AuditLogger
from .config import ErrorReportingConfig


@dataclass
class ErrorState:
    last_sent_at: Optional[datetime] = None


class ErrorReporter:
    def __init__(self, config: ErrorReportingConfig, audit: AuditLogger) -> None:
        self.config = config
        self.audit = audit
        self.state = ErrorState()

    def _should_send(self) -> bool:
        if self.state.last_sent_at is None:
            return True
        delta = datetime.now(timezone.utc) - self.state.last_sent_at
        return delta.total_seconds() >= self.config.error_dump_rate_limit_seconds

    def _format_message(self, message: str, exc: Optional[BaseException]) -> str:
        mention = self.config.error_dump_mention_tag if self.config.error_dump_allow_mention else ""
        detail = ""
        if exc and self.config.error_dump_include_traceback:
            detail = f"\n```py\n{''.join(traceback.format_exception(exc)).strip()}\n```"
        return f"{mention} {message}{detail}".strip()

    async def report(self, bot: discord.Client, message: str, exc: Optional[BaseException] = None) -> None:
        self.audit.write(
            AuditEvent(
                event="error",
                message=message,
                context={"exception": repr(exc) if exc else None},
            )
        )
        if not self._should_send():
            return
        channel = bot.get_channel(self.config.error_dump_channel_id)
        if isinstance(channel, discord.TextChannel):
            await channel.send(self._format_message(message, exc))
            self.state.last_sent_at = datetime.now(timezone.utc)
