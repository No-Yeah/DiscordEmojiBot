"""애플리케이션 설정. 모든 값은 환경변수(.env)로 주입한다."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Discord ---
    discord_bot_token: str = ""
    # 개발 중 즉시 반영용 길드 ID. 비워두면 글로벌 커맨드로 동기화(반영에 수 분 소요).
    discord_dev_guild_id: int | None = None
    # 전송 방식. image = PNG 첨부(크게 보임), emoji = 앱 이모지 인라인(작게 보임)
    send_style: Literal["image", "emoji"] = "image"
    # 앱 이모지 등록(선택). 켜면 검색 Select 항목에 썸네일 아이콘이 붙는다.
    # Discord 제약: 앱당 2000개, 256KiB, 이 앱이 보내는 메시지에서만 렌더링.
    app_emoji_enabled: bool = False

    # --- Database ---
    database_url: str = "sqlite+aiosqlite:///./data/emoticon.db"

    # --- Storage / Image ---
    storage_dir: Path = Path("./data/images")
    image_size: int = 512          # processed 정사각 PNG 한 변
    emoji_size: int = 128          # Discord 이모지 업로드용 한 변
    emoji_max_bytes: int = 256 * 1024   # Discord 하드 리밋(256 KiB)
    max_image_pixels: int = 40_000_000  # decompression bomb 방어

    # --- 외부 URL 다운로드 ---
    http_timeout: float = 10.0
    max_download_bytes: int = 8 * 1024 * 1024
    max_redirects: int = 3
    # 사설망 접근 허용(로컬 테스트 전용). 운영에서는 반드시 False.
    allow_private_network: bool = False
    user_agent: str = "discord-emoticon-bot/1.0 (+personal use)"

    # --- 검색 ---
    search_page_size: int = 8      # MediaGallery 한 페이지에 보여줄 개수
    search_max_results: int = 40

    # --- 실행 ---
    log_level: str = "INFO"

    @field_validator("storage_dir")
    @classmethod
    def _expand(cls, v: Path) -> Path:
        return v.expanduser()

    @property
    def original_dir(self) -> Path:
        return self.storage_dir / "original"

    @property
    def processed_dir(self) -> Path:
        return self.storage_dir / "processed"

    @property
    def sync_url(self) -> str:
        """Alembic 등 동기 드라이버가 필요한 곳에서 쓰는 URL."""
        return self.database_url.replace("+aiosqlite", "").replace("+asyncpg", "+psycopg")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
