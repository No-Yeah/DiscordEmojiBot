"""이모티콘 등록/수정/삭제 비즈니스 로직.

URL 입력 -> 페이지 분석 -> 이미지 추출 -> 다운로드 -> 검증 -> PNG 정규화
-> 중복 검사 -> 저장 -> 메타데이터 등록
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.crawler.base import ImageCandidate, get_parser, host_of
from app.crawler.fetcher import FetchError, fetch
from app.db.models import Emoticon
from app.emoticon import repository as repo
from app.emotion import service as emotion_service
from app.image.processor import ProcessedImage, process
from app.image.validator import ImageValidationError
from app.storage.local import get_storage

logger = logging.getLogger(__name__)

_SAFE_NAME_RE = re.compile(r"[^\w가-힣ㄱ-ㅎㅏ-ㅣ._-]+")


class RegistrationError(RuntimeError):
    pass


class DuplicateEmoticon(RegistrationError):
    def __init__(self, existing: Emoticon) -> None:
        super().__init__(f"이미 등록된 이모티콘입니다: {existing.name} (#{existing.id})")
        self.existing = existing


@dataclass(frozen=True, slots=True)
class ExtractResult:
    source_url: str
    parser: str
    candidates: list[ImageCandidate]


def normalize_name(raw: str) -> str:
    name = _SAFE_NAME_RE.sub("_", raw.strip()).strip("_")
    return (name or "emoticon")[:100]


async def extract_candidates(url: str) -> ExtractResult:
    """URL을 열어 이모티콘 이미지 후보 목록을 만든다."""
    result = await fetch(url)

    if result.is_image:
        return ExtractResult(
            source_url=result.url,
            parser="direct",
            candidates=[ImageCandidate(url=result.url)],
        )

    try:
        page = result.content.decode("utf-8", errors="replace")
    except Exception as exc:  # pragma: no cover - 방어적
        raise RegistrationError(f"페이지를 읽을 수 없습니다: {exc}") from exc

    parser = get_parser(result.url)
    candidates = parser.extract(page, result.url)
    if not candidates:
        raise RegistrationError(
            "이 페이지에서 이모티콘 이미지를 찾지 못했습니다. 이미지 URL을 직접 입력해 보세요."
        )
    logger.info("extracted %d candidates from %s (%s)", len(candidates), result.url, parser.name)
    return ExtractResult(source_url=result.url, parser=parser.name, candidates=candidates)


async def download_and_process(image_url: str) -> ProcessedImage:
    try:
        result = await fetch(image_url)
        return process(result.content)
    except (FetchError, ImageValidationError) as exc:
        raise RegistrationError(str(exc)) from exc


async def register(
    session: AsyncSession,
    *,
    name: str,
    image_url: str,
    source_url: str | None = None,
    keywords: list[str] | None = None,
    emotions: list[str] | None = None,
    keep_original: bool = True,
    allow_duplicate: bool = False,
) -> Emoticon:
    """이미지 URL 하나를 이모티콘으로 등록한다."""
    processed = await download_and_process(image_url)

    duplicate = await repo.find_duplicate(
        session,
        source_url=source_url,
        sha256=processed.sha256,
        dhash=processed.dhash,
    )
    if duplicate is not None and not allow_duplicate:
        raise DuplicateEmoticon(duplicate)

    base_name = normalize_name(name)
    final_name = base_name
    suffix = 2
    while await repo.get_by_name(session, final_name) is not None:
        final_name = f"{base_name}_{suffix}"
        suffix += 1

    storage = get_storage()
    processed_path = storage.save(
        f"processed/{processed.sha256[:2]}/{processed.sha256}.png", processed.png
    )
    preview_path = storage.save(
        f"preview/{processed.sha256[:2]}/{processed.sha256}.png", processed.emoji_png
    )
    original_path = None
    if keep_original:
        original = await fetch(image_url)
        original_path = storage.save(
            f"original/{processed.sha256[:2]}/{processed.sha256}.bin", original.content
        )

    # 관계 객체를 먼저 확보한 뒤 생성자에 넘긴다.
    # (persistent 객체에 나중에 대입하면 컬렉션 lazy-load가 걸린다)
    keyword_rows = await repo.ensure_keywords(session, keywords or [])
    emotion_rows = await emotion_service.ensure_tags(session, emotions or [])

    emoticon = Emoticon(
        name=final_name,
        source_url=source_url or image_url,
        image_url=image_url,
        source_site=host_of(source_url or image_url),
        original_path=original_path,
        processed_path=processed_path,
        preview_path=preview_path,
        width=processed.width,
        height=processed.height,
        image_sha256=processed.sha256,
        image_dhash=processed.dhash,
        keywords=keyword_rows,
        emotions=emotion_rows,
    )
    await repo.add(session, emoticon)
    logger.info("registered emoticon #%s %s", emoticon.id, emoticon.name)
    return emoticon


async def update_metadata(
    session: AsyncSession,
    emoticon: Emoticon,
    *,
    name: str | None = None,
    keywords: list[str] | None = None,
    emotions: list[str] | None = None,
) -> Emoticon:
    if name:
        new_name = normalize_name(name)
        existing = await repo.get_by_name(session, new_name)
        if existing is not None and existing.id != emoticon.id:
            raise RegistrationError(f"이미 같은 이름이 있습니다: {new_name}")
        emoticon.name = new_name
    if keywords is not None:
        emoticon.keywords = await repo.ensure_keywords(session, keywords)
    if emotions is not None:
        emoticon.emotions = await emotion_service.ensure_tags(session, emotions)
    await session.flush()
    return emoticon


async def delete(session: AsyncSession, emoticon: Emoticon, *, remove_files: bool = True) -> None:
    storage = get_storage()
    paths = [emoticon.processed_path, emoticon.original_path]
    await repo.remove(session, emoticon)
    await session.flush()
    if remove_files:
        for path in paths:
            if path:
                storage.delete(path)
