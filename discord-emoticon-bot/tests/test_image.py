from __future__ import annotations

import io

import pytest
from PIL import Image

from app.image.processor import hamming_distance, process
from app.image.validator import ImageValidationError, validate
from tests.conftest import make_png


def test_process_makes_square_transparent_png():
    result = process(make_png((200, 120)), size=256)
    assert result.width == result.height == 256
    with Image.open(io.BytesIO(result.png)) as im:
        assert im.format == "PNG"
        assert im.mode == "RGBA"
        # 여백은 투명으로 채워져야 한다
        assert im.getpixel((0, 0))[3] == 0


def test_process_keeps_aspect_ratio():
    # 가로로 긴 이미지가 세로로 늘어나면 안 된다
    wide = Image.new("RGBA", (400, 100), (0, 0, 255, 255))
    buf = io.BytesIO()
    wide.save(buf, format="PNG")
    result = process(buf.getvalue(), size=256)
    with Image.open(io.BytesIO(result.png)) as im:
        opaque_rows = [y for y in range(im.height) if im.getpixel((im.width // 2, y))[3] > 0]
    height = max(opaque_rows) - min(opaque_rows) + 1
    assert 55 <= height <= 75  # 400:100 비율이면 256폭 기준 약 64


def test_emoji_variant_fits_discord_limit():
    result = process(make_png((1024, 1024)))
    assert len(result.emoji_png) <= 256 * 1024


def test_identical_images_share_hashes():
    a = process(make_png())
    b = process(make_png())
    assert a.sha256 == b.sha256
    assert a.dhash == b.dhash


def test_different_images_differ_visually():
    a = process(make_png(color=(255, 0, 0, 255)))
    b = process(make_png((200, 120), color=(0, 255, 0, 255)))
    # 색만 다르면 dhash는 비슷할 수 있으니 구조가 다른 케이스로 검증
    c = process(make_png((300, 300)))
    assert a.sha256 != b.sha256
    assert hamming_distance(a.dhash, c.dhash) > 0


def test_validate_rejects_html_disguised_as_image():
    with pytest.raises(ImageValidationError):
        validate(b"<!DOCTYPE html><html><script>alert(1)</script></html>")


def test_validate_rejects_garbage():
    with pytest.raises(ImageValidationError):
        validate(b"\x00\x01\x02not an image at all")


def test_validate_accepts_png():
    assert validate(make_png()) == "PNG"
