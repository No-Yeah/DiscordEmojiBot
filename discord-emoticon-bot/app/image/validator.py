"""다운로드한 바이트가 실제로 안전한 이미지인지 검증한다.

확장자/Content-Type은 위조 가능하므로 Pillow 디코딩 결과만 신뢰한다.
"""

from __future__ import annotations

import io
import logging

from PIL import Image, UnidentifiedImageError

from app.config import settings

logger = logging.getLogger(__name__)

ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP", "GIF", "BMP"}


class ImageValidationError(ValueError):
    pass


def validate(data: bytes) -> str:
    """유효하면 Pillow format 문자열을 반환, 아니면 ImageValidationError."""
    if not data:
        raise ImageValidationError("빈 응답입니다.")
    if len(data) > settings.max_download_bytes:
        raise ImageValidationError("이미지가 허용 크기를 초과했습니다.")

    # HTML/JS를 이미지로 위장한 경우를 이른 단계에서 차단
    head = data[:512].lstrip().lower()
    if head.startswith((b"<!doctype", b"<html", b"<?xml", b"<svg", b"<script")):
        raise ImageValidationError("이미지가 아니라 마크업 문서입니다.")

    previous_limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = settings.max_image_pixels
    try:
        with Image.open(io.BytesIO(data)) as im:
            fmt = (im.format or "").upper()
            im.verify()  # 구조 검증(디코드 후 객체는 재사용 불가)
        if fmt not in ALLOWED_FORMATS:
            raise ImageValidationError(f"지원하지 않는 이미지 형식입니다: {fmt or 'unknown'}")
        with Image.open(io.BytesIO(data)) as im:
            w, h = im.size
            if w < 8 or h < 8:
                raise ImageValidationError("이미지가 너무 작습니다.")
            if w * h > settings.max_image_pixels:
                raise ImageValidationError("이미지 픽셀 수가 허용치를 초과했습니다.")
        return fmt
    except UnidentifiedImageError as exc:
        raise ImageValidationError("이미지로 해석할 수 없는 데이터입니다.") from exc
    except Image.DecompressionBombError as exc:
        raise ImageValidationError("비정상적으로 큰 이미지입니다.") from exc
    except OSError as exc:
        raise ImageValidationError(f"손상된 이미지입니다: {exc}") from exc
    finally:
        Image.MAX_IMAGE_PIXELS = previous_limit
