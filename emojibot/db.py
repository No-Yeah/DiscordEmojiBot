"""SQLite 연결과 스키마. 봇과 웹이 같은 DB 파일을 함께 쓴다(WAL 모드)."""
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime

DATA_DIR = os.environ.get("EMOJI_DATA", "/var/lib/emoji-bot")
DB_PATH = os.path.join(DATA_DIR, "emoji.db")
IMG_DIR = os.environ.get("EMOJI_IMG_DIR") or os.path.join(DATA_DIR, "images")  # 설치 시 고른 이미지 폴더

SCHEMA = """
CREATE TABLE IF NOT EXISTS packs(
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('pack','single')),
  name TEXT NOT NULL,
  url TEXT,
  add_date TEXT NOT NULL,
  add_user TEXT NOT NULL,
  deleted_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_pack_name ON packs(lower(name))
  WHERE kind = 'pack' AND deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS emojis(
  id INTEGER PRIMARY KEY,
  pack_id INTEGER NOT NULL REFERENCES packs(id),
  ename TEXT NOT NULL,
  file TEXT NOT NULL,
  seq INTEGER NOT NULL DEFAULT 1,
  add_date TEXT NOT NULL,
  deleted_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_ename ON emojis(lower(ename)) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS ix_emojis_pack ON emojis(pack_id);

CREATE TABLE IF NOT EXISTS grp(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE);
CREATE TABLE IF NOT EXISTS pack_grp(
  pack_id INTEGER NOT NULL REFERENCES packs(id) ON DELETE CASCADE,
  group_id INTEGER NOT NULL REFERENCES grp(id) ON DELETE CASCADE,
  PRIMARY KEY (pack_id, group_id)
);

CREATE TABLE IF NOT EXISTS tags(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS emoji_tags(
  emoji_id INTEGER NOT NULL REFERENCES emojis(id) ON DELETE CASCADE,
  tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  PRIMARY KEY (emoji_id, tag_id)
);

CREATE TABLE IF NOT EXISTS users(
  discord_id TEXT PRIMARY KEY,
  username TEXT,
  add_date TEXT NOT NULL,
  can_bot INTEGER NOT NULL DEFAULT 0,
  can_web INTEGER NOT NULL DEFAULT 0,
  deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS usage_log(
  id INTEGER PRIMARY KEY,
  emoji_id INTEGER NOT NULL,
  discord_id TEXT NOT NULL,
  used_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_usage_at ON usage_log(used_at);

CREATE TABLE IF NOT EXISTS admin(
  id INTEGER PRIMARY KEY CHECK (id = 1),
  username TEXT NOT NULL,
  pw_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS login_tokens(
  token TEXT PRIMARY KEY,
  discord_id TEXT NOT NULL,
  expires_at TEXT NOT NULL
);
"""


def now():
    # 시간대는 systemd 유닛의 TZ(기본 Asia/Seoul)를 따른다.
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@contextmanager
def conn():
    """with 블록이 정상 종료되면 커밋, 예외면 롤백 후 닫는다."""
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    try:
        yield c
        c.commit()
    except BaseException:
        c.rollback()
        raise
    finally:
        c.close()


def init():
    os.makedirs(IMG_DIR, exist_ok=True)
    with conn() as c:
        c.execute("PRAGMA journal_mode = WAL")
        c.executescript(SCHEMA)
