from __future__ import annotations

import io
from pathlib import Path

import pytest
import pytest_asyncio
from PIL import Image
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base


def make_png(size: tuple[int, int] = (200, 120), color=(255, 0, 0, 255)) -> bytes:
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    image.paste(Image.new("RGBA", (size[0] // 2, size[1] // 2), color), (10, 10))
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture(autouse=True)
def storage_tmp(tmp_path: Path, monkeypatch):
    from app.config import settings
    import app.storage.local as local

    monkeypatch.setattr(settings, "storage_dir", tmp_path / "images")
    local._storage = None
    yield tmp_path
    local._storage = None


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()
