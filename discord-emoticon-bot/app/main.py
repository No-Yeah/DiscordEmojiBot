"""실행 진입점: `python -m app.main`"""

from __future__ import annotations

import logging
import sys

from app.config import settings


def setup_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    # 토큰이 섞일 수 있는 라이브러리 디버그 로그는 올리지 않는다.
    logging.getLogger("discord.http").setLevel(logging.WARNING)
    logging.getLogger("discord.gateway").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def main() -> None:
    setup_logging()
    from app.discordbot.bot import run

    run()


if __name__ == "__main__":
    main()
