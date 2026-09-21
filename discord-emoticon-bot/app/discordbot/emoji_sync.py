"""Application-Owned Emoji 등록.

Discord 제약(2026-09 기준 공식 문서):
  - 앱 하나당 최대 2000개
  - 파일 1개당 최대 256 KiB, 권장 128x128
  - 이 이모지는 '이 앱이 보내는 메시지'에서만 렌더링된다.
    사용자가 직접 입력창에 쳐서 쓸 수는 없다(Nitro와 무관).
등록에 실패해도 치명적이지 않다. 이미지 첨부 전송으로 폴백한다.
"""

from __future__ import annotations

import logging

import discord
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import AppEmoji, Emoticon
from app.storage.local import get_storage

logger = logging.getLogger(__name__)

MAX_APP_EMOJIS = 2000


def emoji_name_for(emoticon: Emoticon) -> str:
    """Discord 이모지 이름 규칙: [A-Za-z0-9_] 2~32자. 한글 이름은 쓸 수 없다."""
    ascii_part = "".join(ch for ch in emoticon.name if ch.isascii() and ch.isalnum())
    suffix = f"_{ascii_part[:20]}" if ascii_part else ""
    return f"emo{emoticon.id}{suffix}"[:32]


async def ensure_app_emoji(
    bot: discord.Client, session: AsyncSession, emoticon: Emoticon
) -> AppEmoji | None:
    """이모티콘에 대응하는 앱 이모지를 만들고 매핑을 저장한다."""
    if not settings.app_emoji_enabled:
        return None
    if emoticon.app_emoji is not None:
        return emoticon.app_emoji
    if not emoticon.preview_path:
        return None

    registered = int(await session.scalar(select(func.count(AppEmoji.id))) or 0)
    if registered >= MAX_APP_EMOJIS:
        logger.warning("app emoji 한도(%d) 도달 - 이미지 전송으로 대체됩니다", MAX_APP_EMOJIS)
        return None

    storage = get_storage()
    try:
        image = storage.read(emoticon.preview_path)
    except OSError:
        logger.exception("preview 파일을 읽을 수 없습니다: %s", emoticon.preview_path)
        return None

    if len(image) > settings.emoji_max_bytes:
        logger.warning("preview가 256KiB를 초과해 app emoji 등록을 건너뜁니다 (#%s)", emoticon.id)
        return None

    try:
        created = await bot.create_application_emoji(
            name=emoji_name_for(emoticon), image=image
        )
    except discord.HTTPException as exc:
        logger.warning("app emoji 등록 실패 (#%s): %s", emoticon.id, exc)
        return None

    mapping = AppEmoji(
        emoticon_id=emoticon.id,
        emoji_id=created.id,
        emoji_name=created.name,
        animated=created.animated,
    )
    session.add(mapping)
    await session.flush()
    emoticon.app_emoji = mapping
    logger.info("app emoji 등록: %s -> %s", emoticon.name, mapping.mention)
    return mapping


async def delete_app_emoji(
    bot: discord.Client, session: AsyncSession, emoticon: Emoticon
) -> None:
    mapping = emoticon.app_emoji
    if mapping is None:
        return
    try:
        emoji = await bot.fetch_application_emoji(mapping.emoji_id)
        await emoji.delete()
    except discord.HTTPException as exc:  # 이미 지워졌을 수 있다
        logger.warning("app emoji 삭제 실패 (#%s): %s", emoticon.id, exc)
    await session.delete(mapping)
