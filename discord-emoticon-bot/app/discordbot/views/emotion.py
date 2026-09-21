"""감정 선택 패널.

Slash Command는 `--emotion` 같은 플래그 문법을 지원하지 않으므로,
`/e` 에서 검색어를 비우면 나오는 버튼 → 감정 Select 로 대체한다.
"""

from __future__ import annotations

import logging

import discord
from discord import ui

from app.db.base import session_scope
from app.discordbot.views.search import PanelEntry, SearchPanel
from app.emotion import service as emotion_service
from app.search import service as search_service

logger = logging.getLogger(__name__)


class EmotionRow(ui.ActionRow["EmotionPanel"]):
    def __init__(self, panel: "EmotionPanel", options: list[discord.SelectOption]) -> None:
        super().__init__()
        self.panel = panel
        self.pick.options = options

    @ui.select(placeholder="지금 감정을 고르세요", min_values=1, max_values=1)
    async def pick(self, interaction: discord.Interaction, select: ui.Select) -> None:
        tag = select.values[0]
        async with session_scope() as session:
            hits = await search_service.search(
                session, f"#{tag}", user_id=interaction.user.id
            )
            entries = [PanelEntry.from_emoticon(h.emoticon, h.reason) for h in hits]

        panel = SearchPanel(
            entries,
            title=f"#{tag} 추천",
            owner_id=interaction.user.id,
            footer="비슷한 감정 태그까지 함께 찾았습니다.",
        )
        await interaction.response.edit_message(view=panel, attachments=panel.files())


class EmotionPanel(ui.LayoutView):
    def __init__(self, options: list[discord.SelectOption], owner_id: int) -> None:
        super().__init__(timeout=180)
        self.owner_id = owner_id
        container = ui.Container(accent_colour=discord.Colour.blurple())
        container.add_item(ui.TextDisplay("### 지금 기분에 맞는 이모티콘 찾기"))
        container.add_item(EmotionRow(self, options))
        self.add_item(container)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.owner_id


async def build_emotion_panel(owner_id: int) -> EmotionPanel:
    async with session_scope() as session:
        emotions = await emotion_service.list_emotions(session, primary_only=True)
    options = [
        discord.SelectOption(label=e.label, value=e.tag, emoji=e.icon)
        for e in emotions[:25]
    ]
    if not options:
        options = [discord.SelectOption(label="등록된 감정이 없습니다", value="none")]
    return EmotionPanel(options, owner_id)
