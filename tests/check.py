"""의존성 없이 돌리는 최소 검증: python3 tests/check.py
네트워크 없이 파싱, 이미지 변환, 추가/검색/삭제 흐름을 확인한다."""
import io
import os
import sys
import tempfile

os.environ["EMOJI_DATA"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402

from emojibot import core, db  # noqa: E402

db.init()

# 1) 카카오 페이지 파싱: 가장 많이 나온 앞 32자리 묶음만 팩 이미지로 고른다
P, O = "a" * 32, "b" * 32
html = (f'<img src="https://item.kakaocdn.net/do/{O}{"1" * 32}">'
        + "".join(f'<img src="https://item.kakaocdn.net/do/{P}{i:032x}">' for i in range(3))
        + f'<img src="https://item.kakaocdn.net/do/{O}{"2" * 32}-g">'
        + f'<img src="https://item.kakaocdn.net/do/{P}{0:032x}">')
urls = core.parse_kakao(html)
assert urls == [f"https://item.kakaocdn.net/do/{P}{i:032x}" for i in range(3)], urls

# 2) 검증 규칙
assert core.parse_tags("기쁨, 슬픔,기쁨") == ["기쁨", "슬픔"]
for bad in ("happy", "기쁨1", "기 쁨"):
    try:
        core.parse_tags(bad)
        raise AssertionError(bad)
    except core.UserError:
        pass
for bad in ("find", "a b", "-x", ""):
    try:
        core.check_name(bad, "이름")
        raise AssertionError(bad)
    except core.UserError:
        pass


# 3) 이미지: 긴 변 180px, 움직이는 이미지는 GIF 유지 + 투명 유지
def png(w, h):
    b = io.BytesIO()
    Image.new("RGBA", (w, h), (255, 0, 0, 255)).save(b, "PNG")
    return b.getvalue()


body, ext = core.process_image(png(360, 240))
assert ext == "png" and Image.open(io.BytesIO(body)).size == (180, 120)

frames = []
for i in range(3):
    f = Image.new("RGBA", (100, 50), (0, 0, 0, 0))
    f.paste((0, 200, 0, 255), (i * 20, 10, i * 20 + 20, 40))
    frames.append(f)
b = io.BytesIO()
frames[0].save(b, "GIF", save_all=True, append_images=frames[1:], duration=80, loop=0, disposal=2)
body, ext = core.process_image(b.getvalue())
gif = Image.open(io.BytesIO(body))
assert ext == "gif" and gif.n_frames == 3 and gif.size == (180, 90), (ext, gif.size)
for i in range(3):
    gif.seek(i)
    assert gif.convert("RGBA").getpixel((170, 5))[3] == 0, f"{i}번 프레임 투명 배경이 사라짐"
b = io.BytesIO()  # 움직이는 WebP도 GIF로
frames[0].save(b, "WEBP", save_all=True, append_images=frames[1:], duration=80, loop=0)
body, ext = core.process_image(b.getvalue())
assert ext == "gif" and Image.open(io.BytesIO(body)).n_frames == 3

# 4) 추가 → 검색 → 태그/그룹 → 삭제 흐름과 대시보드용 삭제 기록
try:  # 등록되지 않은 태그·그룹은 붙일 수 없다 (오타 방지)
    core.add_single("후다닥", png(200, 200), "tester", tags="달리기")
    raise AssertionError("없는 태그 허용됨")
except core.UserError:
    pass
for t in ("달리기", "급함", "인사"):
    core.add_label("tags", t)
core.add_label("grp", "다람쥐")
core.add_single("후다닥", png(200, 200), "tester", groups="다람쥐", tags="달리기,급함")
core.add_single("꾸벅", png(200, 200), "tester", name="인사팩", tags="인사")
assert [r["ename"] for r in core.find("달리")] == ["후다닥"]
assert [r["ename"] for r in core.find("인사팩")] == ["꾸벅"]
try:
    core.add_single("후다닥", png(10, 10), "tester")
    raise AssertionError("중복 허용됨")
except core.UserError:
    pass
rows, total = core.search("다람", "group")
assert total == 1 and rows[0]["ename"] == "후다닥"
assert core.search("", "all", 0, 1)[1] == 2 and len(core.search("", "all", 0, 1)[0]) == 1
assert core.search("달리", "name")[1] == 0
assert core.delete_label("tags", name="급함") == 1
assert core.get_emoji("후다닥")["tags"] == "달리기"
assert core.count_targets("group", "다람쥐") == 1
assert core.delete_emojis("group", "다람쥐") == 1
assert core.get_emoji("후다닥") is None
with db.conn() as c:
    assert c.execute("SELECT count(*) FROM emojis WHERE deleted_at IS NOT NULL").fetchone()[0] == 1
    assert c.execute("SELECT count(*) FROM packs WHERE deleted_at IS NULL").fetchone()[0] == 1
core.add_single("후다닥", png(10, 10), "tester")  # 삭제 후 같은 이름 재사용 가능

# 5) 로그인 토큰은 한 번만
t = core.create_login_token("123456789012345678")
assert core.consume_login_token(t) == "123456789012345678"
assert core.consume_login_token(t) is None

# 6) 갤러리 링크: 권한 있는 사용자만, 만료되면 무효
core.touch_user("123456789012345678", "tester")
gt = core.create_gallery("123456789012345678", "999", "itoken", "후다", "name")
assert core.get_gallery(gt) is None, "권한 없는 사용자 링크가 열림"
with db.conn() as c:
    c.execute("UPDATE users SET can_bot=1 WHERE discord_id='123456789012345678'")
assert core.get_gallery(gt)["q"] == "후다" and 0 < core.seconds_left(core.get_gallery(gt)) <= 14 * 60
with db.conn() as c:
    c.execute("UPDATE galleries SET expires_at='2000-01-01 00:00:00'")
assert core.get_gallery(gt) is None, "만료된 링크가 열림"

# 7) 내부망 주소 차단
try:
    core.fetch("http://127.0.0.1/x.png")
    raise AssertionError("내부망 허용됨")
except core.UserError:
    pass

print("모든 검증 통과")
