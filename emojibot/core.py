"""봇과 웹이 함께 쓰는 핵심 로직: 입력 검증, 카카오 수집, 이미지 변환, DB 작업."""
import functools
import io
import ipaddress
import os
import re
import secrets
import socket
import sqlite3
import urllib.parse
import urllib.request
import uuid
from collections import Counter
from datetime import datetime, timedelta

import json
import urllib.error

from PIL import Image, ImageSequence

from . import db

EMOJI_SIZE = int(os.environ.get("EMOJI_SIZE", "180"))  # 저장 이미지의 긴 변(px)
MAX_BYTES = 10 * 1024 * 1024
MAX_FRAMES = 400
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"

COMMANDS = ("add-pack", "add", "find", "del-pack", "del", "web", "help")
TAG_RE = re.compile(r"[가-힣]+")
NAME_RE = re.compile(r"[\w\-]{1,40}")
KAKAO_IMG = re.compile(r"https://item\.kakaocdn\.net/do/([0-9a-f]{32})[0-9a-f]{32}(?![0-9a-f])")


class UserError(ValueError):
    """사용자에게 그대로 보여줄 오류."""


# ---------- 입력 검증 ----------

def check_name(value, what):
    value = (value or "").strip()
    if not NAME_RE.fullmatch(value) or value.startswith("-"):
        raise UserError(f"{what}은 공백 없이 1~40자(한글, 영문, 숫자, _, -)로 입력하세요: {value or '(비어 있음)'}")
    if value.lower() in COMMANDS:
        raise UserError(f"'{value}'는 명령어라서 {what}으로 쓸 수 없습니다.")
    return value


def split_list(value):
    """'a, b' 문자열이나 리스트를 중복 없는 리스트로. '-'는 빈 값."""
    if value is None:
        return []
    items = value.split(",") if isinstance(value, str) else value
    out = []
    for x in items:
        x = str(x).strip()
        if x and x != "-" and x not in out:
            out.append(x)
    return out


def parse_tags(value):
    tags = split_list(value)
    for t in tags:
        if not TAG_RE.fullmatch(t):
            raise UserError(f"태그는 한글만 쓸 수 있습니다: {t}")
    return tags


def parse_groups(value):
    return [check_name(g, "그룹명") for g in split_list(value)]


# ---------- 외부 요청 ----------

def _check_url(url):
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise UserError("http(s) 주소만 사용할 수 있습니다.")
    try:
        infos = socket.getaddrinfo(p.hostname, None)
    except socket.gaierror:
        raise UserError(f"주소를 찾을 수 없습니다: {p.hostname}")
    for info in infos:
        # ponytail: 요청 직전 DNS 확인만 한다. DNS 리바인딩까지 막으려면 프록시 경유가 필요.
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise UserError("내부망 주소로는 요청할 수 없습니다.")


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url, limit=MAX_BYTES):
    _check_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.build_opener(_SafeRedirect).open(req, timeout=20) as r:
            data = r.read(limit + 1)
    except UserError:
        raise
    except Exception as e:
        raise UserError(f"주소를 불러오지 못했습니다 ({e.__class__.__name__}): {url}")
    if len(data) > limit:
        raise UserError(f"파일이 너무 큽니다 (최대 {limit // 1024 // 1024}MB).")
    return data


def parse_kakao(html):
    """상세 페이지 HTML에서 팩 이미지 주소를 순서대로 뽑는다.

    팩의 이미지들은 item.kakaocdn.net/do/ 뒤 64자리 중 앞 32자리가 같다.
    대표 이미지·추천 목록은 서로 다른 앞자리를 가지므로 가장 많이 나온 앞자리 묶음만 고른다.
    """
    urls = []
    for m in KAKAO_IMG.finditer(html):
        if m.group(0) not in urls:
            urls.append(m.group(0))
    if not urls:
        raise UserError("페이지에서 이모티콘 이미지를 찾지 못했습니다. 카카오 페이지 구조가 바뀌었을 수 있습니다.")
    prefix, count = Counter(KAKAO_IMG.match(u).group(1) for u in urls).most_common(1)[0]
    if count < 2:
        raise UserError("이모티콘 목록을 구분하지 못했습니다. 카카오 페이지 구조가 바뀌었을 수 있습니다.")
    return [u for u in urls if KAKAO_IMG.match(u).group(1) == prefix]


def kakao_pack(url):
    p = urllib.parse.urlparse((url or "").strip())
    if p.scheme != "https" or p.hostname != "e.kakao.com" or not p.path.startswith("/t/"):
        raise UserError("카카오 이모티콘 주소(https://e.kakao.com/t/...)를 입력하세요.")
    clean = f"https://e.kakao.com{p.path}"
    return clean, parse_kakao(fetch(clean).decode("utf-8", "replace"))


# ---------- 이미지 ----------

def process_image(data, size=EMOJI_SIZE):
    """긴 변을 size로 맞춘다. 움직이는 이미지는 GIF, 정지 이미지는 PNG로 저장."""
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception:
        raise UserError("이미지 파일이 아닙니다 (PNG, GIF, WebP, JPG 지원).")
    if im.format not in ("PNG", "GIF", "WEBP", "JPEG"):
        raise UserError(f"지원하지 않는 이미지 형식입니다: {im.format}")

    def fit(frame):
        frame = frame.convert("RGBA")
        w, h = frame.size
        s = size / max(w, h)
        return frame.resize((max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS)

    out = io.BytesIO()
    if getattr(im, "n_frames", 1) > 1:
        if im.n_frames > MAX_FRAMES:
            raise UserError(f"프레임이 너무 많습니다 (최대 {MAX_FRAMES}).")
        frames, durations = [], []
        for fr in ImageSequence.Iterator(im):
            frames.append(fit(fr))
            durations.append(fr.info.get("duration") or im.info.get("duration") or 100)
        frames = [_gif_frame(f) for f in frames]
        frames[0].save(out, "GIF", save_all=True, append_images=frames[1:], duration=durations,
                       loop=0, disposal=2, transparency=255, optimize=False)
        return out.getvalue(), "gif"
    fit(im).save(out, "PNG", optimize=True)
    return out.getvalue(), "png"


def _gif_frame(frame):
    """RGBA → 팔레트 255색 + 투명 색 1개(255번). GIF는 반투명이 없어 알파 128 기준으로 자른다."""
    p = frame.convert("RGB").quantize(colors=255)
    palette = p.getpalette()[:255 * 3]
    p.putpalette(palette + [0] * (768 - len(palette)))
    p.paste(255, mask=frame.getchannel("A").point(lambda a: 255 if a < 128 else 0))
    return p


def _save_image(data):
    body, ext = process_image(data)
    name = f"{uuid.uuid4().hex}.{ext}"
    with open(os.path.join(db.IMG_DIR, name), "wb") as f:
        f.write(body)
    return name


def _remove_files(files):
    for f in files:
        try:
            os.remove(os.path.join(db.IMG_DIR, f))
        except FileNotFoundError:
            pass


# ---------- 추가 ----------

def _ename_taken(c, names):
    q = ",".join("?" * len(names))
    row = c.execute(f"SELECT ename FROM emojis WHERE deleted_at IS NULL AND lower(ename) IN ({q})",
                    [n.lower() for n in names]).fetchone()
    return row["ename"] if row else None


def _pack_name_taken(c, name, exclude_id=None):
    return c.execute("SELECT 1 FROM packs WHERE kind='pack' AND deleted_at IS NULL AND lower(name)=lower(?) "
                     "AND id IS NOT ?", (name, exclude_id)).fetchone() is not None


def _existing_ids(c, table, names):
    """이미 등록된 태그/그룹만 붙일 수 있다. 오타로 새 태그가 생기지 않게 하기 위함."""
    what = "태그" if table == "tags" else "그룹"
    ids, missing = [], []
    for n in names:
        row = c.execute(f"SELECT id FROM {table} WHERE name=? COLLATE NOCASE", (n,)).fetchone()
        (ids.append(row["id"]) if row else missing.append(n))
    if missing:
        raise UserError(f"등록되지 않은 {what}입니다: {', '.join(missing)}. 웹의 {what} 관리에서 먼저 추가하세요.")
    return ids


def _set_groups(c, pack_id, groups):
    ids = _existing_ids(c, "grp", groups)
    c.execute("DELETE FROM pack_grp WHERE pack_id=?", (pack_id,))
    c.executemany("INSERT INTO pack_grp VALUES (?,?)", [(pack_id, g) for g in ids])


def _set_tags(c, emoji_id, tags):
    ids = _existing_ids(c, "tags", tags)
    c.execute("DELETE FROM emoji_tags WHERE emoji_id=?", (emoji_id,))
    c.executemany("INSERT INTO emoji_tags VALUES (?,?)", [(emoji_id, t) for t in ids])


def add_pack(url, name, add_user):
    """카카오 팩을 받아 name-1, name-2 ... 로 등록. 추가된 개수를 돌려준다."""
    name = check_name(name, "팩 이름")
    with db.conn() as c:
        if _pack_name_taken(c, name):
            raise UserError(f"이미 있는 팩 이름입니다: {name}")
    clean, urls = kakao_pack(url)
    enames = [f"{name}-{i}" for i in range(1, len(urls) + 1)]
    files = []
    try:
        for u in urls:
            files.append(_save_image(fetch(u)))
        with db.conn() as c:
            if _pack_name_taken(c, name):
                raise UserError(f"이미 있는 팩 이름입니다: {name}")
            taken = _ename_taken(c, enames)
            if taken:
                raise UserError(f"이미 같은 이름의 이모티콘이 있습니다: {taken}")
            t = db.now()
            pid = c.execute("INSERT INTO packs(kind,name,url,add_date,add_user) VALUES ('pack',?,?,?,?)",
                            (name, clean, t, add_user)).lastrowid
            c.executemany("INSERT INTO emojis(pack_id,ename,file,seq,add_date) VALUES (?,?,?,?,?)",
                          [(pid, e, f, i, t) for i, (e, f) in enumerate(zip(enames, files), 1)])
    except BaseException:
        _remove_files(files)
        raise
    return len(files)


def add_single(ename, data, add_user, name=None, groups=None, tags=None):
    ename = check_name(ename, "이모티콘 이름")
    name = check_name(name, "이름") if split_list(name) else ename
    groups, tags = parse_groups(groups), parse_tags(tags)
    with db.conn() as c:
        if _ename_taken(c, [ename]):
            raise UserError(f"이미 있는 이모티콘 이름입니다: {ename}")
        _existing_ids(c, "grp", groups)
        _existing_ids(c, "tags", tags)
    f = _save_image(data)
    try:
        with db.conn() as c:
            if _ename_taken(c, [ename]):
                raise UserError(f"이미 있는 이모티콘 이름입니다: {ename}")
            t = db.now()
            pid = c.execute("INSERT INTO packs(kind,name,add_date,add_user) VALUES ('single',?,?,?)",
                            (name, t, add_user)).lastrowid
            eid = c.execute("INSERT INTO emojis(pack_id,ename,file,add_date) VALUES (?,?,?,?)",
                            (pid, ename, f, t)).lastrowid
            _set_groups(c, pid, groups)
            _set_tags(c, eid, tags)
    except BaseException:
        _remove_files([f])
        raise
    return ename


# ---------- 편집 ----------

def set_tags(emoji_id, tags):
    tags = parse_tags(tags)
    with db.conn() as c:
        _set_tags(c, emoji_id, tags)


def set_groups(pack_id, groups):
    groups = parse_groups(groups)
    with db.conn() as c:
        _set_groups(c, pack_id, groups)


def bulk_groups(pack_ids, groups, mode="add"):
    """여러 팩·단일 이모티콘에 그룹을 한꺼번에 붙이거나(add) 뗀다(remove). 바뀐 대상 수를 돌려준다."""
    groups = parse_groups(groups)
    ids = sorted({int(i) for i in pack_ids})
    if not ids:
        raise UserError("먼저 목록에서 대상을 체크하세요.")
    if not groups:
        raise UserError("그룹을 하나 이상 고르세요.")
    with db.conn() as c:
        gids = _existing_ids(c, "grp", groups)
        marks = ",".join("?" * len(ids))
        live = [r[0] for r in c.execute(f"SELECT id FROM packs WHERE deleted_at IS NULL AND id IN ({marks})", ids)]
        pairs = [(pid, gid) for pid in live for gid in gids]
        if mode == "remove":
            c.executemany("DELETE FROM pack_grp WHERE pack_id=? AND group_id=?", pairs)
        else:
            c.executemany("INSERT OR IGNORE INTO pack_grp VALUES (?,?)", pairs)
    return len(live)


def rename_emoji(emoji_id, new):
    new = check_name(new, "이모티콘 이름")
    with db.conn() as c:
        row = c.execute("SELECT ename FROM emojis WHERE deleted_at IS NULL AND lower(ename)=lower(?) AND id<>?",
                        (new, emoji_id)).fetchone()
        if row:
            raise UserError(f"이미 있는 이모티콘 이름입니다: {new}")
        c.execute("UPDATE emojis SET ename=? WHERE id=?", (new, emoji_id))


def rename_pack(pack_id, new):
    new = check_name(new, "이름")
    with db.conn() as c:
        if _pack_name_taken(c, new, pack_id):
            raise UserError(f"이미 있는 팩 이름입니다: {new}")
        c.execute("UPDATE packs SET name=? WHERE id=?", (new, pack_id))


def add_label(table, name):
    """table: 'tags' 또는 'grp'"""
    name = parse_tags(name)[0] if table == "tags" else check_name(name, "그룹명")
    try:
        with db.conn() as c:
            c.execute(f"INSERT INTO {table}(name) VALUES (?)", (name,))
    except sqlite3.IntegrityError:
        raise UserError(f"이미 있습니다: {name}")


def rename_label(table, label_id, new):
    new = (parse_tags(new) or [""])[0] if table == "tags" else check_name(new, "그룹명")
    if not new:
        raise UserError("새 이름을 입력하세요.")
    try:
        with db.conn() as c:
            c.execute(f"UPDATE {table} SET name=? WHERE id=?", (new, label_id))
    except sqlite3.IntegrityError:
        raise UserError(f"이미 있습니다: {new}")


def label_exists(table, name):
    with db.conn() as c:
        return c.execute(f"SELECT 1 FROM {table} WHERE name=? COLLATE NOCASE", (name,)).fetchone() is not None


def delete_label(table, name=None, label_id=None):
    """태그/그룹 이름만 지운다. 연결된 이모티콘은 그대로 남는다."""
    with db.conn() as c:
        if label_id is not None:
            return c.execute(f"DELETE FROM {table} WHERE id=?", (label_id,)).rowcount
        return c.execute(f"DELETE FROM {table} WHERE name=? COLLATE NOCASE", (name,)).rowcount


# ---------- 삭제 (이모티콘은 삭제 시각만 남기고 파일은 지운다) ----------

_TARGET_SQL = {
    "emoji": "SELECT id FROM emojis WHERE deleted_at IS NULL AND lower(ename)=lower(?)",
    "name": "SELECT e.id FROM emojis e JOIN packs p ON p.id=e.pack_id "
            "WHERE e.deleted_at IS NULL AND lower(p.name)=lower(?)",
    "tag": "SELECT e.id FROM emojis e JOIN emoji_tags et ON et.emoji_id=e.id JOIN tags t ON t.id=et.tag_id "
           "WHERE e.deleted_at IS NULL AND t.name=?",
    "group": "SELECT e.id FROM emojis e JOIN pack_grp pg ON pg.pack_id=e.pack_id JOIN grp g ON g.id=pg.group_id "
             "WHERE e.deleted_at IS NULL AND g.name=? COLLATE NOCASE",
    "pack_id": "SELECT id FROM emojis WHERE deleted_at IS NULL AND pack_id=?",
    "emoji_id": "SELECT id FROM emojis WHERE deleted_at IS NULL AND id=?",
}


def count_targets(field, value):
    with db.conn() as c:
        return len(c.execute(_TARGET_SQL[field], (value,)).fetchall())


def delete_emojis(field, value):
    """field: emoji | name | tag | group | pack_id | emoji_id. 지운 개수를 돌려준다."""
    with db.conn() as c:
        ids = [r["id"] for r in c.execute(_TARGET_SQL[field], (value,))]
        if not ids:
            return 0
        q = ",".join("?" * len(ids))
        files = [r["file"] for r in c.execute(f"SELECT file FROM emojis WHERE id IN ({q})", ids)]
        t = db.now()
        c.execute(f"UPDATE emojis SET deleted_at=? WHERE id IN ({q})", [t, *ids])
        c.execute(f"DELETE FROM emoji_tags WHERE emoji_id IN ({q})", ids)
        # 남은 이모티콘이 없는 팩도 삭제 처리
        c.execute("UPDATE packs SET deleted_at=? WHERE deleted_at IS NULL AND NOT EXISTS "
                  "(SELECT 1 FROM emojis e WHERE e.pack_id=packs.id AND e.deleted_at IS NULL)", (t,))
    _remove_files(files)
    return len(ids)


# ---------- 조회 ----------

_EMOJI_COLS = """e.id, e.ename, e.file, p.name AS pack, p.kind,
  (SELECT group_concat(t.name, ', ') FROM emoji_tags et JOIN tags t ON t.id=et.tag_id WHERE et.emoji_id=e.id) AS tags"""


def get_emoji(ename):
    with db.conn() as c:
        return c.execute(f"SELECT {_EMOJI_COLS} FROM emojis e JOIN packs p ON p.id=e.pack_id "
                         "WHERE e.deleted_at IS NULL AND lower(e.ename)=lower(?)", (ename.strip(),)).fetchone()


_SEARCH = {
    "name": "instr(lower(e.ename), lower(:q)) OR instr(lower(p.name), lower(:q))",
    "tag": "EXISTS (SELECT 1 FROM emoji_tags et JOIN tags t ON t.id=et.tag_id "
           "WHERE et.emoji_id=e.id AND instr(t.name, :q))",
    "group": "EXISTS (SELECT 1 FROM pack_grp pg JOIN grp g ON g.id=pg.group_id "
             "WHERE pg.pack_id=p.id AND instr(lower(g.name), lower(:q)))",
}
_SEARCH["all"] = " OR ".join(f"({v})" for v in _SEARCH.values())


def search(q="", field="all", offset=0, limit=25):
    """이름·팩 이름·태그·그룹 검색(대소문자 무관, 일부 일치). q가 비면 전체. (rows, 전체 개수)"""
    q = (q or "").strip()
    cond = f"AND ({_SEARCH.get(field, _SEARCH['all'])})" if q else ""
    base = f"FROM emojis e JOIN packs p ON p.id=e.pack_id WHERE e.deleted_at IS NULL {cond}"
    with db.conn() as c:
        total = c.execute(f"SELECT count(*) {base}", {"q": q}).fetchone()[0]
        rows = c.execute(f"SELECT {_EMOJI_COLS} {base} ORDER BY lower(e.ename)=lower(:q) DESC, p.id, e.seq "
                         "LIMIT :n OFFSET :o", {"q": q, "n": limit, "o": offset}).fetchall()
    return rows, total


def find(q, limit=25):
    return search(q, "all", 0, limit)[0] if (q or "").strip() else []


def label_names(table, q="", limit=25):
    with db.conn() as c:
        return [r[0] for r in c.execute(f"SELECT name FROM {table} WHERE instr(lower(name), lower(?)) "
                                        "ORDER BY lower(name) LIMIT ?", (q or "", limit))]


def pack_names(q="", limit=25):
    with db.conn() as c:
        return [r[0] for r in c.execute("SELECT DISTINCT name FROM packs WHERE deleted_at IS NULL "
                                        "AND instr(lower(name), lower(?)) ORDER BY lower(name) LIMIT ?",
                                        (q or "", limit))]


# ---------- 그룹 단위 둘러보기 (웹 갤러리, /e pick 공용) ----------
# key: 그룹 id(숫자 문자열), "n" = 그룹 없음, "f" = 자주 쓰는

def _covers(items, n=4):
    """대표 이미지 n개: 서로 다른 팩에서 돌아가며 하나씩 (팩이 적으면 같은 팩에서 더)."""
    by_pack = {}
    for pack_id, f in items:
        by_pack.setdefault(pack_id, []).append(f)
    lists, out, depth = list(by_pack.values()), [], 0
    while len(out) < n and any(depth < len(x) for x in lists):
        out += [x[depth] for x in lists if depth < len(x)][:n - len(out)]
        depth += 1
    return out


def group_overview():
    """그룹별 이모티콘 수와 대표 이미지(최대 4개). 자주 쓰는 / 그룹 없음 포함."""
    with db.conn() as c:
        names = {r["id"]: r["name"] for r in c.execute("SELECT id, name FROM grp")}
        rows = c.execute("""SELECT pg.group_id gid, e.pack_id, e.file FROM emojis e
            LEFT JOIN pack_grp pg ON pg.pack_id=e.pack_id
            WHERE e.deleted_at IS NULL ORDER BY e.pack_id, e.seq""").fetchall()
    members = {}
    for r in rows:
        members.setdefault(r["gid"], []).append((r["pack_id"], r["file"]))

    def item(key, name, items):
        covers = _covers(items)
        return {"key": key, "name": name, "count": len(items), "cover": covers[0], "covers": covers}

    out = []
    fav = group_emojis("f")
    if fav:
        out.append(item("f", "자주 쓰는", [(i, r["file"]) for i, r in enumerate(fav)]))
    out += [item(str(gid), names[gid], items)
            for gid, items in sorted(((g, v) for g, v in members.items() if g in names),
                                     key=lambda x: names[x[0]].lower())]
    if None in members:
        out.append(item("n", "그룹 없음", members[None]))
    return out


def group_name(key):
    if key in ("f", "n"):
        return {"f": "자주 쓰는", "n": "그룹 없음"}[key]
    with db.conn() as c:
        row = c.execute("SELECT name FROM grp WHERE id=?", (key,)).fetchone()
    return row["name"] if row else None


def group_emojis(key):
    """그룹에 속한 모든 이모티콘 (팩 순서, 팩 안 순서). 자주 쓰는 = 최근 30일 많이 쓴 25개."""
    if key == "f":
        return [r for r in popular(25, 30) if r["uses"]]
    if key == "n":
        where = "NOT EXISTS (SELECT 1 FROM pack_grp pg WHERE pg.pack_id=e.pack_id)"
        args = ()
    else:
        where = "EXISTS (SELECT 1 FROM pack_grp pg WHERE pg.pack_id=e.pack_id AND pg.group_id=?)"
        args = (key,)
    with db.conn() as c:
        return c.execute(f"SELECT {_EMOJI_COLS} FROM emojis e JOIN packs p ON p.id=e.pack_id "
                         f"WHERE e.deleted_at IS NULL AND {where} ORDER BY p.id, e.seq", args).fetchall()


def get_emoji_by_id(emoji_id):
    with db.conn() as c:
        return c.execute(f"SELECT {_EMOJI_COLS} FROM emojis e JOIN packs p ON p.id=e.pack_id "
                         "WHERE e.deleted_at IS NULL AND e.id=?", (emoji_id,)).fetchone()


SHEET_CELL = {3: 220, 4: 170, 5: 136}  # 한 줄 칸 수별 칸 크기: 어느 쪽이든 이미지 폭 약 700px


def contact_sheet(rows, cols=4):
    """번호가 붙은 격자 이미지(투명 WebP). 디스코드 버튼 배치(한 줄 cols개)와 같은 모양."""
    return _sheet(tuple(r["file"] for r in rows), cols)


@functools.lru_cache(maxsize=300)  # 같은 쪽을 다시 열면 바로 재사용 (쪽당 수십 KB)
def _sheet(files, cols):
    """배경은 투명(채팅 배경이 비침), 칸 구분용 옅은 테두리 + 노란 번호표."""
    from PIL import ImageDraw, ImageFont
    cell = SHEET_CELL.get(cols, 170)
    gap, pad = 10, 12
    n_rows = max(cols, -(-len(files) // cols))  # 항상 정사각형: 모자란 칸은 비워 두어 쪽마다 크기가 같다
    w = pad * 2 + cols * cell + (cols - 1) * gap
    h = pad * 2 + n_rows * cell + (n_rows - 1) * gap
    navy, badge = (38, 43, 110, 255), (255, 201, 64, 255)
    sheet = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(sheet)
    fs = max(18, cell // 6)
    try:
        font = ImageFont.load_default(size=fs)
    except TypeError:  # 오래된 Pillow
        font = ImageFont.load_default()
    for i, f in enumerate(files):
        x = pad + (i % cols) * (cell + gap)
        y = pad + (i // cols) * (cell + gap)
        draw.rounded_rectangle((x, y, x + cell, y + cell), radius=cell // 10, fill=(255, 255, 255, 18))
        try:
            with Image.open(os.path.join(db.IMG_DIR, f)) as im:
                im.seek(0)
                thumb = im.convert("RGBA")
            thumb.thumbnail((cell - 12, cell - 12), Image.LANCZOS)
            sheet.alpha_composite(thumb, (x + (cell - thumb.width) // 2, y + (cell - thumb.height) // 2))
        except OSError:
            pass
        bw, bh = fs * 2 if i >= 9 else int(fs * 1.5), int(fs * 1.4)
        draw.rounded_rectangle((x + 5, y + 5, x + 5 + bw, y + 5 + bh), radius=bh // 2, fill=badge)
        draw.text((x + 5 + bw / 2, y + 5 + bh / 2), str(i + 1), fill=navy, font=font, anchor="mm")
    out = io.BytesIO()
    # WebP: 투명 배경을 유지하면서 PNG보다 몇 배 작아 업로드가 빠르다
    sheet.save(out, "WEBP", quality=85, method=4)
    return out.getvalue()


def popular(limit=25, days=30):
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    with db.conn() as c:
        return c.execute(
            f"""SELECT {_EMOJI_COLS}, count(u.id) AS uses FROM emojis e JOIN packs p ON p.id=e.pack_id
            LEFT JOIN usage_log u ON u.emoji_id=e.id AND u.used_at>=?
            WHERE e.deleted_at IS NULL GROUP BY e.id ORDER BY uses DESC, e.id DESC LIMIT ?""",
            (since, limit)).fetchall()


def log_usage(emoji_id, discord_id):
    with db.conn() as c:
        c.execute("INSERT INTO usage_log(emoji_id,discord_id,used_at) VALUES (?,?,?)",
                  (emoji_id, discord_id, db.now()))


# ---------- 사용자 ----------

def get_user(discord_id):
    with db.conn() as c:
        return c.execute("SELECT * FROM users WHERE discord_id=? AND deleted_at IS NULL",
                         (str(discord_id),)).fetchone()


def touch_user(discord_id, username):
    """봇을 처음 쓰면 권한 없이 등록된다. 관리자가 웹에서 허용해야 사용 가능."""
    did = str(discord_id)
    with db.conn() as c:
        row = c.execute("SELECT * FROM users WHERE discord_id=?", (did,)).fetchone()
        if row is None:
            c.execute("INSERT INTO users(discord_id,username,add_date) VALUES (?,?,?)", (did, username, db.now()))
        elif row["deleted_at"]:
            c.execute("UPDATE users SET username=?, add_date=?, can_bot=0, can_web=0, deleted_at=NULL "
                      "WHERE discord_id=?", (username, db.now(), did))
        elif row["username"] != username:
            c.execute("UPDATE users SET username=? WHERE discord_id=?", (username, did))
        return c.execute("SELECT * FROM users WHERE discord_id=?", (did,)).fetchone()


def set_pick_cols(discord_id, cols):
    with db.conn() as c:
        c.execute("UPDATE users SET pick_cols=? WHERE discord_id=?", (cols, str(discord_id)))


def create_login_token(discord_id, minutes=10):
    token = secrets.token_urlsafe(32)
    expires = (datetime.now() + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")
    with db.conn() as c:
        c.execute("DELETE FROM login_tokens WHERE expires_at<?", (db.now(),))
        c.execute("INSERT INTO login_tokens VALUES (?,?,?)", (token, str(discord_id), expires))
    return token


def consume_login_token(token):
    """한 번 쓰면 사라지는 로그인 토큰. 유효하면 discord_id를 돌려준다."""
    with db.conn() as c:
        row = c.execute("SELECT * FROM login_tokens WHERE token=?", (token or "",)).fetchone()
        c.execute("DELETE FROM login_tokens WHERE token=? OR expires_at<?", (token or "", db.now()))
    if row and row["expires_at"] >= db.now():
        return row["discord_id"]
    return None


# ---------- 웹 갤러리 ----------
# /e find 를 쓰면 그 명령의 interaction 토큰을 잠시 보관한다. 디스코드는 명령 후 15분 동안
# 이 토큰으로 같은 채널(DM 포함)에 이어서 메시지를 보내는 것을 허용한다. 여유를 두고 14분.
GALLERY_MINUTES = 14


def create_gallery(discord_id, app_id, itoken, q="", field="all"):
    token = secrets.token_urlsafe(24)
    expires = (datetime.now() + timedelta(minutes=GALLERY_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
    with db.conn() as c:
        c.execute("DELETE FROM galleries WHERE expires_at<?", (db.now(),))
        c.execute("INSERT INTO galleries VALUES (?,?,?,?,?,?,?)",
                  (token, str(discord_id), str(app_id), itoken, q or "", field or "all", expires))
    return token


def get_gallery(token):
    """유효한(만료 전, 사용자 권한 유지) 갤러리만 돌려준다."""
    with db.conn() as c:
        row = c.execute("SELECT * FROM galleries WHERE token=? AND expires_at>=?", (token or "", db.now())).fetchone()
    if row is None:
        return None
    user = get_user(row["discord_id"])
    return row if user and user["can_bot"] else None


def seconds_left(row):
    return max(0, int((datetime.strptime(row["expires_at"], "%Y-%m-%d %H:%M:%S") - datetime.now()).total_seconds()))


class DiscordRejected(UserError):
    """디스코드가 이 경로로는 보낼 수 없다고 거절함 (만료·권한 없음). 다른 경로로 다시 시도할 수 있다."""


def _post_file(url, path, auth=None):
    ext = path.rsplit(".", 1)[-1]
    boundary = uuid.uuid4().hex
    with open(path, "rb") as f:
        data = f.read()
    payload = json.dumps({"attachments": [{"id": 0, "filename": f"emoji.{ext}"}]})
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"payload_json\"\r\n"
            f"Content-Type: application/json\r\n\r\n{payload}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"files[0]\"; filename=\"emoji.{ext}\"\r\n"
            f"Content-Type: image/{ext}\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}", "User-Agent": "DiscordBot (emoji-bot, 1.0)"}
    if auth:
        headers["Authorization"] = auth
    try:
        urllib.request.urlopen(urllib.request.Request(url, data=body, method="POST", headers=headers), timeout=20).close()
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise UserError("너무 빠르게 보냈어요. 잠깐 뒤에 다시 눌러 주세요.")
        if e.code in (400, 401, 403, 404):
            raise DiscordRejected(f"디스코드가 보내기를 거절했어요 (HTTP {e.code}).")
        raise UserError(f"디스코드로 보내지 못했어요 (HTTP {e.code}).")
    except urllib.error.URLError:
        raise UserError("디스코드 서버에 연결하지 못했어요. 잠시 뒤 다시 시도해 주세요.")


def post_followup(app_id, itoken, path):
    """명령을 쓴 채널에 이미지를 보낸다 (interaction followup 웹훅, 명령 후 15분 동안)."""
    try:
        _post_file(f"https://discord.com/api/v10/webhooks/{app_id}/{itoken}", path)
    except DiscordRejected:
        raise UserError("디스코드 연결이 만료됐어요. 디스코드에서 명령을 다시 써 주세요.")


def post_as_bot(channel_id, path):
    """봇이 들어가 있는 서버 채널(또는 봇과의 DM)에 봇 토큰으로 보낸다."""
    _post_file(f"https://discord.com/api/v10/channels/{channel_id}/messages", path,
               auth=f"Bot {os.environ['BOT_TOKEN']}")


# ---------- 디스코드 액티비티 (/e pick) ----------
# 액티비티 창은 디스코드 로그인(OAuth)으로 사용자를 확인하고, 이후 요청은 자체 세션 토큰으로 받는다.
# 보내기: /e pick 명령의 interaction 토큰(15분) → 안 되면 봇 토큰으로 채널에 직접(서버 채널만 가능).

def activity_enabled():
    return bool(os.environ.get("DISCORD_CLIENT_SECRET"))


def record_launch(discord_id, channel_id, app_id, itoken):
    expires = (datetime.now() + timedelta(minutes=GALLERY_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
    with db.conn() as c:
        c.execute("DELETE FROM pick_launches WHERE expires_at<?", (db.now(),))
        c.execute("INSERT OR REPLACE INTO pick_launches VALUES (?,?,?,?,?)",
                  (str(discord_id), str(channel_id), str(app_id), itoken, expires))


def _discord_json(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "DiscordBot (emoji-bot, 1.0)", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise UserError(f"디스코드 로그인에 실패했어요 (HTTP {e.code}). 창을 닫고 다시 열어 주세요.")
    except urllib.error.URLError:
        raise UserError("디스코드 서버에 연결하지 못했어요.")


def activity_login(code, username_hint=None):
    """OAuth code → access_token → 사용자 확인 → 세션 발급. (access_token, session, user row)"""
    if not code:
        raise UserError("로그인 정보가 없어요.")
    tok = _discord_json("https://discord.com/api/v10/oauth2/token", data=urllib.parse.urlencode({
        "client_id": os.environ["DISCORD_CLIENT_ID"], "client_secret": os.environ["DISCORD_CLIENT_SECRET"],
        "grant_type": "authorization_code", "code": code}).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    me = _discord_json("https://discord.com/api/v10/users/@me",
                       headers={"Authorization": f"Bearer {tok['access_token']}"})
    user = touch_user(me["id"], me.get("username") or username_hint or me["id"])
    session = secrets.token_urlsafe(24)
    expires = (datetime.now() + timedelta(hours=12)).strftime("%Y-%m-%d %H:%M:%S")
    with db.conn() as c:
        c.execute("DELETE FROM activity_sessions WHERE expires_at<?", (db.now(),))
        c.execute("INSERT INTO activity_sessions VALUES (?,?,?)", (session, me["id"], expires))
    return tok["access_token"], session, user


def activity_user(session):
    """유효한 세션이고 봇 사용 권한이 있으면 사용자 row."""
    with db.conn() as c:
        row = c.execute("SELECT discord_id FROM activity_sessions WHERE token=? AND expires_at>=?",
                        (session or "", db.now())).fetchone()
    if row is None:
        return None
    user = get_user(row["discord_id"])
    return user if user and user["can_bot"] else None


def activity_send(discord_id, channel_id, emoji_id):
    emoji = get_emoji_by_id(emoji_id)
    if emoji is None:
        raise UserError("삭제된 이모티콘이에요.")
    path = os.path.join(db.IMG_DIR, emoji["file"])
    with db.conn() as c:
        launch = c.execute("SELECT * FROM pick_launches WHERE discord_id=? AND channel_id=? AND expires_at>=?",
                           (str(discord_id), str(channel_id), db.now())).fetchone()
    sent = False
    if launch:
        try:
            _post_file(f"https://discord.com/api/v10/webhooks/{launch['app_id']}/{launch['itoken']}", path)
            sent = True
        except DiscordRejected:
            pass  # 아래에서 봇으로 다시 시도
    if not sent:
        try:
            post_as_bot(channel_id, path)
        except DiscordRejected:
            raise UserError("이 대화방에는 보낼 수 없어요. 대화방에서 /e pick 을 다시 써서 창을 열어 주세요 "
                            "(열고 나서 14분 동안 보낼 수 있어요).")
    log_usage(emoji["id"], str(discord_id))
