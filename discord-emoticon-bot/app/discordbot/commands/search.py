"""`/e` — 이모티콘 검색/선택/전송.

설치 컨텍스트:
  allowed_installs(guilds=True, users=True)  → 서버 설치 + 사용자 설치 모두 허용
  allowed_contexts(guilds, dms, private_channels) → 서버 채널 / 봇 DM / 일반 DM·그룹 DM
사용자 설치로 추가하면 개인 DM과 그룹 DM에서도 `/e`를 쓸 수 있다.
"""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from app.db.base import session_scope
from app.discordbot.views.search import PanelEntry, SearchPanel
from app.emoticon import repository as repo
from app.search import service as search_service

logger = logging.getLogger(__name__)

class SearchCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="e", description="이모티콘을 검색해서 채팅에 보냅니다")
    @app_commands.rename(query="검색어")
    @app_commands.describe(query="이모티콘 이름, 키워드 또는 #감정 (비우면 최근 사용)")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def e(self, interaction: discord.Interaction, query: str | None = None) -> None:
        # 패널은 본인만 보이게(ephemeral). 고른 것만 채널에 공개된다.
        await interaction.response.defer(ephemeral=True, thinking=True)

        async with session_scope() as session:
            if query:
                hits = await search_service.search(
                    session, query, user_id=interaction.user.id
                )
                entries = [PanelEntry.from_emoticon(h.emoticon, h.reason) for h in hits]
                title = f"검색 결과: {query}"
                footer = "" if entries else "`/e #감정` 으로도 찾을 수 있어요."
                show_emotion = not entries
            else:
                recent = await repo.recent_for_user(session, interaction.user.id, limit=16)
                favorites = await repo.favorites_for_user(session, interaction.user.id, 8)
                merged: dict[int, PanelEntry] = {}
                for emoticon in [*favorites, *recent]:
                    merged.setdefault(
                        emoticon.id, PanelEntry.from_emoticon(emoticon, "최근/즐겨찾기")
                    )
                if not merged:
                    for emoticon in await repo.list_all(session, limit=16):
                        merged[emoticon.id] = PanelEntry.from_emoticon(emoticon, "최근 등록")
                entries = list(merged.values())
                title = "최근 사용 · 즐겨찾기"
                footer = "검색어를 입력하거나 감정 버튼을 눌러보세요."
                show_emotion = True

        panel = SearchPanel(
            entries,
            title=title,
            owner_id=interaction.user.id,
            footer=footer,
            show_emotion_button=show_emotion,
        )
        await interaction.followup.send(
            view=panel, files=panel.files(), ephemeral=True
        )

    # rename("검색어") 이후에도 연결은 파이썬 파라미터 이름(query)으로 한다.
    @e.autocomplete("query")
    async def e_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        try:
            async with session_scope() as session:
                values = await search_service.suggest(session, current, limit=25)
        except Exception:  # pragma: no cover - 자동완성 실패는 조용히 무시
            logger.exception("autocomplete failed")
            return []
        return [app_commands.Choice(name=v[:100], value=v[:100]) for v in values[:25]]
