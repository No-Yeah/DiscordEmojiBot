"""디스코드 봇. /e 를 입력하면 하위 명령과 입력 칸이 차례로 나온다.

/e send      이모티콘 보내기 (이름 자동완성)
/e find      웹 갤러리 링크 (그룹 → 이모티콘, 또는 검색) → 누르면 채널로 바로 전송
/e pick      디스코드 안에서 그룹 → 번호 격자로 골라 보내기
/e add-pack  카카오 이모티콘 팩 추가
/e add       단일 이모티콘 추가 (그룹·태그는 등록된 것 중에서 자동완성)
/e del-pack  이름·태그·그룹 기준으로 이모티콘 여러 개 삭제
/e del       이모티콘 1개, 또는 태그·그룹 이름만 삭제
/e web       관리자 웹 로그인 링크
/e help      사용법
"""
import asyncio
import io
import logging
import math
import os

import discord
from discord import app_commands
from discord.app_commands import Choice

from . import core, db

log = logging.getLogger("emojibot")
BASE_URL = os.environ.get("WEB_BASE_URL", "http://localhost:8080").rstrip("/")
MAX_UPLOAD = 10 * 1024 * 1024
NOTICE_SECONDS = 20        # 완료 안내가 사라지기까지의 시간

FIELDS = [Choice(name="전체", value="all"), Choice(name="이름", value="name"),
          Choice(name="태그", value="tag"), Choice(name="그룹", value="group")]
FIELD_LABEL = {"all": "전체", "name": "이름", "tag": "태그", "group": "그룹", "emoji": "이모티콘"}


class Bot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.none())  # 슬래시 명령만 쓰므로 특권 인텐트 불필요
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        self.add_dynamic_items(SendButton, NavButton, SizeButton, HomeButton, GroupButton, HomePageButton,
                               GroupSelect, JumpSelect)
        self.tree.add_command(e)
        await self.tree.sync()
        log.info("슬래시 명령 동기화 완료")


class EGroup(app_commands.Group):
    async def interaction_check(self, inter):
        return bool(await allowed(inter))  # 권한이 없으면 allowed()가 안내 후 False


async def on_tree_error(inter, error):
    err = getattr(error, "original", error)
    if isinstance(err, app_commands.CheckFailure):
        return  # 권한 안내는 이미 보냄
    if isinstance(err, core.UserError):
        return await reply(inter, f"⚠️ {err}")
    log.error("명령 처리 실패", exc_info=err)
    await reply(inter, "처리 중 오류가 발생했습니다. 관리자에게 서버 로그 확인을 요청하세요.")


bot = Bot()
bot.tree.on_error = on_tree_error
e = EGroup(
    name="e", description="이모티콘 봇",
    allowed_installs=app_commands.AppInstallationType(guild=True, user=True),
    allowed_contexts=app_commands.AppCommandContext(guild=True, dm_channel=True, private_channel=True),
)


# ---------- 공통 ----------

async def reply(inter, text=None, *, fade=False, **kwargs):
    """나만 보이는 메시지. fade=True면 잠시 뒤 스스로 사라진다."""
    kwargs["ephemeral"] = True
    if inter.response.is_done():
        msg = await inter.followup.send(text, wait=True, **kwargs)
        if fade:
            await msg.delete(delay=NOTICE_SECONDS)
    else:
        await inter.response.send_message(text, delete_after=NOTICE_SECONDS if fade else None, **kwargs)


async def allowed(inter):
    user = await asyncio.to_thread(core.get_user, inter.user.id)
    if user is None or user["username"] != inter.user.name:  # 처음 쓰거나 이름이 바뀐 경우만 기록
        user = await asyncio.to_thread(core.touch_user, inter.user.id, inter.user.name)
    if not user["can_bot"]:
        await reply(inter, f"아직 사용 권한이 없습니다. 관리자에게 승인을 요청하세요. (내 디스코드 ID: {inter.user.id})")
        return None
    return user


async def can_autocomplete(inter):
    user = await asyncio.to_thread(core.get_user, inter.user.id)
    return bool(user and user["can_bot"])


async def send_emoji(inter, row):
    path = os.path.join(db.IMG_DIR, row["file"])
    ext = row["file"].rsplit(".", 1)[-1]
    await inter.response.send_message(file=discord.File(path, filename=f"emoji.{ext}"))
    await asyncio.to_thread(core.log_usage, row["id"], str(inter.user.id))


def choices(names, current=""):
    return [Choice(name=n[:100], value=n[:100]) for n in names][:25]


def multi_choices(names_fn, current):
    """'기쁨, 인' 처럼 쉼표로 여러 개 입력할 때 마지막 항목만 자동완성한다."""
    head, _, last = current.rpartition(",")
    done = [x.strip() for x in head.split(",") if x.strip()]
    prefix = ", ".join(done) + (", " if done else "")
    out = []
    for n in names_fn(last.strip()):
        if n not in done:
            out.append(Choice(name=(prefix + n)[:100], value=(prefix + n)[:100]))
    return out[:25]


# ---------- 웹 갤러리 ----------

async def show_gallery(inter, q="", field="all", intro=None):
    """조건에 맞는 이모티콘이 있으면 웹 갤러리 링크를 나만 보이게 보낸다."""
    _, total = await asyncio.to_thread(core.search, q, field, 0, 1)
    if not total:
        return await reply(inter, f"'{q}' 검색 결과가 없습니다." if q else
                           "아직 등록된 이모티콘이 없습니다. `/e add-pack`으로 추가하세요.", fade=True)
    token = await asyncio.to_thread(core.create_gallery, inter.user.id, inter.application_id, inter.token, q, field)
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="갤러리 열기", url=f"{BASE_URL}/g/{token}", emoji="🖼️"))
    head = intro or (f"**'{q}'** {FIELD_LABEL[field]} 검색 결과 {total}개" if q else f"전체 이모티콘 {total}개")
    await reply(inter, f"{head}\n갤러리에서 이모티콘을 누르면 이 채널에 바로 보내집니다. "
                       f"(링크는 {core.GALLERY_MINUTES}분 동안, 나만 쓸 수 있어요)", view=view)


class ConfirmView(discord.ui.View):
    def __init__(self, action, done):
        super().__init__(timeout=60)
        self.action, self.done = action, done

    @discord.ui.button(label="삭제", style=discord.ButtonStyle.danger)
    async def ok(self, inter, _button):
        try:
            result = await asyncio.to_thread(self.action)
        except core.UserError as err:
            return await inter.response.edit_message(content=f"⚠️ {err}", view=None)
        await inter.response.edit_message(content=self.done.format(n=result), view=None,
                                          delete_after=NOTICE_SECONDS)

    @discord.ui.button(label="취소", style=discord.ButtonStyle.secondary)
    async def cancel(self, inter, _button):
        await inter.response.edit_message(content="삭제를 취소했습니다.", view=None, delete_after=NOTICE_SECONDS)


# ---------- 명령 ----------

@e.command(name="send", description="이모티콘 보내기")
@app_commands.rename(ename="이모티콘")
@app_commands.describe(ename="이름·팩 이름·태그 일부를 입력하면 목록이 나옵니다")
async def cmd_send(inter: discord.Interaction, ename: str):
    row = await asyncio.to_thread(core.get_emoji, ename)
    if row:
        return await send_emoji(inter, row)
    await show_gallery(inter, ename, intro=f"'{ename}'과 정확히 같은 이름은 없어서 비슷한 결과를 모았습니다.")


@cmd_send.autocomplete("ename")
async def ac_send(inter, current: str):
    if not await can_autocomplete(inter):
        return []
    rows = await asyncio.to_thread(core.find, current) if current else await asyncio.to_thread(core.popular, 25)
    return [Choice(name=f"{r['ename']}  ({r['pack']})" + (f"  #{r['tags']}" if r["tags"] else ""),
                   value=r["ename"][:100]) for r in rows][:25]


@e.command(name="find", description="웹 갤러리 열기: 그룹을 고르거나 검색해서 누르면 바로 전송")
async def cmd_find(inter: discord.Interaction):
    await show_gallery(inter, intro="이모티콘 갤러리")


# ---------- /e pick: 디스코드 안에서 그룹 → 이모티콘 고르기 ----------
# 디스코드 메시지는 안에서 스크롤할 수 없고 한 메시지에 넣을 수 있는 부품은 40개까지라서
# '격자 이미지 1장 + 같은 배치의 번호 버튼 25개 + 팩 바로가기 + 이전/다음' 으로 구성한다.
# 버튼 custom_id 에 상태를 담아(DynamicItem) 봇이 재시작돼도 열려 있던 창이 계속 동작한다.
SIZES = {3: "크게", 4: "보통", 5: "많이"}  # 한 줄 칸 수 → 이름. 한 쪽 = 칸 수 × 칸 수 (정사각형 격자)
NEXT_SIZE = {3: 4, 4: 5, 5: 3}


def size_of(cols):
    cols = int(cols)
    return cols if cols in SIZES else 4


HOME_ALL = 30    # 그룹이 이만큼 이하면 한 화면에 전부 (버튼 5개 × 6줄)
HOME_PAGE = 25   # 넘으면 25개씩 + 이전/다음


async def pick_home_view(page=0):
    """그룹을 버튼으로 한 화면에 펼쳐 보여준다 (드롭다운은 25개 제한이라 쓰지 않음)."""
    groups = await asyncio.to_thread(core.group_overview)
    view = discord.ui.LayoutView(timeout=None)
    if not groups:
        view.add_item(discord.ui.TextDisplay("아직 등록된 이모티콘이 없습니다. `/e add-pack`으로 추가하세요."))
        return view
    per = HOME_ALL if len(groups) <= HOME_ALL else HOME_PAGE
    pages = math.ceil(len(groups) / per)
    page = max(0, min(page, pages - 1))
    chunk = groups[page * per:(page + 1) * per]
    head = f"### 그룹을 고르세요  ({len(groups)}개)" + (f"  {page + 1}/{pages}" if pages > 1 else "")
    view.add_item(discord.ui.TextDisplay(head))
    for i in range(0, len(chunk), 5):
        view.add_item(discord.ui.ActionRow(*[GroupButton(g["key"], f"{g['name']} {g['count']}") for g in chunk[i:i + 5]]))
    if pages > 1:
        view.add_item(discord.ui.ActionRow(HomePageButton(page - 1, "◀", page == 0, "p"),
                                           HomePageButton(page + 1, "▶", page >= pages - 1, "n")))
    return view


def pack_pages(rows, per):
    """쪽 나누기: 한 쪽에는 한 팩의 이모티콘만. 팩이 끝나면 남은 칸은 비워 둔다.
    단일 이모티콘은 하나씩 따로 쪽을 차지하지 않게 '단일 이모티콘'으로 모은다."""
    packs = {}
    for r in rows:
        packs.setdefault(r["pack"] if r["kind"] == "pack" else "단일 이모티콘", []).append(r)
    pages = []
    for name, items in packs.items():
        for i in range(0, len(items), per):
            pages.append((name, i, len(items), items[i:i + per]))
    return pages


async def pick_group_view(key, page, cols, anchor=None):
    """anchor(이모티콘 id)를 주면 그 이모티콘이 들어 있는 쪽을 연다 (크기를 바꿀 때 위치 유지)."""
    cols = size_of(cols)
    rows = await asyncio.to_thread(core.group_emojis, key)
    name = await asyncio.to_thread(core.group_name, key)
    view = discord.ui.LayoutView(timeout=None)
    if not rows or name is None:
        view.add_item(discord.ui.TextDisplay("이 그룹에는 이모티콘이 없습니다."))
        view.add_item(discord.ui.ActionRow(HomeButton()))
        return view, None, []
    per = cols * cols
    if key == "f":  # 자주 쓰는: 팩과 상관없이 많이 쓴 순서대로
        pages = [("자주 쓰는", i, len(rows), rows[i:i + per]) for i in range(0, len(rows), per)]
    else:
        pages = pack_pages(rows, per)
    if anchor is not None:
        page = next((n for n, pg in enumerate(pages) if any(r["id"] == anchor for r in pg[3])), 0)
    page = max(0, min(page, len(pages) - 1))
    pack, start, size, chunk = pages[page]
    view.add_item(discord.ui.TextDisplay(
        f"### {name}  {page + 1}/{len(pages)}\n{pack}  ({start + 1}~{start + len(chunk)} / {size}개)"))
    data = await asyncio.to_thread(core.contact_sheet, chunk, cols)
    view.add_item(discord.ui.MediaGallery(discord.MediaGalleryItem("attachment://pick.webp")))
    for i in range(0, len(chunk), cols):
        view.add_item(discord.ui.ActionRow(*[SendButton(r["id"], str(i + j + 1))
                                             for j, r in enumerate(chunk[i:i + cols])]))
    starts = {}
    for n, pg in enumerate(pages):
        starts.setdefault(pg[0], n)
    if len(starts) > 1:  # 팩 바로가기
        options = [discord.SelectOption(label=f"{p[:80]}  ({pg + 1}쪽)", value=f"{pg}:{n}", default=(p == pack))
                   for n, (p, pg) in enumerate(list(starts.items())[:25])]
        view.add_item(discord.ui.ActionRow(JumpSelect(key, cols, options)))
    view.add_item(discord.ui.ActionRow(
        NavButton(key, page - 1, cols, "◀", page == 0, "p"),
        NavButton(key, page + 1, cols, "▶", page >= len(pages) - 1, "n"),
        SizeButton(key, chunk[0]["id"], cols),
        HomeButton(),
    ))
    nxt = pages[page + 1][3] if page + 1 < len(pages) else []  # 다음 쪽은 미리 만들어 둔다
    return view, discord.File(io.BytesIO(data), filename="pick.webp"), nxt


async def show_group(inter, key, page, cols, anchor=None):
    view, file, nxt = await pick_group_view(key, page, cols, anchor)
    await inter.response.edit_message(view=view, attachments=[file] if file else [])
    if nxt:
        asyncio.get_running_loop().run_in_executor(None, _prefetch, nxt, size_of(cols))


def _prefetch(rows, cols):
    try:
        core.contact_sheet(rows, cols)
    except Exception:  # 미리 만들기 실패는 넘길 때 다시 만들면 되므로 무시
        log.debug("격자 미리 만들기 실패", exc_info=True)


class SendButton(discord.ui.DynamicItem[discord.ui.Button], template=r"ep:s:(?P<eid>\d+)"):
    def __init__(self, eid, label="보내기"):
        super().__init__(discord.ui.Button(label=label, style=discord.ButtonStyle.secondary, custom_id=f"ep:s:{eid}"))
        self.eid = eid

    @classmethod
    async def from_custom_id(cls, inter, item, match):
        return cls(int(match["eid"]), item.label)

    async def callback(self, inter):
        if not await allowed(inter):
            return
        row = await asyncio.to_thread(core.get_emoji_by_id, self.eid)
        if row is None:
            return await reply(inter, "이미 삭제된 이모티콘입니다.", fade=True)
        await send_emoji(inter, row)


class NavButton(discord.ui.DynamicItem[discord.ui.Button],
                template=r"ep:g:(?P<key>\w+):(?P<page>-?\d+):(?P<cols>\d):(?P<d>[pn])"):
    def __init__(self, key, page, cols, label, disabled=False, d="n"):
        super().__init__(discord.ui.Button(label=label, style=discord.ButtonStyle.primary, disabled=disabled,
                                           custom_id=f"ep:g:{key}:{page}:{cols}:{d}"))
        self.key, self.page, self.cols = key, page, cols

    @classmethod
    async def from_custom_id(cls, inter, item, match):
        return cls(match["key"], int(match["page"]), int(match["cols"]), item.label, d=match["d"])

    async def callback(self, inter):
        if await allowed(inter):
            await show_group(inter, self.key, self.page, self.cols)


class SizeButton(discord.ui.DynamicItem[discord.ui.Button], template=r"ep:z:(?P<key>\w+):(?P<eid>\d+):(?P<cols>\d)"):
    """크게(3×3) → 보통(4×4) → 많이(5×5). 보던 팩·위치를 유지하고, 고른 크기는 다음 /e pick 에도 유지."""
    def __init__(self, key, eid, cols):
        super().__init__(discord.ui.Button(label=f"🔍 {SIZES[size_of(cols)]}", style=discord.ButtonStyle.secondary,
                                           custom_id=f"ep:z:{key}:{eid}:{cols}"))
        self.key, self.eid, self.cols = key, eid, size_of(cols)

    @classmethod
    async def from_custom_id(cls, inter, item, match):
        return cls(match["key"], int(match["eid"]), int(match["cols"]))

    async def callback(self, inter):
        if not await allowed(inter):
            return
        new = NEXT_SIZE[self.cols]
        await asyncio.to_thread(core.set_pick_cols, inter.user.id, new)
        await show_group(inter, self.key, 0, new, anchor=self.eid)


class HomeButton(discord.ui.DynamicItem[discord.ui.Button], template=r"ep:h"):
    def __init__(self):
        super().__init__(discord.ui.Button(label="그룹", emoji="🏠", style=discord.ButtonStyle.secondary,
                                           custom_id="ep:h"))

    @classmethod
    async def from_custom_id(cls, inter, item, match):
        return cls()

    async def callback(self, inter):
        if await allowed(inter):
            await inter.response.edit_message(view=await pick_home_view(), attachments=[])


class GroupButton(discord.ui.DynamicItem[discord.ui.Button], template=r"ep:gb:(?P<key>\w+)"):
    def __init__(self, key, label="그룹"):
        style = discord.ButtonStyle.success if key == "f" else discord.ButtonStyle.secondary
        super().__init__(discord.ui.Button(label=label[:80], style=style, emoji="⭐" if key == "f" else None,
                                           custom_id=f"ep:gb:{key}"))
        self.key = key

    @classmethod
    async def from_custom_id(cls, inter, item, match):
        return cls(match["key"], item.label)

    async def callback(self, inter):
        user = await allowed(inter)
        if user:
            await show_group(inter, self.key, 0, user["pick_cols"])


class HomePageButton(discord.ui.DynamicItem[discord.ui.Button], template=r"ep:hp:(?P<page>-?\d+):(?P<d>[pn])"):
    def __init__(self, page, label, disabled=False, d="n"):
        super().__init__(discord.ui.Button(label=label, style=discord.ButtonStyle.primary, disabled=disabled,
                                           custom_id=f"ep:hp:{page}:{d}"))
        self.page = page

    @classmethod
    async def from_custom_id(cls, inter, item, match):
        return cls(int(match["page"]), item.label, d=match["d"])

    async def callback(self, inter):
        if await allowed(inter):
            await inter.response.edit_message(view=await pick_home_view(self.page), attachments=[])


class GroupSelect(discord.ui.DynamicItem[discord.ui.Select], template=r"ep:gs:(?P<i>\d+)"):
    """이전 버전 창(드롭다운)이 열려 있어도 동작하도록 남겨 둔다."""
    def __init__(self, i, options=None):
        super().__init__(discord.ui.Select(placeholder="그룹 고르기" if i == 0 else f"그룹 더 보기 ({i + 1})",
                                           options=options or [discord.SelectOption(label="-")],
                                           custom_id=f"ep:gs:{i}"))

    @classmethod
    async def from_custom_id(cls, inter, item, match):
        return cls(int(match["i"]), item.options)

    async def callback(self, inter):
        user = await allowed(inter)
        if user:
            await show_group(inter, inter.data["values"][0], 0, user["pick_cols"])


class JumpSelect(discord.ui.DynamicItem[discord.ui.Select], template=r"ep:j:(?P<key>\w+):(?P<cols>\d)"):
    def __init__(self, key, cols, options=None):
        super().__init__(discord.ui.Select(placeholder="팩으로 바로 가기", options=options or [discord.SelectOption(label="-")],
                                           custom_id=f"ep:j:{key}:{cols}"))
        self.key, self.cols = key, cols

    @classmethod
    async def from_custom_id(cls, inter, item, match):
        return cls(match["key"], int(match["cols"]), item.options)

    async def callback(self, inter):
        if await allowed(inter):
            await show_group(inter, self.key, int(inter.data["values"][0].split(":")[0]), self.cols)


@e.command(name="pick", description="디스코드 안에서 그룹을 골라 이모티콘 보내기")
async def cmd_pick(inter: discord.Interaction):
    if core.activity_enabled():
        # 액티비티 창을 연다. 창에서 누른 이모티콘은 이 명령의 토큰으로 이 대화방에 보낸다(14분).
        await asyncio.to_thread(core.record_launch, inter.user.id, inter.channel_id, inter.application_id, inter.token)
        try:
            await inter.response.launch_activity()
            return
        except discord.HTTPException as err:  # 개발자 포털에서 액티비티를 안 켰을 때 등
            log.warning("액티비티 실행 실패, 버튼 화면으로 대신 엽니다: %s", err)
    await inter.response.send_message(view=await pick_home_view(), ephemeral=True)


@e.command(name="add-pack", description="카카오 이모티콘 팩 추가")
@app_commands.rename(url="카카오주소", name="팩이름")
@app_commands.describe(url="https://e.kakao.com/t/... 주소", name="팩 이름 (이모티콘마다 팩이름-1, 팩이름-2 … 로 붙음)")
async def cmd_add_pack(inter: discord.Interaction, url: str, name: str):
    await inter.response.defer(ephemeral=True, thinking=True)
    n = await asyncio.to_thread(core.add_pack, url, name, inter.user.name)
    await reply(inter, f"✅ '{name}' 팩을 추가했습니다. ({name}-1 ~ {name}-{n})", fade=True)
    await show_gallery(inter, name, "name", intro=f"방금 추가한 '{name}' 팩")


@e.command(name="add", description="이모티콘 1개 추가")
@app_commands.rename(ename="이모티콘이름", image="이미지", image_url="이미지주소", name="이름", groups="그룹", tags="태그")
@app_commands.describe(ename="보낼 때 쓸 이름 (공백 없이)", image="이미지 올리기 (끌어놓기·붙여넣기 가능)",
                       image_url="이미지를 올리지 않았다면 이미지 주소", name="묶음 이름 (비우면 이모티콘이름과 같게)",
                       groups="등록된 그룹 중에서 선택 (쉼표로 여러 개)", tags="등록된 태그 중에서 선택 (쉼표로 여러 개)")
async def cmd_add(inter: discord.Interaction, ename: str, image: discord.Attachment | None = None,
                  image_url: str | None = None, name: str | None = None,
                  groups: str | None = None, tags: str | None = None):
    if image is None and not image_url:
        raise core.UserError("`이미지`에 파일을 올리거나 `이미지주소`를 입력하세요.")
    if image is not None and image.size > MAX_UPLOAD:
        raise core.UserError("이미지가 너무 큽니다 (최대 10MB).")
    await inter.response.defer(ephemeral=True, thinking=True)
    data = await image.read() if image is not None else await asyncio.to_thread(core.fetch, image_url)
    ename = await asyncio.to_thread(core.add_single, ename, data, inter.user.name, name, groups, tags)
    await reply(inter, f"✅ '{ename}' 이모티콘을 추가했습니다.", fade=True)
    await show_gallery(inter, ename, "name", intro=f"방금 추가한 '{ename}'")


@cmd_add.autocomplete("groups")
async def ac_add_groups(inter, current: str):
    if not await can_autocomplete(inter):
        return []
    return await asyncio.to_thread(multi_choices, lambda q: core.label_names("grp", q), current)


@cmd_add.autocomplete("tags")
async def ac_add_tags(inter, current: str):
    if not await can_autocomplete(inter):
        return []
    return await asyncio.to_thread(multi_choices, lambda q: core.label_names("tags", q), current)


@e.command(name="del-pack", description="이름·태그·그룹 기준으로 이모티콘 여러 개 삭제")
@app_commands.rename(field="기준", value="값")
@app_commands.describe(field="무엇을 기준으로 지울지", value="목록에서 선택")
@app_commands.choices(field=FIELDS[1:])
async def cmd_del_pack(inter: discord.Interaction, field: Choice[str], value: str):
    n = await asyncio.to_thread(core.count_targets, field.value, value)
    if not n:
        raise core.UserError(f"{field.name} '{value}'에 해당하는 이모티콘이 없습니다.")
    await reply(inter, f"{field.name} '{value}'에 해당하는 이모티콘 {n}개를 삭제할까요? 되돌릴 수 없습니다.",
                view=ConfirmView(lambda: core.delete_emojis(field.value, value), "🗑️ 이모티콘 {n}개를 삭제했습니다."))


@e.command(name="del", description="이모티콘 1개 삭제, 또는 태그·그룹 이름만 삭제")
@app_commands.rename(target="대상", value="값")
@app_commands.describe(target="무엇을 지울지", value="목록에서 선택")
@app_commands.choices(target=[Choice(name="이모티콘 1개", value="emoji"), Choice(name="태그 이름만", value="tag"),
                              Choice(name="그룹 이름만", value="group")])
async def cmd_del(inter: discord.Interaction, target: Choice[str], value: str):
    if target.value == "emoji":
        if not await asyncio.to_thread(core.count_targets, "emoji", value):
            raise core.UserError(f"'{value}' 이모티콘이 없습니다.")
        return await reply(inter, f"'{value}' 이모티콘을 삭제할까요?",
                           view=ConfirmView(lambda: core.delete_emojis("emoji", value), "🗑️ 삭제했습니다."))
    table = "tags" if target.value == "tag" else "grp"
    subj, obj = ("태그가", "태그를") if table == "tags" else ("그룹이", "그룹을")
    if not await asyncio.to_thread(core.label_exists, table, value):
        raise core.UserError(f"'{value}' {subj} 없습니다.")
    await reply(inter, f"'{value}' {obj} 삭제할까요? 이 {subj} 붙은 이모티콘은 남고 {obj[:2]}만 빠집니다.",
                view=ConfirmView(lambda: core.delete_label(table, name=value), f"🗑️ '{value}' {obj} 삭제했습니다."))


async def _ac_value(inter, current, field):
    if not await can_autocomplete(inter):
        return []
    if field == "tag":
        names = await asyncio.to_thread(core.label_names, "tags", current)
    elif field == "group":
        names = await asyncio.to_thread(core.label_names, "grp", current)
    elif field == "name":
        names = await asyncio.to_thread(core.pack_names, current)
    elif field == "emoji":
        names = [r["ename"] for r in (await asyncio.to_thread(core.find, current) if current
                                      else await asyncio.to_thread(core.popular, 25))]
    else:
        return [Choice(name="먼저 앞 칸에서 기준을 고르세요", value=current[:100] or "-")]
    return choices(names)


@cmd_del_pack.autocomplete("value")
async def ac_del_pack(inter, current: str):
    return await _ac_value(inter, current, getattr(inter.namespace, "기준", None))


@cmd_del.autocomplete("value")
async def ac_del(inter, current: str):
    return await _ac_value(inter, current, getattr(inter.namespace, "대상", None))


@e.command(name="web", description="관리자 웹 로그인 링크 받기")
async def cmd_web(inter: discord.Interaction):
    user = await asyncio.to_thread(core.get_user, inter.user.id)
    if not user or not user["can_web"]:
        raise core.UserError("웹 사용 권한이 없습니다. 관리자에게 요청하세요.")
    token = await asyncio.to_thread(core.create_login_token, inter.user.id)
    await reply(inter, f"관리자 웹 로그인 링크입니다. 10분 동안 한 번만 쓸 수 있습니다.\n{BASE_URL}/login/discord?token={token}")


HELP = discord.Embed(title="이모티콘 봇 사용법", color=0xFFC940, description=(
    "`/e` 를 입력하면 아래 명령이 목록으로 뜹니다. 고른 뒤 나오는 칸만 채우면 됩니다.\n\n"
    "**/e send** 이름 일부를 입력하면 자동완성 목록에서 골라 바로 보냅니다.\n"
    "**/e pick** 디스코드 안에서 그룹을 고르면 번호 격자가 나오고, 번호를 누르면 바로 보내집니다.\n"
    "**/e find** 웹 갤러리 링크를 받습니다. 그룹을 고르거나 검색해서 이미지를 누르면 이 채널에 보내집니다 (14분 동안).\n"
    "**/e add-pack** 카카오 이모티콘 주소와 팩 이름으로 팩을 통째로 추가합니다.\n"
    "**/e add** 이미지 1개를 추가합니다. 그룹·태그는 등록된 것 중에서 고릅니다.\n"
    "**/e del-pack** 이름·태그·그룹 기준으로 여러 개를 삭제합니다.\n"
    "**/e del** 이모티콘 1개, 또는 태그·그룹 이름만 삭제합니다.\n"
    "**/e web** 관리자 웹 로그인 링크를 받습니다 (웹 권한 필요).\n\n"
    "새 태그·그룹은 관리자 웹의 태그·그룹 관리에서 만듭니다."))


@e.command(name="help", description="사용법 보기")
async def cmd_help(inter: discord.Interaction):
    await reply(inter, embed=HELP)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    db.init()
    bot.run(os.environ["BOT_TOKEN"], log_handler=None)


if __name__ == "__main__":
    main()
