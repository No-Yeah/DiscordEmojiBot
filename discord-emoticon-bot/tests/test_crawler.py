from __future__ import annotations

import pytest

from app.crawler.base import get_parser
from app.crawler.fetcher import FetchError, assert_safe_url
from app.crawler.generic import GenericImageParser
from app.crawler.kakao import KakaoEmoticonParser


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/x.png",
        "http://localhost/x.png",
        "http://169.254.169.254/latest/meta-data/",  # 클라우드 메타데이터
        "http://[::1]/x.png",
        "file:///etc/passwd",
        "ftp://example.com/x.png",
        "http://user:pw@example.com/x.png",
        "http://example.com:22/x.png",
    ],
)
def test_assert_safe_url_blocks_dangerous(url):
    with pytest.raises(FetchError):
        assert_safe_url(url)


def test_assert_safe_url_allows_public_https():
    assert assert_safe_url("https://example.com/a.png").startswith("https://")


def test_parser_selection():
    assert isinstance(get_parser("https://e.kakao.com/t/abc"), KakaoEmoticonParser)
    assert isinstance(get_parser("https://example.com/page"), GenericImageParser)


def test_kakao_parser_picks_cdn_images_and_skips_noise():
    page = """
    <html><head><title>누룽이 아무튼</title>
    <meta property="og:image" content="https://item.kakaocdn.net/og/thumb.png"></head>
    <body>
      <img src="https://item.kakaocdn.net/do/1a/emoticon_01.png">
      <img src="https://item.kakaocdn.net/do/1a/emoticon_02.webp">
      <img src="https://item.kakaocdn.net/do/1a/profile_owner.png">
    </body></html>
    """
    found = KakaoEmoticonParser().extract(page, "https://e.kakao.com/t/abc")
    urls = [c.url for c in found]
    assert "https://item.kakaocdn.net/do/1a/emoticon_01.png" in urls
    assert "https://item.kakaocdn.net/do/1a/emoticon_02.webp" in urls
    assert all("profile" not in u for u in urls)
    assert found[0].title == "누룽이 아무튼"


def test_generic_parser_absolutizes_and_filters():
    page = """
    <html><body>
      <img src="/img/a.png">
      <img data-src="https://cdn.example.com/b.webp">
      <img src="/script.js">
      <img src="data:image/png;base64,AAAA">
    </body></html>
    """
    urls = [c.url for c in GenericImageParser().extract(page, "https://site.test/page")]
    assert "https://site.test/img/a.png" in urls
    assert "https://cdn.example.com/b.webp" in urls
    assert not any(u.endswith(".js") for u in urls)
    assert not any(u.startswith("data:") for u in urls)
