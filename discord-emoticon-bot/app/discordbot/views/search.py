"""검색 결과 패널 (Discord Components V2).

레이아웃:
  Container
    ├─ TextDisplay  "검색 결과: 아무튼 (1/3)"
    ├─ MediaGallery [미리보기 8장]
    ├─ Separator
    ├─ ActionRow    [이모티콘 선택 Select]
    └─ ActionRow    [이전][다음][닫기]

패널 자체는 ephemeral(본인만 보임)이고, Select로 고른 이모티콘만 채널에 공개 전송된다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import discord
from discord import ui

from app.config import settings
from app.db.base import session_scope
from app.db.models import Emoticon
from app.emoticon import repository as repo
from app.storage.local import get_storage

logger = logging.getLogger(__name__)

MAX_SELECT_OPTIONS = 25


@dataclass(slots=True)
class PanelEntry:
    """세션이 닫힌 뒤에도 쓸 수 있도록 Emoticon을 평평하게 복사한 값."""

    id: int
    name: str
    tags: str
    preview_path: str | None
    processed_path: str
    emoji_id: int | None = None
    emoji_name: str | None = None
    emoji_animated: bool = False
    reason: str = ""

    @classmethod
    def from_emoticon(cls, emoticon: Emoticon, reason: str = "") -> "PanelEntry":
        mapping = emoticon.app_emoji
        return cls(
            id=emoticon.id,
            name=emoticon.name,
            tags=" ".join(f"#{e.tag}" for e in emoticon.emotions[:4]),
            preview_path=emoticon.preview_path,
            processed_path=emoticon.processed_path,
            emoji_id=mapping.emoji_id if mapping else None,
            emoji_name=mapping.emoji_name if mapping else None,
            emoji_animated=mapping.animated if mapping else False,
            reason=reason,
        )

    @property
    def partial_emoji(self) -> discord.PartialEmoji | None:
        if self.emoji_id is None or self.emoji_name is None:
            return None
        return discord.PartialEmoji(
            name=self.emoji_name, id=self.emoji_id, animated=self.emoji_animated
        )

    @property
    def mention(self) -> str | None:
        if self.emoji_id is None:
            return None
        prefix = "a" if self.emoji_animated else ""
        return f"<{prefix}:{self.emoji_name}:{self.emoji_id}>"


def _interaction_context(interaction: discord.Interaction) -> tuple[str, int | None]:
    if interaction.guild_id:
        return "guild", interaction.guild_id
    if interaction.channel and isinstance(interaction.channel, discord.GroupChannel):
        return "group_dm", None
    return "dm", None


def _file_for(path: str | None, filename: str) -> discord.File | None:
    if not path:
        return None
    storage = get_storage()
    try:
        return discord.File(storage.full_path(path), filename=filename)
    except (OSError, ValueError):
        logger.warning("미리보기 파일을 열 수 없습니다: %s", path)
        return None


async def send_emoticon(interaction: discord.Interaction, entry: PanelEntry) -> None:
    """고른 이모티콘을 채널(또는 DM)에 공개 메시지로 보낸다.

    Discord는 Bot이 '사용자 이름으로' 메시지를 보내는 것을 허용하지 않는다.
    따라서 앱 메시지로 전송되며, 클라이언트에는 '{사용자}가 /e 사용' 형태로 표시된다.
    """
    mention = entry.mention
    if settings.send_style == "emoji" and mention:
        await interaction.followup.send(content=mention, ephemeral=False)
    else:
        file = _file_for(entry.processed_path, f"{entry.name}.png")
        if file is None:
            await interaction.followup.send(
                content="이미지 파일을 찾을 수 없습니다.", ephemeral=True
            )
            return
        await interaction.followup.send(file=file, ephemeral=False)

    context, guild_id = _interaction_context(interaction)
    async with session_scope() as session:
        await repo.log_usage(
            session,
            emoticon_id=entry.id,
            user_id=interaction.user.id,
            guild_id=guild_id,
            context=context,
        )


class PickRow(ui.ActionRow["SearchPanel"]):
    def __init__(self, panel: "SearchPanel") -> None:
        super().__init__()
        self.panel = panel
        self.pick.options = [
            discord.SelectOption(
                label=entry.name[:100],
                value=str(entry.id),
                description=(entry.tags or entry.reason)[:100] or None,
                emoji=entry.partial_emoji,
            )
            for entry in panel.current_page
        ] or [discord.SelectOption(label="결과 없음", value="none")]
        self.pick.disabled = not panel.current_page

    @ui.select(placeholder="보낼 이모티콘을 고르세요", min_values=1, max_values=1)
    async def pick(self, interaction: discord.Interaction, select: ui.Select) -> None:
        value = select.values[0]
        if value == "none":
            await interaction.response.defer()
            return

        entry = next((e for e in self.panel.entries if str(e.id) == value), None)
        if entry is None:
            await interaction.response.send_message("이미 삭제된 이모티콘입니다.", ephemeral=True)
            return

        # 1) 내 패널을 '전송됨' 상태로 바꾸고 2) 채널에 공개 전송
        self.panel.mark_sent(entry)
        await interaction.response.edit_message(view=self.panel, attachments=[])
        await send_emoticon(interaction, entry)


class NavRow(ui.ActionRow["SearchPanel"]):
    def __init__(self, panel: "SearchPanel") -> None:
        super().__init__()
        self.panel = panel
        self.prev.disabled = panel.page <= 0
        self.next.disabled = panel.page >= panel.last_page
        if not panel.show_emotion_button:
            self.remove_item(self.emotion)

    @ui.button(label="이전", style=discord.ButtonStyle.secondary, emoji="◀")
    async def prev(self, interaction: discord.Interaction, _: ui.Button) -> None:
        await self.panel.go_to(interaction, self.panel.page - 1)

    @ui.button(label="다음", style=discord.ButtonStyle.secondary, emoji="▶")
    async def next(self, interaction: discord.Interaction, _: ui.Button) -> None:
        await self.panel.go_to(interaction, self.panel.page + 1)

    @ui.button(label="감정으로 찾기", style=discord.ButtonStyle.primary, emoji="😐")
    async def emotion(self, interaction: discord.Interaction, _: ui.Button) -> None:
        from app.discordbot.views.emotion import build_emotion_panel

        panel = await build_emotion_panel(interaction.user.id)
        await interaction.response.edit_message(view=panel, attachments=[])

    @ui.button(label="닫기", style=discord.ButtonStyle.danger, emoji="✖")
    async def close(self, interaction: discord.Interaction, _: ui.Button) -> None:
        self.panel.clear_items()
        container = ui.Container(ui.TextDisplay("검색을 닫았습니다."))
        self.panel.add_item(container)
        self.panel.stop()
        await interaction.response.edit_message(view=self.panel, attachments=[])


class SearchPanel(ui.LayoutView):
    def __init__(
        self,
        entries: list[PanelEntry],
        *,
        title: str,
        owner_id: int,
        page: int = 0,
        footer: str = "",
        show_emotion_button: bool = False,
    ) -> None:
        super().__init__(timeout=180)
        self.entries = entries
        self.title = title
        self.owner_id = owner_id
        self.footer = footer
        self.show_emotion_button = show_emotion_button
        self.page_size = max(1, min(settings.search_page_size, 10))
        self.page = page
        self.render()

    # --- 페이지 계산 ---
    @property
    def last_page(self) -> int:
        if not self.entries:
            return 0
        return (len(self.entries) - 1) // self.page_size

    @property
    def current_page(self) -> list[PanelEntry]:
        start = self.page * self.page_size
        return self.entries[start : start + self.page_size][:MAX_SELECT_OPTIONS]

    def files(self) -> list[discord.File]:
        out: list[discord.File] = []
        for entry in self.current_page:
            file = _file_for(entry.preview_path or entry.processed_path, f"{entry.id}.png")
            if file is not None:
                out.append(file)
        return out

    # --- 렌더링 ---
    def render(self) -> None:
        self.clear_items()
        container = ui.Container(accent_colour=discord.Colour.blurple())

        header = f"### {self.title}"
        if self.entries:
            header += f"  ·  {len(self.entries)}개 (페이지 {self.page + 1}/{self.last_page + 1})"
        container.add_item(ui.TextDisplay(header))

        page_entries = self.current_page
        if page_entries:
            items = [
                discord.MediaGalleryItem(
                    f"attachment://{entry.id}.png", description=entry.name
                )
                for entry in page_entries
            ]
            container.add_item(ui.MediaGallery(*items))
            listing = "\n".join(
                f"`{i + 1}.` **{e.name}** {e.tags}" for i, e in enumerate(page_entries)
            )
            container.add_item(ui.TextDisplay(listing))
        else:
            container.add_item(
                ui.TextDisplay("결과가 없습니다. 다른 이름이나 `#감정`으로 찾아보세요.")
            )

        container.add_item(ui.Separator())
        container.add_item(PickRow(self))
        container.add_item(NavRow(self))
        if self.footer:
            container.add_item(ui.TextDisplay(f"-# {self.footer}"))
        self.add_item(container)

    def mark_sent(self, entry: PanelEntry) -> None:
        self.clear_items()
        self.add_item(
            ui.Container(ui.TextDisplay(f"**{entry.name}** 을(를) 보냈습니다."))
        )
        self.stop()

    async def go_to(self, interaction: discord.Interaction, page: int) -> None:
        self.page = max(0, min(page, self.last_page))
        self.render()
        await interaction.response.edit_message(view=self, attachments=self.files())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "본인이 실행한 검색만 조작할 수 있습니다.", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self) -> None:  # pragma: no cover - 타이머 경로
        self.stop()
