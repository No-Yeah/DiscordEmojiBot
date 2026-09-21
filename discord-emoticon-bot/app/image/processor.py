"""모든 이모티콘을 동일 규격(정사각 투명 PNG)으로 정규화한다.

- 비율 유지, 왜곡 없음. 남는 영역은 투명으로 패딩.
- 애니메이션(GIF/WebP)은 첫 프레임만 사용한다. (ponytail: 정적 PNG 하나로 통일)
- 해시 2종: sha256(완전 동일), dHash(시각적 동일/유사).
"""

from __future__ import annotations

import hashlib
import io
import logging
from dataclasses import dataclass

from PIL import Image

from app.config import settings
from app.image.validator import validate

logger = logging.getLogger(__name__)

_DHASH_W, _DHASH_H = 9, 8


@dataclass(frozen=True, slots=True)
class ProcessedImage:
    png: bytes          # image_size x image_size 투명 PNG
    emoji_png: bytes    # Discord 업로드용(<=256KiB)
    width: int
    height: int
    sha256: str
    dhash: str
    source_format: str


def _first_frame(im: Image.Image) -> Image.Image:
    if getattr(im, "n_frames", 1) > 1:
        im.seek(0)
    return im.convert("RGBA")


def _trim_transparent(im: Image.Image) -> Image.Image:
    """투명 여백을 잘라낸다. 전부 투명하면 원본 유지."""
    bbox = im.getbbox()
    if bbox and bbox != (0, 0, *im.size):
        return im.crop(bbox)
    return im


def _fit_square(im: Image.Image, size: int) -> Image.Image:
    """비율을 유지한 채 size x size 투명 캔버스 가운데 배치."""
    src = im.copy()
    src.thumbnail((size, size), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(src, ((size - src.width) // 2, (size - src.height) // 2))
    return canvas


def _to_png(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def compute_dhash(im: Image.Image) -> str:
    """difference hash(64bit). 투명 배경은 흰색으로 합성해 안정화한다."""
    flat = Image.new("RGBA", im.size, (255, 255, 255, 255))
    flat.alpha_composite(im)
    gray = flat.convert("L").resize((_DHASH_W, _DHASH_H), Image.LANCZOS)
    pixels = list(gray.getdata())
    bits = 0
    for row in range(_DHASH_H):
        offset = row * _DHASH_W
        for col in range(_DHASH_W - 1):
            bits = (bits << 1) | int(pixels[offset + col] > pixels[offset + col + 1])
    return f"{bits:016x}"


def hamming_distance(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def _emoji_variant(im: Image.Image) -> bytes:
    """Discord 이모지 업로드 한도(256KiB) 안에 들어오는 PNG를 만든다."""
    for size in (settings.emoji_size, 112, 96, 72, 64):
        data = _to_png(_fit_square(im, size))
        if len(data) <= settings.emoji_max_bytes:
            return data
    # 마지막 수단: 팔레트 축소
    small = _fit_square(im, 64).quantize(colors=128, method=Image.FASTOCTREE)
    buf = io.BytesIO()
    small.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def process(data: bytes, size: int | None = None) -> ProcessedImage:
    """원본 바이트 -> 규격화된 PNG + 메타데이터."""
    fmt = validate(data)
    size = size or settings.image_size

    with Image.open(io.BytesIO(data)) as raw:
        frame = _first_frame(raw)

    trimmed = _trim_transparent(frame)
    square = _fit_square(trimmed, size)
    png = _to_png(square)

    return ProcessedImage(
        png=png,
        emoji_png=_emoji_variant(trimmed),
        width=square.width,
        height=square.height,
        sha256=hashlib.sha256(png).hexdigest(),
        dhash=compute_dhash(square),
        source_format=fmt,
    )
