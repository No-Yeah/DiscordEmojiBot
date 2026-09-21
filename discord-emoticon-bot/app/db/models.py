"""SQLAlchemy 2.0 모델. 이모티콘 / 키워드 / 감정을 N:M으로 연결한다."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Column,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


emoticon_keywords = Table(
    "emoticon_keywords",
    Base.metadata,
    Column("emoticon_id", ForeignKey("emoticons.id", ondelete="CASCADE"), primary_key=True),
    Column("keyword_id", ForeignKey("keywords.id", ondelete="CASCADE"), primary_key=True),
)

emoticon_emotions = Table(
    "emoticon_emotions",
    Base.metadata,
    Column("emoticon_id", ForeignKey("emoticons.id", ondelete="CASCADE"), primary_key=True),
    Column("emotion_id", ForeignKey("emotions.id", ondelete="CASCADE"), primary_key=True),
)


class Emoticon(Base):
    __tablename__ = "emoticons"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    source_url: Mapped[str | None] = mapped_column(String(1000), index=True)
    image_url: Mapped[str | None] = mapped_column(String(1000))
    source_site: Mapped[str | None] = mapped_column(String(50))

    original_path: Mapped[str | None] = mapped_column(String(300))
    processed_path: Mapped[str] = mapped_column(String(300))
    # 검색 UI 미리보기용 128px PNG(그리드에 8장씩 붙이므로 작아야 한다)
    preview_path: Mapped[str | None] = mapped_column(String(300))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)

    # 완전 동일 바이트 탐지
    image_sha256: Mapped[str] = mapped_column(String(64), index=True)
    # 시각적 유사/동일 탐지(dHash 64bit hex)
    image_dhash: Mapped[str] = mapped_column(String(16), index=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    keywords: Mapped[list["Keyword"]] = relationship(
        secondary=emoticon_keywords, back_populates="emoticons", lazy="selectin"
    )
    emotions: Mapped[list["Emotion"]] = relationship(
        secondary=emoticon_emotions, back_populates="emoticons", lazy="selectin"
    )
    app_emoji: Mapped["AppEmoji | None"] = relationship(
        back_populates="emoticon", cascade="all, delete-orphan",
        uselist=False, lazy="selectin",
    )

    def __repr__(self) -> str:  # pragma: no cover - 디버깅용
        return f"<Emoticon {self.id} {self.name}>"


class Keyword(Base):
    __tablename__ = "keywords"

    id: Mapped[int] = mapped_column(primary_key=True)
    value: Mapped[str] = mapped_column(String(50), unique=True, index=True)

    emoticons: Mapped[list[Emoticon]] = relationship(
        secondary=emoticon_keywords, back_populates="keywords"
    )


class Emotion(Base):
    __tablename__ = "emotions"

    id: Mapped[int] = mapped_column(primary_key=True)
    # '#' 없이 저장한다. 예: "황당"
    tag: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    label: Mapped[str] = mapped_column(String(50))
    icon: Mapped[str] = mapped_column(String(8), default="🙂")
    sort_order: Mapped[int] = mapped_column(Integer, default=100)
    # 감정 선택 UI에 노출할지
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)

    emoticons: Mapped[list[Emoticon]] = relationship(
        secondary=emoticon_emotions, back_populates="emotions"
    )


class EmotionRelation(Base):
    """감정 간 유사도 그래프(무덤덤 → 귀찮음 0.7 …)."""

    __tablename__ = "emotion_relations"
    __table_args__ = (UniqueConstraint("emotion_id", "related_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    emotion_id: Mapped[int] = mapped_column(ForeignKey("emotions.id", ondelete="CASCADE"))
    related_id: Mapped[int] = mapped_column(ForeignKey("emotions.id", ondelete="CASCADE"))
    weight: Mapped[float] = mapped_column(Float, default=0.5)


class AppEmoji(Base):
    """Discord Application-Owned Emoji 매핑(앱당 2000개 한도)."""

    __tablename__ = "app_emojis"

    id: Mapped[int] = mapped_column(primary_key=True)
    emoticon_id: Mapped[int] = mapped_column(
        ForeignKey("emoticons.id", ondelete="CASCADE"), unique=True
    )
    emoji_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    emoji_name: Mapped[str] = mapped_column(String(32))
    animated: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    emoticon: Mapped[Emoticon] = relationship(back_populates="app_emoji")

    @property
    def mention(self) -> str:
        prefix = "a" if self.animated else ""
        return f"<{prefix}:{self.emoji_name}:{self.emoji_id}>"


class GuildEmoji(Base):
    """서버 커스텀 이모지로도 올린 경우의 매핑(선택 기능)."""

    __tablename__ = "guild_emojis"
    __table_args__ = (UniqueConstraint("emoticon_id", "guild_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    emoticon_id: Mapped[int] = mapped_column(ForeignKey("emoticons.id", ondelete="CASCADE"))
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    emoji_id: Mapped[int] = mapped_column(BigInteger)
    emoji_name: Mapped[str] = mapped_column(String(32))


class UsageLog(Base):
    __tablename__ = "usage_logs"
    __table_args__ = (Index("ix_usage_user_time", "user_id", "used_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    emoticon_id: Mapped[int] = mapped_column(ForeignKey("emoticons.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    guild_id: Mapped[int | None] = mapped_column(BigInteger)
    context: Mapped[str] = mapped_column(String(20), default="guild")  # guild/bot_dm/private
    used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Favorite(Base):
    __tablename__ = "favorites"
    __table_args__ = (UniqueConstraint("user_id", "emoticon_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    emoticon_id: Mapped[int] = mapped_column(ForeignKey("emoticons.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
