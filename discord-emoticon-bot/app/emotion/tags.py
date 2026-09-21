"""기본 감정 태그와 감정 간 유사도 그래프.

여기 정의된 값은 최초 1회 DB로 seed된다. 이후 태그 추가/수정은 DB(관리자 UI)에서 한다.
"""

from __future__ import annotations

from typing import NamedTuple


class EmotionDef(NamedTuple):
    tag: str        # '#' 없이 저장
    label: str
    icon: str
    is_primary: bool = False   # /e 감정 선택 버튼에 노출할 대표 감정
    sort_order: int = 100


DEFAULT_EMOTIONS: tuple[EmotionDef, ...] = (
    EmotionDef("기쁨", "기쁨", "😀", True, 10),
    EmotionDef("웃김", "웃김", "😂", True, 20),
    EmotionDef("슬픔", "슬픔", "😭", True, 30),
    EmotionDef("분노", "분노", "😡", True, 40),
    EmotionDef("황당", "황당", "😯", True, 50),
    EmotionDef("어이없음", "어이없음", "🙄", False, 55),
    EmotionDef("체념", "체념", "😮‍💨", False, 60),
    EmotionDef("무덤덤", "무덤덤", "😐", True, 70),
    EmotionDef("귀찮음", "귀찮음", "😑", True, 80),
    EmotionDef("놀람", "놀람", "😲", False, 90),
    EmotionDef("당황", "당황", "😳", True, 100),
    EmotionDef("감동", "감동", "🥹", False, 110),
    EmotionDef("축하", "축하", "🎉", False, 120),
    EmotionDef("동의", "동의", "👍", False, 130),
    EmotionDef("거절", "거절", "🙅", False, 140),
    EmotionDef("의문", "의문", "❓", False, 150),
    EmotionDef("생각", "생각", "🤔", True, 160),
    EmotionDef("피곤", "피곤", "🥱", False, 170),
)

# tag -> [(related_tag, weight)] : 검색 시 가중치가 곱해진다. 양방향으로 seed된다.
DEFAULT_RELATIONS: dict[str, list[tuple[str, float]]] = {
    "무덤덤": [("귀찮음", 0.7), ("체념", 0.7), ("어이없음", 0.5)],
    "귀찮음": [("피곤", 0.8), ("체념", 0.6), ("무덤덤", 0.7)],
    "황당": [("어이없음", 0.9), ("놀람", 0.6), ("당황", 0.6)],
    "어이없음": [("체념", 0.6), ("분노", 0.4)],
    "기쁨": [("웃김", 0.7), ("축하", 0.6), ("감동", 0.5)],
    "슬픔": [("감동", 0.4), ("체념", 0.5)],
    "분노": [("황당", 0.5)],
    "당황": [("놀람", 0.7), ("의문", 0.5)],
    "생각": [("의문", 0.7)],
}


def normalize_tag(raw: str) -> str:
    """'#황당', ' 황당 ' -> '황당'."""
    return raw.strip().lstrip("#").strip()
