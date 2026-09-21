"""URL 입력 -> 추출 -> 다운로드 -> 변환 -> 저장 -> 등록 전체 경로 검증.

로컬 HTTP 서버를 띄우므로 이 테스트에서만 사설망 접근을 허용한다.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.config import settings
from app.emoticon import service as emoticon_service
from app.emotion.service import seed_emotions
from app.storage.local import get_storage
from tests.conftest import make_png

PAGE = b"""<html><head><title>test pack</title></head><body>
<img src="/img/one.png"><img src="/img/two.png"></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path.startswith("/img/"):
            body = make_png()
            ctype = "image/png"
        elif self.path == "/evil.png":
            body = b"<html><script>alert(1)</script></html>"
            ctype = "image/png"  # Content-Type 위조
        else:
            body = PAGE
            ctype = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):  # 테스트 출력 조용히
        return


@pytest.fixture
def http_server(monkeypatch):
    monkeypatch.setattr(settings, "allow_private_network", True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


async def test_full_registration_flow(session, http_server):
    await seed_emotions(session)

    extracted = await emoticon_service.extract_candidates(f"{http_server}/pack")
    assert extracted.parser == "generic"
    assert len(extracted.candidates) == 2

    emoticon = await emoticon_service.register(
        session,
        name="누룽이 아무튼",
        image_url=extracted.candidates[0].url,
        source_url=extracted.source_url,
        keywords=["아무튼", "누룽이"],
        emotions=["#황당", "체념"],
    )

    assert emoticon.name == "누룽이_아무튼"  # 공백은 안전하게 치환
    assert emoticon.width == emoticon.height == settings.image_size
    assert {e.tag for e in emoticon.emotions} == {"황당", "체념"}
    assert {k.value for k in emoticon.keywords} == {"아무튼", "누룽이"}

    storage = get_storage()
    assert storage.exists(emoticon.processed_path)
    assert storage.exists(emoticon.preview_path)
    assert storage.exists(emoticon.original_path)


async def test_same_image_from_different_url_is_rejected(session, http_server):
    await emoticon_service.register(
        session, name="첫번째", image_url=f"{http_server}/img/one.png", keep_original=False
    )
    with pytest.raises(emoticon_service.DuplicateEmoticon):
        await emoticon_service.register(
            session,
            name="두번째",
            image_url=f"{http_server}/img/two.png",  # URL은 다르지만 같은 이미지
            keep_original=False,
        )


async def test_fake_image_is_rejected(session, http_server):
    with pytest.raises(emoticon_service.RegistrationError):
        await emoticon_service.register(
            session, name="가짜", image_url=f"{http_server}/evil.png", keep_original=False
        )


async def test_storage_blocks_path_traversal():
    storage = get_storage()
    with pytest.raises(ValueError):
        storage.save("../../etc/passwd", b"x")
