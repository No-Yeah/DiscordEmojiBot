"""`/emoticon ...` — Discord 안에서 쓰는 관리 명령.

전체 관리 기능(대량 등록, 이미지 고르기 등)은 관리자 Web UI에 있다.
여기에는 채팅 중에 바로 쓰는 최소 기능만 둔다. 변경 계열 명령은 앱 소유자만 쓸 수 있다.
"""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from app.crawler.fetcher import FetchError
from app.db.base import session_scope
from app.discordbot import emoji_sync
from app.emoticon import repository as repo
from app.emoticon import service as emoticon_service
from app.emoticon.service import DuplicateEmoticon, RegistrationError

logger = logging.getLogger(__name__)

PREVIEW_LIMIT = 10


def _split(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part.strip() for part in raw.replace(",", " ").split() if part.strip()]


class EmoticonCog(commands.Cog):
    group = app_commands.Group(
        name="emoticon",
        description="이모티콘 등록/관리",
        allowed_installs=app_commands.AppInstallationType(guild=True, user=True),
        allowed_contexts=app_commands.AppCommandContext(
            guild=True, dm_channel=True, private_channel=True
        ),
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _require_owner(self, interaction: discord.Interaction) -> bool:
        if await self.bot.is_owner(interaction.user):
            return True
        await interaction.followup.send(
            "이 명령은 앱 소유자만 사용할 수 있습니다.", ephemeral=True
        )
        return False

    @group.command(name="preview", description="URL에서 이모티콘 이미지 후보를 찾아봅니다")
    @app_commands.describe(url="이모티콘 페이지 또는 이미지 URL")
    async def preview(self, interaction: discord.Interaction, url: str) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        if not await self._require_owner(interaction):
            return
        try:
            result = await emoticon_service.extract_candidates(url)
        except (FetchError, RegistrationError) as exc:
            await interaction.followup.send(f"실패: {exc}", ephemeral=True)
            return

        shown = result.candidates[:PREVIEW_LIMIT]
        lines = "\n".join(f"`{i + 1}.` <{c.url}>" for i, c in enumerate(shown))
        embed = discord.Embed(
            title=f"후보 {len(result.candidates)}개 (parser: {result.parser})",
            description=f"{lines}\n\n`/emoticon add url:... index:N` 으로 등록하세요.",
            colour=discord.Colour.blurple(),
        )
        if shown:
            embed.set_image(url=shown[0].url)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @group.command(name="add", description="URL에서 이모티콘 하나를 등록합니다")
    @app_commands.describe(
        url="이모티콘 페이지 또는 이미지 URL",
        name="이모티콘 이름",
        index="preview에서 확인한 후보 번호 (기본 1)",
        emotions="감정 태그 (예: #황당 #체념)",
        keywords="검색 키워드 (공백 구분)",
    )
    async def add(
        self,
        interaction: discord.Interaction,
        url: str,
        name: str,
        index: app_commands.Range[int, 1, 60] = 1,
        emotions: str | None = None,
        keywords: str | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        if not await self._require_owner(interaction):
            return

        try:
            extracted = await emoticon_service.extract_candidates(url)
            if index > len(extracted.candidates):
                await interaction.followup.send(
                    f"후보가 {len(extracted.candidates)}개뿐입니다.", ephemeral=True
                )
                return
            candidate = extracted.candidates[index - 1]

            async with session_scope() as session:
                emoticon = await emoticon_service.register(
                    session,
                    name=name,
                    image_url=candidate.url,
                    source_url=extracted.source_url,
                    keywords=_split(keywords),
                    emotions=_split(emotions),
                )
                await emoji_sync.ensure_app_emoji(self.bot, session, emoticon)
                summary = (
                    f"**{emoticon.name}** 등록 완료 (#{emoticon.id})\n"
                    f"감정: {' '.join('#' + e.tag for e in emoticon.emotions) or '없음'}\n"
                    f"키워드: {' '.join(k.value for k in emoticon.keywords) or '없음'}"
                )
                preview = emoticon.preview_path
        except DuplicateEmoticon as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        except (FetchError, RegistrationError) as exc:
            await interaction.followup.send(f"등록 실패: {exc}", ephemeral=True)
            return

        from app.discordbot.views.search import _file_for

        file = _file_for(preview, "preview.png")
        await interaction.followup.send(
            content=summary,
            file=file if file else discord.utils.MISSING,
            ephemeral=True,
        )

    @group.command(name="tag", description="이모티콘의 이름/감정/키워드를 수정합니다")
    @app_commands.describe(
        name="수정할 이모티콘 이름",
        new_name="새 이름 (선택)",
        emotions="감정 태그 전체 교체 (예: #귀찮음 #피곤)",
        keywords="키워드 전체 교체",
    )
    async def tag(
        self,
        interaction: discord.Interaction,
        name: str,
        new_name: str | None = None,
        emotions: str | None = None,
        keywords: str | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        if not await self._require_owner(interaction):
            return

        async with session_scope() as session:
            emoticon = await repo.get_by_name(session, name)
            if emoticon is None:
                await interaction.followup.send(f"`{name}` 을 찾을 수 없습니다.", ephemeral=True)
                return
            try:
                await emoticon_service.update_metadata(
                    session,
                    emoticon,
                    name=new_name,
                    keywords=_split(keywords) if keywords is not None else None,
                    emotions=_split(emotions) if emotions is not None else None,
                )
            except RegistrationError as exc:
                await interaction.followup.send(str(exc), ephemeral=True)
                return
            message = (
                f"**{emoticon.name}** 수정 완료\n"
                f"감정: {' '.join('#' + e.tag for e in emoticon.emotions) or '없음'}\n"
                f"키워드: {' '.join(k.value for k in emoticon.keywords) or '없음'}"
            )
        await interaction.followup.send(message, ephemeral=True)

    @group.command(name="delete", description="이모티콘을 삭제합니다")
    @app_commands.describe(name="삭제할 이모티콘 이름")
    async def delete(self, interaction: discord.Interaction, name: str) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        if not await self._require_owner(interaction):
            return
        async with session_scope() as session:
            emoticon = await repo.get_by_name(session, name)
            if emoticon is None:
                await interaction.followup.send(f"`{name}` 을 찾을 수 없습니다.", ephemeral=True)
                return
            await emoji_sync.delete_app_emoji(self.bot, session, emoticon)
            await emoticon_service.delete(session, emoticon)
        await interaction.followup.send(f"`{name}` 삭제 완료.", ephemeral=True)

    @group.command(name="favorite", description="즐겨찾기를 켜고 끕니다")
    @app_commands.describe(name="이모티콘 이름")
    async def favorite(self, interaction: discord.Interaction, name: str) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with session_scope() as session:
            emoticon = await repo.get_by_name(session, name)
            if emoticon is None:
                await interaction.followup.send(f"`{name}` 을 찾을 수 없습니다.", ephemeral=True)
                return
            added = await repo.toggle_favorite(session, interaction.user.id, emoticon.id)
        await interaction.followup.send(
            f"`{name}` {'즐겨찾기에 추가했습니다.' if added else '즐겨찾기에서 뺐습니다.'}",
            ephemeral=True,
        )

    @group.command(name="stats", description="등록 현황을 봅니다")
    async def stats(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with session_scope() as session:
            total = await repo.count(session)
            recent = await repo.list_all(session, limit=5)
        lines = "\n".join(f"- {e.name}" for e in recent) or "없음"
        await interaction.followup.send(
            f"등록된 이모티콘: **{total}개**\n최근 등록:\n{lines}", ephemeral=True
        )

    @group.command(name="sync-emojis", description="앱 이모지 등록을 밀린 만큼 채웁니다")
    async def sync_emojis(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        if not await self._require_owner(interaction):
            return
        created = 0
        async with session_scope() as session:
            for emoticon in await repo.list_all(session, limit=500):
                if emoticon.app_emoji is None:
                    if await emoji_sync.ensure_app_emoji(self.bot, session, emoticon):
                        created += 1
        await interaction.followup.send(f"앱 이모지 {created}개 새로 등록했습니다.", ephemeral=True)

    @tag.autocomplete("name")
    @delete.autocomplete("name")
    @favorite.autocomplete("name")
    async def name_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        async with session_scope() as session:
            found = await repo.list_all(session, query=current or None, limit=25)
        return [app_commands.Choice(name=e.name, value=e.name) for e in found]
