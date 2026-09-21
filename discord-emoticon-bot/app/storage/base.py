"""저장소 인터페이스. 지금은 로컬 파일, 나중에 S3 호환으로 교체 가능."""

from __future__ import annotations

from typing import Protocol


class Storage(Protocol):
    def save(self, rel_path: str, data: bytes) -> str:
        """저장하고 조회용 상대 경로를 반환."""

    def read(self, rel_path: str) -> bytes: ...

    def delete(self, rel_path: str) -> None: ...

    def exists(self, rel_path: str) -> bool: ...
