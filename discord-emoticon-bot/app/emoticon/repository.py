"""이모티콘 DB 접근. 비즈니스 로직은 service.py에 둔다."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Emoticon,
    Emotion,
    Favorite,
    Keyword,
    UsageLog,
    emoticon_emotions,
    emoticon_keywords,
)


async def get(session: AsyncSession, emoticon_id: int) -> Emoticon | None:
    return await session.get(Emoticon, emoticon_id)


async def get_by_name(session: AsyncSession, name: str) -> Emoticon | None:
    return await session.scalar(select(Emoticon).where(Emoticon.name == name))


async def find_duplicate(
    session: AsyncSession, *, source_url: str | None, sha256: str, dhash: str
) -> Emoticon | None:
    """URL / 바이트 / 시각적 해시 중 하나라도 겹치면 중복으로 본다."""
    conditions = [Emoticon.image_sha256 == sha256, Emoticon.image_dhash == dhash]
    if source_url:
        conditions.append(Emoticon.source_url == source_url)
    stmt = select(Emoticon).where(func.coalesce(Emoticon.is_active, True).is_(True))
    for cond in conditions:
        found = await session.scalar(stmt.where(cond).limit(1))
        if found is not None:
            return found
    return None


async def add(session: AsyncSession, emoticon: Emoticon) -> Emoticon:
    session.add(emoticon)
    await session.flush()
    return emoticon


async def remove(session: AsyncSession, emoticon: Emoticon) -> None:
    await session.delete(emoticon)


async def list_all(
    session: AsyncSession, *, query: str | None = None, limit: int = 100, offset: int = 0
) -> list[Emoticon]:
    stmt = select(Emoticon).where(Emoticon.is_active.is_(True))
    if query:
        stmt = stmt.where(Emoticon.name.ilike(f"%{query}%"))
    stmt = stmt.order_by(Emoticon.created_at.desc()).limit(limit).offset(offset)
    return list((await session.scalars(stmt)).all())


async def count(session: AsyncSession) -> int:
    return int(await session.scalar(select(func.count(Emoticon.id))) or 0)


async def ensure_keywords(session: AsyncSession, values: list[str]) -> list[Keyword]:
    out: list[Keyword] = []
    for raw in values:
        value = raw.strip().lstrip("#").strip()
        if not value:
            continue
        keyword = await session.scalar(select(Keyword).where(Keyword.value == value))
        if keyword is None:
            keyword = Keyword(value=value)
            session.add(keyword)
            await session.flush()
        if keyword not in out:
            out.append(keyword)
    return out


async def search_candidates(
    session: AsyncSession, *, text: str | None, tags: list[str], limit: int
) -> list[Emoticon]:
    """이름/키워드/감정 중 하나라도 걸리는 후보를 넉넉히 가져온다.

    ponytail: 개인용(수천 건) 규모라 후보를 가져와 파이썬에서 점수를 매긴다.
    수만 건을 넘어가면 FTS5(SQLite) 또는 PostgreSQL tsvector로 올린다.
    """
    stmt = select(Emoticon).where(Emoticon.is_active.is_(True))
    conditions = []

    if text:
        pattern = f"%{text}%"
        conditions.append(Emoticon.name.ilike(pattern))
        conditions.append(
            Emoticon.id.in_(
                select(emoticon_keywords.c.emoticon_id)
                .join(Keyword, Keyword.id == emoticon_keywords.c.keyword_id)
                .where(Keyword.value.ilike(pattern))
            )
        )
        conditions.append(
            Emoticon.id.in_(
                select(emoticon_emotions.c.emoticon_id)
                .join(Emotion, Emotion.id == emoticon_emotions.c.emotion_id)
                .where(Emotion.tag.ilike(pattern))
            )
        )
    if tags:
        conditions.append(
            Emoticon.id.in_(
                select(emoticon_emotions.c.emoticon_id)
                .join(Emotion, Emotion.id == emoticon_emotions.c.emotion_id)
                .where(Emotion.tag.in_(tags))
            )
        )

    if conditions:
        from sqlalchemy import or_

        stmt = stmt.where(or_(*conditions))
    stmt = stmt.limit(limit)
    return list((await session.scalars(stmt)).all())


async def recent_for_user(
    session: AsyncSession, user_id: int, limit: int = 8
) -> list[Emoticon]:
    sub = (
        select(UsageLog.emoticon_id, func.max(UsageLog.used_at).label("last_used"))
        .where(UsageLog.user_id == user_id)
        .group_by(UsageLog.emoticon_id)
        .subquery()
    )
    stmt = (
        select(Emoticon)
        .join(sub, sub.c.emoticon_id == Emoticon.id)
        .where(Emoticon.is_active.is_(True))
        .order_by(sub.c.last_used.desc())
        .limit(limit)
    )
    return list((await session.scalars(stmt)).all())


async def favorites_for_user(
    session: AsyncSession, user_id: int, limit: int = 8
) -> list[Emoticon]:
    stmt = (
        select(Emoticon)
        .join(Favorite, Favorite.emoticon_id == Emoticon.id)
        .where(Favorite.user_id == user_id, Emoticon.is_active.is_(True))
        .order_by(Favorite.created_at.desc())
        .limit(limit)
    )
    return list((await session.scalars(stmt)).all())


async def toggle_favorite(session: AsyncSession, user_id: int, emoticon_id: int) -> bool:
    """즐겨찾기 상태를 뒤집고, 최종 상태(True=등록됨)를 반환."""
    existing = await session.scalar(
        select(Favorite).where(
            Favorite.user_id == user_id, Favorite.emoticon_id == emoticon_id
        )
    )
    if existing is not None:
        await session.delete(existing)
        return False
    session.add(Favorite(user_id=user_id, emoticon_id=emoticon_id))
    return True


async def log_usage(
    session: AsyncSession,
    *,
    emoticon_id: int,
    user_id: int,
    guild_id: int | None,
    context: str,
) -> None:
    session.add(
        UsageLog(
            emoticon_id=emoticon_id, user_id=user_id, guild_id=guild_id, context=context
        )
    )


async def usage_scores(
    session: AsyncSession, user_id: int, days: int = 30
) -> dict[int, int]:
    """최근 N일 사용 횟수(정렬 보너스용)."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = await session.execute(
        select(UsageLog.emoticon_id, func.count(UsageLog.id))
        .where(UsageLog.user_id == user_id, UsageLog.used_at >= since)
        .group_by(UsageLog.emoticon_id)
    )
    return {int(eid): int(cnt) for eid, cnt in rows}


async def purge_usage(session: AsyncSession, emoticon_id: int) -> None:
    await session.execute(delete(UsageLog).where(UsageLog.emoticon_id == emoticon_id))
