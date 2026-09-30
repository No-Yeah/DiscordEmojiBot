"""관리자 웹 (Flask). gunicorn emojibot.web:app 으로 실행."""
import math
import os
import re
import time
from datetime import datetime, timedelta
from functools import wraps

from flask import (Flask, abort, g, jsonify, redirect, render_template, request,
                   send_from_directory, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from . import core, db

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    MAX_CONTENT_LENGTH=12 * 1024 * 1024,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
)
db.init()

PAGE_SIZE = 30
PUBLIC = {"login", "login_discord", "static"}
_fails = {}  # ip -> (실패 횟수, 첫 실패 시각). ponytail: 워커 1개 기준 메모리 카운터


# ---------- 인증 ----------

def current_user():
    if session.get("admin"):
        with db.conn() as c:
            row = c.execute("SELECT username FROM admin WHERE id=1").fetchone()
        return {"admin": True, "name": row["username"] if row else "admin"}
    did = session.get("discord_id")
    if did:
        u = core.get_user(did)
        if u and u["can_web"]:
            return {"admin": False, "name": u["username"] or did}
    session.clear()
    return None


@app.before_request
def guard():
    if request.endpoint in PUBLIC:
        return None
    g.me = current_user()
    if not g.me:
        if request.path.startswith("/api/"):
            return jsonify(error="로그인이 필요합니다."), 401
        return redirect(url_for("login"))
    # CSRF 방어: 변경 요청은 모두 fetch(X-Requested-With 헤더)로만 받는다
    if request.method == "POST" and request.headers.get("X-Requested-With") != "fetch":
        abort(400)
    return None


def admin_only(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not g.me["admin"]:
            if request.path.startswith("/api/"):
                return jsonify(error="관리자 계정만 할 수 있습니다."), 403
            abort(403)
        return fn(*a, **kw)
    return wrapper


@app.errorhandler(core.UserError)
def user_error(e):
    return jsonify(error=str(e)), 400


def arg(name, default=None):
    j = request.get_json(silent=True) or {}
    return j.get(name, request.form.get(name, default))


def ok(**kw):
    return jsonify(ok=True, **kw)


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        ip = request.remote_addr or "?"
        count, first = _fails.get(ip, (0, 0.0))
        if time.time() - first > 300:
            count, first = 0, time.time()
        if count >= 5:
            error = "로그인에 5번 실패했습니다. 5분 뒤 다시 시도하세요."
        else:
            with db.conn() as c:
                row = c.execute("SELECT * FROM admin WHERE id=1").fetchone()
            if row and request.form.get("username") == row["username"] and \
                    check_password_hash(row["pw_hash"], request.form.get("password", "")):
                _fails.pop(ip, None)
                session.clear()
                session.permanent = True
                session["admin"] = True
                return redirect(url_for("dashboard"))
            _fails[ip] = (count + 1, first)
            time.sleep(1)
            error = "아이디 또는 비밀번호가 맞지 않습니다."
    return render_template("login.html", error=error)


@app.route("/login/discord")
def login_discord():
    did = core.consume_login_token(request.args.get("token"))
    u = core.get_user(did) if did else None
    if not u or not u["can_web"]:
        return render_template("login.html", error="로그인 링크가 만료됐거나 웹 권한이 없습니다. 디스코드에서 /e web 으로 새 링크를 받으세요.")
    session.clear()
    session.permanent = True
    session["discord_id"] = did
    return redirect(url_for("dashboard"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/img/<path:name>")
def image(name):
    if not re.fullmatch(r"[0-9a-f]{32}\.(png|gif)", name):
        abort(404)
    return send_from_directory(db.IMG_DIR, name, max_age=86400)


# ---------- 대시보드 ----------

RANGES = {"day": ("하루", 1), "week": ("일주일", 7), "month": ("한 달", 30)}


@app.route("/")
def dashboard():
    today = datetime.now().strftime("%Y-%m-%d")
    rng = request.args.get("range", "day")
    if rng not in RANGES:
        rng = "day"
    since = (datetime.now() - timedelta(days=RANGES[rng][1])).strftime("%Y-%m-%d %H:%M:%S")
    with db.conn() as c:
        emo = c.execute("""SELECT
            sum(deleted_at IS NULL) total, sum(add_date>=:t) new, sum(deleted_at>=:t) deleted,
            (SELECT count(*) FROM packs WHERE kind='pack' AND deleted_at IS NULL) packs
            FROM emojis""", {"t": today}).fetchone()
        usr = c.execute("""SELECT sum(deleted_at IS NULL) total, sum(add_date>=:t AND deleted_at IS NULL) new,
            sum(deleted_at>=:t) deleted, sum(deleted_at IS NULL AND can_bot) allowed FROM users""",
                        {"t": today}).fetchone()
        new_today = c.execute("""SELECT e.ename, e.file, p.name pack FROM emojis e JOIN packs p ON p.id=e.pack_id
            WHERE e.deleted_at IS NULL AND e.add_date>=? ORDER BY e.id DESC LIMIT 40""", (today,)).fetchall()
        top_emoji = c.execute("""SELECT e.ename, e.file, count(*) n FROM usage_log u JOIN emojis e ON e.id=u.emoji_id
            WHERE u.used_at>=? AND e.deleted_at IS NULL GROUP BY e.id ORDER BY n DESC LIMIT 5""", (since,)).fetchall()
        top_user = c.execute("""SELECT coalesce(us.username, u.discord_id) name, count(*) n FROM usage_log u
            LEFT JOIN users us ON us.discord_id=u.discord_id WHERE u.used_at>=?
            GROUP BY u.discord_id ORDER BY n DESC LIMIT 5""", (since,)).fetchall()
    return render_template("dashboard.html", emo=emo, usr=usr, new_today=new_today, top_emoji=top_emoji,
                           top_user=top_user, rng=rng, ranges=RANGES, today=today)


# ---------- 이모티콘 목록 ----------

SORTS = {
    "no": "p.id", "group": "grp_names", "name": "lower(p.name)", "url": "p.url", "date": "p.add_date",
    "ename": "first_ename", "tag": "single_tags", "user": "p.add_user",
}


@app.route("/emojis")
def emojis():
    q = request.args.get("q", "").strip()
    sort = request.args.get("sort", "no")
    sort = sort if sort in SORTS else "no"
    direction = "asc" if request.args.get("dir", "asc") == "asc" else "desc"
    page = max(1, request.args.get("page", 1, type=int))
    where, params = "", {"q": q}
    if q:
        where = """AND (instr(lower(p.name), lower(:q)) OR instr(lower(ifnull(p.url,'')), lower(:q))
          OR EXISTS (SELECT 1 FROM pack_grp pg JOIN grp g ON g.id=pg.group_id
                     WHERE pg.pack_id=p.id AND instr(lower(g.name), lower(:q)))
          OR EXISTS (SELECT 1 FROM emojis e WHERE e.pack_id=p.id AND e.deleted_at IS NULL AND (
               instr(lower(e.ename), lower(:q)) OR EXISTS (SELECT 1 FROM emoji_tags et JOIN tags t ON t.id=et.tag_id
                                                         WHERE et.emoji_id=e.id AND instr(t.name, :q)))))"""
    with db.conn() as c:
        total = c.execute(f"SELECT count(*) FROM packs p WHERE p.deleted_at IS NULL {where}", params).fetchone()[0]
        pages = max(1, math.ceil(total / PAGE_SIZE))
        page = min(page, pages)
        packs = c.execute(f"""SELECT p.*,
            (SELECT group_concat(g.name, ', ') FROM pack_grp pg JOIN grp g ON g.id=pg.group_id WHERE pg.pack_id=p.id) grp_names,
            (SELECT min(e.ename) FROM emojis e WHERE e.pack_id=p.id AND e.deleted_at IS NULL) first_ename,
            (SELECT group_concat(t.name, ', ') FROM emojis e JOIN emoji_tags et ON et.emoji_id=e.id
               JOIN tags t ON t.id=et.tag_id WHERE e.pack_id=p.id AND p.kind='single') single_tags,
            (SELECT count(*) FROM emojis e WHERE e.pack_id=p.id AND e.deleted_at IS NULL) cnt
            FROM packs p WHERE p.deleted_at IS NULL {where}
            ORDER BY {SORTS[sort]} {direction}, p.id LIMIT :n OFFSET :o""",
                          {**params, "n": PAGE_SIZE, "o": (page - 1) * PAGE_SIZE}).fetchall()
        ids = [p["id"] for p in packs]
        items = {}
        if ids:
            marks = ",".join("?" * len(ids))
            for e in c.execute(f"""SELECT e.*, (SELECT group_concat(t.name, ', ') FROM emoji_tags et
                    JOIN tags t ON t.id=et.tag_id WHERE et.emoji_id=e.id) tags
                    FROM emojis e WHERE e.deleted_at IS NULL AND e.pack_id IN ({marks}) ORDER BY e.seq""", ids):
                items.setdefault(e["pack_id"], []).append(e)
        labels = {"tag": [r[0] for r in c.execute("SELECT name FROM tags ORDER BY name")],
                  "group": [r[0] for r in c.execute("SELECT name FROM grp ORDER BY lower(name)")]}
    return render_template("emojis.html", packs=packs, items=items, q=q, sort=sort, direction=direction,
                           page=page, pages=pages, total=total, labels=labels)


@app.post("/api/pack")
def api_add_pack():
    n = core.add_pack(arg("url"), arg("name"), "WEB")
    return ok(count=n)


@app.post("/api/single")
def api_add_single():
    f = request.files.get("file")
    if f and f.filename:
        data = f.read()
    elif arg("image_url"):
        data = core.fetch(arg("image_url"))
    else:
        raise core.UserError("이미지를 올리거나 붙여넣거나, 이미지 URL을 입력하세요.")
    ename = core.add_single(arg("ename"), data, "WEB", arg("name"), arg("groups"), arg("tags"))
    return ok(ename=ename)


@app.post("/api/pack/<int:pid>/groups")
def api_pack_groups(pid):
    core.set_groups(pid, arg("items"))
    return ok()


@app.post("/api/pack/<int:pid>/rename")
def api_pack_rename(pid):
    core.rename_pack(pid, arg("name"))
    return ok()


@app.post("/api/pack/<int:pid>/delete")
def api_pack_delete(pid):
    return ok(count=core.delete_emojis("pack_id", pid))


@app.post("/api/emoji/<int:eid>/tags")
def api_emoji_tags(eid):
    core.set_tags(eid, arg("items"))
    return ok()


@app.post("/api/emoji/<int:eid>/rename")
def api_emoji_rename(eid):
    core.rename_emoji(eid, arg("name"))
    return ok()


@app.post("/api/emoji/<int:eid>/delete")
def api_emoji_delete(eid):
    return ok(count=core.delete_emojis("emoji_id", eid))


# ---------- 그룹 / 태그 관리 ----------

@app.route("/groups")
def groups():
    with db.conn() as c:
        rows = c.execute("""SELECT g.id, g.name,
            coalesce(sum(p.kind='pack'), 0) packs, coalesce(sum(p.kind='single'), 0) singles
            FROM grp g LEFT JOIN pack_grp pg ON pg.group_id=g.id
            LEFT JOIN packs p ON p.id=pg.pack_id AND p.deleted_at IS NULL
            GROUP BY g.id ORDER BY lower(g.name)""").fetchall()
    return render_template("labels.html", kind="group", rows=rows)


@app.route("/tags")
def tags():
    with db.conn() as c:
        rows = c.execute("""SELECT t.id, t.name, count(e.id) emojis FROM tags t
            LEFT JOIN emoji_tags et ON et.tag_id=t.id LEFT JOIN emojis e ON e.id=et.emoji_id AND e.deleted_at IS NULL
            GROUP BY t.id ORDER BY t.name""").fetchall()
    return render_template("labels.html", kind="tag", rows=rows)


def _table(kind):
    if kind not in ("group", "tag"):
        abort(404)
    return "grp" if kind == "group" else "tags"


@app.post("/api/<kind>")
def api_label_add(kind):
    core.add_label(_table(kind), arg("name"))
    return ok()


@app.post("/api/<kind>/<int:lid>/rename")
def api_label_rename(kind, lid):
    core.rename_label(_table(kind), lid, arg("name"))
    return ok()


@app.post("/api/<kind>/<int:lid>/delete")
def api_label_delete(kind, lid):
    core.delete_label(_table(kind), label_id=lid)
    return ok()


# ---------- 디스코드 유저 ----------

@app.route("/users")
@admin_only
def users():
    with db.conn() as c:
        rows = c.execute("SELECT * FROM users WHERE deleted_at IS NULL ORDER BY add_date").fetchall()
    return render_template("users.html", rows=rows)


@app.post("/api/user")
@admin_only
def api_user_add():
    did = (arg("discord_id") or "").strip()
    if not re.fullmatch(r"\d{15,21}", did):
        raise core.UserError("디스코드 ID는 15~21자리 숫자입니다. (디스코드 개발자 모드 → 프로필 우클릭 → ID 복사)")
    core.touch_user(did, (arg("username") or "").strip() or did)
    return ok()


@app.post("/api/user/<did>/perm")
@admin_only
def api_user_perm(did):
    field = arg("field")
    if field not in ("can_bot", "can_web"):
        abort(400)
    with db.conn() as c:
        c.execute(f"UPDATE users SET {field}=? WHERE discord_id=?", (1 if arg("value") else 0, did))
    return ok()


@app.post("/api/user/<did>/delete")
@admin_only
def api_user_delete(did):
    with db.conn() as c:
        c.execute("UPDATE users SET deleted_at=?, can_bot=0, can_web=0 WHERE discord_id=?", (db.now(), did))
    return ok()


# ---------- 관리자 계정 ----------

@app.route("/account")
@admin_only
def account():
    return render_template("account.html")


@app.post("/api/account")
@admin_only
def api_account():
    with db.conn() as c:
        row = c.execute("SELECT * FROM admin WHERE id=1").fetchone()
        if not check_password_hash(row["pw_hash"], arg("current_password") or ""):
            raise core.UserError("현재 비밀번호가 맞지 않습니다.")
        username = (arg("username") or "").strip() or row["username"]
        if not re.fullmatch(r"[\w.\-]{3,32}", username):
            raise core.UserError("아이디는 3~32자(영문, 숫자, _, ., -)로 입력하세요.")
        new_pw = arg("new_password") or ""
        if new_pw and len(new_pw) < 8:
            raise core.UserError("새 비밀번호는 8자 이상이어야 합니다.")
        pw_hash = generate_password_hash(new_pw) if new_pw else row["pw_hash"]
        c.execute("UPDATE admin SET username=?, pw_hash=? WHERE id=1", (username, pw_hash))
    return ok()
