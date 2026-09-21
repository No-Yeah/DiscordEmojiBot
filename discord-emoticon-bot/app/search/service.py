"""검색: 이름 / 키워드 / #감정 + 감정 유사도 + 최근 사용 가중치.

점수 규칙(높을수록 위):
  이름 완전일치 100 / 이름 시작일치 70 / 이름 부분일치 50
  감정 태그 일치 80 * 유사도(직접 입력=1.0)
  키워드 완전일치 60 / 부분일치 40
  최근 사용 보너스 최대 +12
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import Emoticon
from app.emoticon import repository as repo
from app.emotion import service as emotion_service
from app.emotion.tags import normalize_tag

logger = logging.getLogger(__name__)

NAME_EXACT, NAME_PREFIX, NAME_PARTIAL = 100.0, 70.0, 50.0
EMOTION_BASE = 80.0
KEYWORD_EXACT, KEYWORD_PARTIAL = 60.0, 40.0
MAX_RECENT_BONUS = 12.0


@dataclass(frozen=True, slots=True)
class SearchHit:
    emoticon: Emoticon
    score: float
    reason: str


@dataclass(frozen=True, slots=True)
class ParsedQuery:
    text: str | None
    tags: list[str]

    @property
    def is_empty(self) -> bool:
        return not self.text and not self.tags


def parse_query(raw: str | None) -> ParsedQuery:
    """'#황당 아무튼' -> tags=['황당'], text='아무튼'."""
    if not raw or not raw.strip():
        return ParsedQuery(text=None, tags=[])
    tags: list[str] = []
    words: list[str] = []
    for token in raw.split():
        if token.startswith("#") and len(token) > 1:
            tags.append(normalize_tag(token))
        else:
            words.append(token)
    return ParsedQuery(text=" ".join(words) or None, tags=tags)


def _score_one(
    emoticon: Emoticon, text: str | None, tag_weights: dict[str, float]
) -> tuple[float, str]:
    score = 0.0
    reasons: list[str] = []

    if text:
        lowered = text.lower()
        name = emoticon.name.lower()
        if name == lowered:
            score += NAME_EXACT
            reasons.append("이름 일치")
        elif name.startswith(lowered):
            score += NAME_PREFIX
            reasons.append("이름 시작")
        elif lowered in name:
            score += NAME_PARTIAL
            reasons.append("이름 포함")

        for keyword in emoticon.keywords:
            value = keyword.value.lower()
            if value == lowered:
                score += KEYWORD_EXACT
                reasons.append(f"키워드 {keyword.value}")
                break
            if lowered in value or value in lowered:
                score += KEYWORD_PARTIAL
                reasons.append(f"키워드 {keyword.value}")
                break

    if tag_weights:
        best_weight, best_tag = 0.0, None
        for emotion in emoticon.emotions:
            weight = tag_weights.get(emotion.tag, 0.0)
            if weight > best_weight:
                best_weight, best_tag = weight, emotion.tag
        if best_tag:
            score += EMOTION_BASE * best_weight
            reasons.append(f"#{best_tag}" + ("" if best_weight >= 1.0 else " (유사)"))

    return score, ", ".join(reasons)


async def search(
    session: AsyncSession,
    raw_query: str | None,
    *,
    user_id: int | None = None,
    limit: int | None = None,
) -> list[SearchHit]:
    parsed = parse_query(raw_query)
    limit = limit or settings.search_max_results

    if parsed.is_empty:
        return []

    # #감정 검색이면 유사 감정까지 확장
    tag_weights: dict[str, float] = {}
    for tag in parsed.tags:
        for related, weight in (await emotion_service.expand_tags(session, tag)).items():
            tag_weights[related] = max(tag_weights.get(related, 0.0), weight)

    # 일반 단어도 감정 태그일 수 있다(예: /e 귀찮음)
    if parsed.text and not parsed.tags:
        if await emotion_service.get_by_tag(session, parsed.text):
            for related, weight in (
                await emotion_service.expand_tags(session, parsed.text)
            ).items():
                tag_weights[related] = max(tag_weights.get(related, 0.0), weight)

    candidates = await repo.search_candidates(
        session,
        text=parsed.text,
        tags=list(tag_weights),
        limit=max(limit * 5, 100),
    )

    recent = await repo.usage_scores(session, user_id) if user_id else {}
    max_used = max(recent.values(), default=0)

    hits: list[SearchHit] = []
    for emoticon in candidates:
        score, reason = _score_one(emoticon, parsed.text, tag_weights)
        if score <= 0:
            continue
        if max_used:
            score += MAX_RECENT_BONUS * (recent.get(emoticon.id, 0) / max_used)
        hits.append(SearchHit(emoticon=emoticon, score=score, reason=reason))

    hits.sort(key=lambda h: (-h.score, h.emoticon.name))
    return hits[:limit]


async def suggest(
    session: AsyncSession, raw_query: str | None, *, limit: int = 25
) -> list[str]:
    """Slash Command Autocomplete용 문자열 목록."""
    parsed = parse_query(raw_query)

    if parsed.is_empty:
        emotions = await emotion_service.list_emotions(session, primary_only=True)
        recent = await repo.list_all(session, limit=limit)
        return [f"#{e.tag}" for e in emotions][:10] + [e.name for e in recent][:15]

    if raw_query and raw_query.strip().startswith("#"):
        typed = normalize_tag(raw_query)
        emotions = await emotion_service.list_emotions(session)
        return [f"#{e.tag}" for e in emotions if typed in e.tag][:limit]

    hits = await search(session, raw_query, limit=limit)
    return [hit.emoticon.name for hit in hits]
