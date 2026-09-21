"""감정 태그 조회/seed/유사도 확장."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Emotion, EmotionRelation
from app.emotion.tags import DEFAULT_EMOTIONS, DEFAULT_RELATIONS, normalize_tag

logger = logging.getLogger(__name__)


async def seed_emotions(session: AsyncSession) -> int:
    """기본 감정/관계를 멱등하게 입력한다. 추가된 감정 수를 반환."""
    existing = {e.tag: e for e in (await session.scalars(select(Emotion))).all()}
    added = 0
    for d in DEFAULT_EMOTIONS:
        if d.tag in existing:
            continue
        emotion = Emotion(
            tag=d.tag, label=d.label, icon=d.icon,
            is_primary=d.is_primary, sort_order=d.sort_order,
        )
        session.add(emotion)
        existing[d.tag] = emotion
        added += 1
    await session.flush()

    pairs = {
        (r.emotion_id, r.related_id)
        for r in (await session.scalars(select(EmotionRelation))).all()
    }
    for tag, relations in DEFAULT_RELATIONS.items():
        src = existing.get(tag)
        if src is None:
            continue
        for related_tag, weight in relations:
            dst = existing.get(related_tag)
            if dst is None:
                continue
            for a, b in ((src.id, dst.id), (dst.id, src.id)):  # 양방향
                if (a, b) not in pairs:
                    session.add(EmotionRelation(emotion_id=a, related_id=b, weight=weight))
                    pairs.add((a, b))
    await session.flush()
    logger.info("emotion seed done (+%d)", added)
    return added


async def get_by_tag(session: AsyncSession, tag: str) -> Emotion | None:
    return await session.scalar(select(Emotion).where(Emotion.tag == normalize_tag(tag)))


async def list_emotions(session: AsyncSession, primary_only: bool = False) -> list[Emotion]:
    stmt = select(Emotion).order_by(Emotion.sort_order, Emotion.tag)
    if primary_only:
        stmt = stmt.where(Emotion.is_primary.is_(True))
    return list((await session.scalars(stmt)).all())


async def expand_tags(session: AsyncSession, tag: str) -> dict[str, float]:
    """입력 태그 + 유사 감정 태그를 가중치와 함께 돌려준다.

    반환 예: {"무덤덤": 1.0, "귀찮음": 0.7, "체념": 0.7}
    """
    base = normalize_tag(tag)
    result: dict[str, float] = {base: 1.0}
    emotion = await get_by_tag(session, base)
    if emotion is None:
        return result

    rows = await session.execute(
        select(Emotion.tag, EmotionRelation.weight)
        .join(EmotionRelation, EmotionRelation.related_id == Emotion.id)
        .where(EmotionRelation.emotion_id == emotion.id)
    )
    for related_tag, weight in rows:
        result[related_tag] = max(result.get(related_tag, 0.0), float(weight))
    return result


async def ensure_tags(session: AsyncSession, tags: list[str]) -> list[Emotion]:
    """없는 태그는 새로 만들어서 Emotion 목록을 반환한다."""
    out: list[Emotion] = []
    for raw in tags:
        tag = normalize_tag(raw)
        if not tag:
            continue
        emotion = await get_by_tag(session, tag)
        if emotion is None:
            emotion = Emotion(tag=tag, label=tag, icon="🏷️", sort_order=500)
            session.add(emotion)
            await session.flush()
        if emotion not in out:
            out.append(emotion)
    return out
