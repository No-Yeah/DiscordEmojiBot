"""임의 웹페이지에서 이미지 후보를 뽑는 기본 파서.

og:image / twitter:image / <img src|data-src> 순으로 수집한다.
HTML 파서 의존성을 늘리지 않으려고 정규식을 쓴다.
(ponytail: 여기서 필요한 건 'src 속성 수집'뿐이라 파서 트리가 필요 없다.)
"""

from __future__ import annotations

import html
import re

from app.crawler.base import ImageCandidate, absolutize, dedupe, looks_like_image

META_RE = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](?:og:image(?::url)?|twitter:image)["\']'
    r'[^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
IMG_RE = re.compile(
    r'<img[^>]+(?:data-src|data-original|src)=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
SRCSET_RE = re.compile(r'srcset=["\']([^"\']+)["\']', re.IGNORECASE)
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


class GenericImageParser:
    name = "generic"

    def matches(self, url: str) -> bool:  # 항상 폴백으로 동작
        return True

    def extract(self, page: str, base_url: str) -> list[ImageCandidate]:
        title = None
        if m := TITLE_RE.search(page):
            title = html.unescape(m.group(1)).strip() or None

        urls: list[str] = []
        urls += META_RE.findall(page)
        urls += IMG_RE.findall(page)
        for srcset in SRCSET_RE.findall(page):
            urls += [part.strip().split(" ")[0] for part in srcset.split(",") if part.strip()]

        candidates = []
        for u in urls:
            absolute = absolutize(base_url, html.unescape(u))
            if absolute.startswith("data:"):
                continue
            if looks_like_image(absolute):
                candidates.append(ImageCandidate(url=absolute, title=title))
        return dedupe(candidates)
