"""e.kakao.com 이모티콘 상세 페이지 파서.

카카오 페이지는 CSR이라 HTML 태그 구조가 자주 바뀐다. 그래서 DOM 구조 대신
페이지에 인라인으로 박혀 있는 CDN URL을 정규식으로 긁는 방식을 쓴다.
구조가 바뀌면 이 파일의 패턴만 고치면 된다.

주의: 카카오 이모티콘은 저작권이 있는 콘텐츠다. 개인적인 사용 범위를 넘어서
재배포/공유하지 않도록 한다.
"""

from __future__ import annotations

import html
import logging
import re

from app.crawler.base import ImageCandidate, dedupe, host_of

logger = logging.getLogger(__name__)

# item.kakaocdn.net / dn.kakaocdn.net 에 올라간 이모티콘 이미지
CDN_RE = re.compile(
    r"https?://[\w.-]*kakaocdn\.net/[^\s\"'\\<>)]+?\.(?:png|webp|gif|jpg|jpeg)",
    re.IGNORECASE,
)
OG_IMAGE_RE = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)

# 상세 페이지에는 배너/프로필 같은 비-이모티콘 이미지도 섞여 있다.
# 파일명 접두어로만 판단한다("emoticon_01.png"이 "icon_"에 걸리면 안 된다).
NOISE_PREFIXES = ("profile", "banner", "logo", "sprite", "icon_", "bg_", "badge", "ico_")


def _is_noise(url: str) -> bool:
    filename = url.split("?")[0].rsplit("/", 1)[-1].lower()
    return filename.startswith(NOISE_PREFIXES)


class KakaoEmoticonParser:
    name = "kakao"

    def matches(self, url: str) -> bool:
        host = host_of(url)
        return host.endswith("kakao.com") or host.endswith("kakaocdn.net")

    def extract(self, page: str, base_url: str) -> list[ImageCandidate]:
        title = None
        if m := TITLE_RE.search(page):
            title = html.unescape(m.group(1)).strip() or None

        raw = [html.unescape(u) for u in CDN_RE.findall(page)]
        urls = [u for u in raw if not _is_noise(u)]

        if not urls:
            urls = [html.unescape(u) for u in OG_IMAGE_RE.findall(page)]
            if urls:
                logger.info("kakao parser fell back to og:image (%s)", base_url)

        candidates = [ImageCandidate(url=u, title=title) for u in urls]
        return dedupe(candidates)
