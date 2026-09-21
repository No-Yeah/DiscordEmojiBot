"""Discord 계층 스모크 테스트 (게이트웨이 연결 없이 구성만 검증)."""

from __future__ import annotations

import discord

from app.discordbot.commands.emoticon import EmoticonCog
from app.discordbot.commands.search import SearchCog
from app.discordbot.emoji_sync import emoji_name_for
from app.discordbot.views.search import PanelEntry, SearchPanel


def _entries(n: int) -> list[PanelEntry]:
    return [
        PanelEntry(
            id=i,
            name=f"이모티콘{i}",
            tags="#황당 #체념",
            preview_path=f"preview/{i}.png",
            processed_path=f"processed/{i}.png",
        )
        for i in range(1, n + 1)
    ]


def test_panel_builds_valid_components_v2_payload():
    panel = SearchPanel(_entries(8), title="검색 결과: 아무튼", owner_id=1)
    payload = panel.to_components()
    assert payload[0]["type"] == 17  # Container
    kinds = [c["type"] for c in payload[0]["components"]]
    assert 10 in kinds and 12 in kinds and 1 in kinds  # Text, MediaGallery, ActionRow


def test_panel_paginates():
    panel = SearchPanel(_entries(20), title="t", owner_id=1)
    assert panel.page_size == 8
    assert panel.last_page == 2
    assert len(panel.current_page) == 8
    panel.page = 2
    assert len(panel.current_page) == 4


def test_panel_select_never_exceeds_discord_limits():
    panel = SearchPanel(_entries(40), title="t", owner_id=1)
    rows = [c for c in panel.to_components()[0]["components"] if c["type"] == 1]
    select = rows[0]["components"][0]
    assert len(select["options"]) <= 25
    gallery = [c for c in panel.to_components()[0]["components"] if c["type"] == 12][0]
    assert len(gallery["items"]) <= 10


def test_empty_panel_has_emotion_button():
    panel = SearchPanel([], title="t", owner_id=1, show_emotion_button=True)
    labels = [
        c.get("label")
        for row in panel.to_components()[0]["components"]
        if row["type"] == 1
        for c in row["components"]
    ]
    assert "감정으로 찾기" in labels


def test_emoji_name_follows_discord_rules():
    class Fake:
        id = 12
        name = "누룽이_anyway"

    name = emoji_name_for(Fake())
    assert name.isascii() and all(ch.isalnum() or ch == "_" for ch in name)
    assert 2 <= len(name) <= 32


def test_commands_are_user_installable_everywhere():
    bot = discord.Client(intents=discord.Intents.none())
    search_cmd = SearchCog(bot).__cog_app_commands__[0]
    installs = search_cmd.allowed_installs
    contexts = search_cmd.allowed_contexts
    assert installs.guild and installs.user
    assert contexts.guild and contexts.dm_channel and contexts.private_channel

    group = EmoticonCog(bot).__cog_app_commands__[0]
    assert {c.name for c in group.commands} >= {"add", "delete", "favorite", "preview"}
