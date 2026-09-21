"""로컬 파일 저장소."""

from __future__ import annotations

import logging
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)


class LocalStorage:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or settings.storage_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, rel_path: str) -> Path:
        target = (self.root / rel_path).resolve()
        # 경로 탈출 방지(관리자 UI가 경로를 받기 때문에 필수)
        if not target.is_relative_to(self.root):
            raise ValueError(f"허용되지 않는 경로입니다: {rel_path}")
        return target

    def save(self, rel_path: str, data: bytes) -> str:
        target = self._resolve(rel_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(target)  # 부분 기록 파일이 남지 않도록 원자적 교체
        return rel_path

    def read(self, rel_path: str) -> bytes:
        return self._resolve(rel_path).read_bytes()

    def delete(self, rel_path: str) -> None:
        try:
            self._resolve(rel_path).unlink(missing_ok=True)
        except ValueError:
            logger.warning("skip delete for unsafe path: %s", rel_path)

    def exists(self, rel_path: str) -> bool:
        try:
            return self._resolve(rel_path).is_file()
        except ValueError:
            return False

    def full_path(self, rel_path: str) -> Path:
        return self._resolve(rel_path)


_storage: LocalStorage | None = None


def get_storage() -> LocalStorage:
    global _storage
    if _storage is None:
        _storage = LocalStorage()
    return _storage
