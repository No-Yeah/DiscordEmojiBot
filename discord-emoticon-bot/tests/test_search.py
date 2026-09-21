from __future__ import annotations

import pytest

from app.db.models import Emoticon
from app.emoticon import repository as repo
from app.emoticon import service as emoticon_service
from app.emotion import service as emotion_service
from app.search.service import parse_query, search



async def _add(session, name, *, emotions=(), keywords=(), sha=None):
    emoticon = Emoticon(
        name=name,
        source_url=f"https://example.com/{name}",
        processed_path=f"processed/{name}.png",
        preview_path=f"preview/{name}.png",
        width=512,
        height=512,
        image_sha256=(sha or name).ljust(64, "0"),
        image_dhash=f"{abs(hash(name)) % (16**16):016x}",
    )
    emoticon.emotions = await emotion_service.ensure_tags(session, list(emotions))
    emoticon.keywords = await repo.ensure_keywords(session, list(keywords))
    session.add(emoticon)
    await session.flush()
    return emoticon


def test_parse_query_splits_tags_and_text():
    parsed = parse_query("#황당 아무튼")
    assert parsed.tags == ["황당"]
    assert parsed.text == "아무튼"
    assert parse_query("  ").is_empty


async def test_seed_is_idempotent(session):
    first = await emotion_service.seed_emotions(session)
    second = await emotion_service.seed_emotions(session)
    assert first > 0
    assert second == 0


async def test_expand_tags_includes_similar_emotions(session):
    await emotion_service.seed_emotions(session)
    weights = await emotion_service.expand_tags(session, "#무덤덤")
    assert weights["무덤덤"] == 1.0
    assert weights["귀찮음"] == pytest.approx(0.7)


async def test_exact_name_ranks_above_partial(session):
    await emotion_service.seed_emotions(session)
    await _add(session, "아무튼", emotions=["황당"])
    await _add(session, "아무튼_그래", emotions=["황당"])

    hits = await search(session, "아무튼")
    assert [h.emoticon.name for h in hits][0] == "아무튼"
    assert len(hits) == 2


async def test_emotion_search_includes_similar_tags_with_lower_score(session):
    await emotion_service.seed_emotions(session)
    await _add(session, "무표정이", emotions=["무덤덤"])
    await _add(session, "귀찮이", emotions=["귀찮음"])

    hits = await search(session, "#무덤덤")
    names = [h.emoticon.name for h in hits]
    assert names == ["무표정이", "귀찮이"]  # 유사 감정은 뒤로
    assert hits[0].score > hits[1].score


async def test_keyword_search(session):
    await emotion_service.seed_emotions(session)
    await _add(session, "누룽이1", keywords=["피곤", "누룽이"])
    hits = await search(session, "피곤")
    assert hits and hits[0].emoticon.name == "누룽이1"


async def test_recent_usage_boosts_ranking(session):
    await emotion_service.seed_emotions(session)
    a = await _add(session, "아무튼_A", emotions=["황당"])
    b = await _add(session, "아무튼_B", emotions=["황당"])
    for _ in range(3):
        await repo.log_usage(
            session, emoticon_id=b.id, user_id=1, guild_id=None, context="dm"
        )
    await session.flush()

    hits = await search(session, "#황당", user_id=1)
    assert hits[0].emoticon.name == "아무튼_B"
    assert a.id in {h.emoticon.id for h in hits}


async def test_duplicate_detection_by_hash(session):
    existing = await _add(session, "중복테스트", sha="deadbeef")
    found = await repo.find_duplicate(
        session,
        source_url="https://other.example/x",
        sha256=existing.image_sha256,
        dhash="0000000000000000",
    )
    assert found is not None and found.id == existing.id


async def test_duplicate_detection_by_source_url(session):
    existing = await _add(session, "중복URL")
    found = await repo.find_duplicate(
        session,
        source_url=existing.source_url,
        sha256="x" * 64,
        dhash="ffffffffffffffff",
    )
    assert found is not None and found.id == existing.id


async def test_favorites_toggle(session):
    emoticon = await _add(session, "즐겨찾기용")
    assert await repo.toggle_favorite(session, 7, emoticon.id) is True
    await session.flush()
    assert [e.name for e in await repo.favorites_for_user(session, 7)] == ["즐겨찾기용"]
    assert await repo.toggle_favorite(session, 7, emoticon.id) is False
    await session.flush()
    assert await repo.favorites_for_user(session, 7) == []


async def test_name_collision_is_suffixed(session, monkeypatch):
    from app.image.processor import ProcessedImage
    from tests.conftest import make_png

    processed = ProcessedImage(
        png=make_png(), emoji_png=make_png(), width=512, height=512,
        sha256="a" * 64, dhash="1111111111111111", source_format="PNG",
    )

    async def fake_process(_url: str) -> ProcessedImage:
        return processed

    monkeypatch.setattr(emoticon_service, "download_and_process", fake_process)
    await _add(session, "겹치는이름")

    created = await emoticon_service.register(
        session,
        name="겹치는이름",
        image_url="https://example.com/a.png",
        keep_original=False,
        allow_duplicate=True,
    )
    assert created.name == "겹치는이름_2"


async def test_register_rejects_duplicate(session, monkeypatch):
    from app.image.processor import ProcessedImage
    from tests.conftest import make_png

    processed = ProcessedImage(
        png=make_png(), emoji_png=make_png(), width=512, height=512,
        sha256="b" * 64, dhash="2222222222222222", source_format="PNG",
    )
    monkeypatch.setattr(
        emoticon_service, "download_and_process", lambda _u: _coro(processed)
    )
    await _add(session, "이미있음", sha="b" * 64)

    with pytest.raises(emoticon_service.DuplicateEmoticon):
        await emoticon_service.register(
            session, name="새이름", image_url="https://example.com/b.png",
            keep_original=False,
        )


async def _coro(value):
    return value
