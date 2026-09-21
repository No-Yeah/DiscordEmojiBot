"""Discord Bot 본체.

- Message Content 인텐트를 쓰지 않는다(Application Command만 사용).
- 커맨드는 User Install + Guild Install 양쪽을 지원하도록 등록한다.
"""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

from app.config import settings
from app.db.base import create_all, session_scope
from app.emotion.service import seed_emotions

logger = logging.getLogger(__name__)


class EmoticonBot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(
            command_prefix=commands.when_mentioned,  # 텍스트 커맨드는 사용하지 않음
            intents=discord.Intents.none(),
            help_command=None,
        )

    async def setup_hook(self) -> None:
        await create_all()
        async with session_scope() as session:
            await seed_emotions(session)

        from app.discordbot.commands.emoticon import EmoticonCog
        from app.discordbot.commands.search import SearchCog

        await self.add_cog(SearchCog(self))
        await self.add_cog(EmoticonCog(self))

        if settings.discord_dev_guild_id:
            guild = discord.Object(id=settings.discord_dev_guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            logger.info("synced %d commands to dev guild %s", len(synced), guild.id)
        else:
            synced = await self.tree.sync()
            logger.info("synced %d global commands (반영까지 최대 1시간)", len(synced))

    async def on_ready(self) -> None:
        logger.info("logged in as %s (id=%s)", self.user, getattr(self.user, "id", "?"))

    async def on_app_command_error(  # pragma: no cover - 런타임 경로
        self, interaction: discord.Interaction, error: Exception
    ) -> None:
        logger.exception("app command error", exc_info=error)


def run() -> None:
    if not settings.discord_bot_token:
        raise SystemExit("DISCORD_BOT_TOKEN이 설정되지 않았습니다. .env를 확인하세요.")
    EmoticonBot().run(settings.discord_bot_token, log_handler=None)
