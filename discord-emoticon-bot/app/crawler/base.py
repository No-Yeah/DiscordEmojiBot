"""URL -> 이모티콘 이미지 후보 추출기(Adapter).

사이트 구조가 바뀌면 해당 Parser 파일 하나만 고치면 되도록 분리한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from urllib.parse import urljoin, urlsplit

IMAGE_EXT_RE = re.compile(r"\.(png|jpe?g|webp|gif)(\?|$)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ImageCandidate:
    url: str
    title: str | None = None


@runtime_checkable
class EmoticonParser(Protocol):
    name: str

    def matches(self, url: str) -> bool: ...

    def extract(self, html: str, base_url: str) -> list[ImageCandidate]: ...


def absolutize(base_url: str, url: str) -> str:
    return urljoin(base_url, url.strip().replace("&amp;", "&"))


def looks_like_image(url: str) -> bool:
    return bool(IMAGE_EXT_RE.search(url)) or "kakaocdn.net" in url


def dedupe(candidates: list[ImageCandidate], limit: int = 60) -> list[ImageCandidate]:
    seen: set[str] = set()
    out: list[ImageCandidate] = []
    for c in candidates:
        key = c.url.split("?")[0]
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
        if len(out) >= limit:
            break
    return out


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def get_parser(url: str) -> EmoticonParser:
    """등록 순서대로 첫 번째로 매칭되는 파서를 반환(마지막은 항상 Generic)."""
    from app.crawler.generic import GenericImageParser
    from app.crawler.kakao import KakaoEmoticonParser

    parsers: list[EmoticonParser] = [KakaoEmoticonParser(), GenericImageParser()]
    for parser in parsers:
        if parser.matches(url):
            return parser
    return GenericImageParser()
