"""디스코드 봇. /e 를 입력하면 하위 명령과 입력 칸이 차례로 나온다.

/e send      이모티콘 보내기 (이름 자동완성)
/e find      격자 미리보기로 찾아서 번호를 눌러 보내기 (이전/다음 페이지)
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
GALLERY_MINUTES = 10       # 격자 목록 버튼이 동작하는 시간
PAGE_SIZES = {4: 2, 9: 3, 12: 4, 16: 4, 20: 5}  # 한 페이지 개수 -> 한 줄 칸 수

FIELDS = [Choice(name="전체", value="all"), Choice(name="이름", value="name"),
          Choice(name="태그", value="tag"), Choice(name="그룹", value="group")]
FIELD_LABEL = {"all": "전체", "name": "이름", "tag": "태그", "group": "그룹", "emoji": "이모티콘"}


class Bot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.none())  # 슬래시 명령만 쓰므로 특권 인텐트 불필요
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
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


# ---------- 격자 미리보기 ----------

class GalleryView(discord.ui.View):
    """번호가 붙은 격자 이미지 + 번호 버튼(누르면 전송) + 이전/다음."""

    def __init__(self, q, field, per_page, page=0):
        super().__init__(timeout=GALLERY_MINUTES * 60)
        self.q, self.field, self.per_page, self.page = q, field, per_page, page
        self.cols = PAGE_SIZES[per_page]
        self.rows, self.total = [], 0

    async def load(self):
        self.rows, self.total = await asyncio.to_thread(
            core.search, self.q, self.field, self.page * self.per_page, self.per_page)
        self.pages = max(1, math.ceil(self.total / self.per_page))
        self.clear_items()
        for i, row in enumerate(self.rows):
            btn = discord.ui.Button(label=str(i + 1), style=discord.ButtonStyle.primary, row=i // self.cols)
            btn.callback = self._sender(row["ename"])
            self.add_item(btn)
        nav = [
            ("◀ 이전", self.page == 0, -1),
            (f"{self.page + 1} / {self.pages}", True, 0),
            ("다음 ▶", self.page + 1 >= self.pages, 1),
        ]
        for label, disabled, step in nav:
            btn = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary, disabled=disabled, row=4)
            if step:
                btn.callback = self._mover(step)
            self.add_item(btn)
        return self

    def content(self):
        head = f"**'{self.q}'** {FIELD_LABEL[self.field]} 검색" if self.q else "**전체 이모티콘**"
        names = "   ".join(f"`{i + 1}` {r['ename']}" for i, r in enumerate(self.rows))
        return f"{head}  {self.total}개  ({self.page + 1}/{self.pages} 페이지)\n{names}\n번호를 누르면 채널에 보냅니다."

    async def file(self):
        data = await asyncio.to_thread(core.contact_sheet, self.rows, self.cols)
        return discord.File(io.BytesIO(data), filename="list.png")

    def _sender(self, ename):
        async def cb(inter):
            if not await allowed(inter):
                return
            row = await asyncio.to_thread(core.get_emoji, ename)
            if row is None:
                return await reply(inter, "이미 삭제된 이모티콘입니다.", fade=True)
            await send_emoji(inter, row)
        return cb

    def _mover(self, step):
        async def cb(inter):
            view = await GalleryView(self.q, self.field, self.per_page, self.page + step).load()
            await inter.response.edit_message(content=view.content(), attachments=[await view.file()], view=view)
        return cb


async def show_gallery(inter, q="", field="all", per_page=9, empty_msg=None):
    view = await GalleryView(q, field, per_page).load()
    if not view.total:
        return await reply(inter, empty_msg or f"'{q}' 검색 결과가 없습니다.", fade=True)
    await reply(inter, view.content(), file=await view.file(), view=view)


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
    await show_gallery(inter, ename, empty_msg=f"'{ename}' 이모티콘이 없습니다. `/e find`로 둘러보세요.")


@cmd_send.autocomplete("ename")
async def ac_send(inter, current: str):
    if not await can_autocomplete(inter):
        return []
    rows = await asyncio.to_thread(core.find, current) if current else await asyncio.to_thread(core.popular, 25)
    return [Choice(name=f"{r['ename']}  ({r['pack']})" + (f"  #{r['tags']}" if r["tags"] else ""),
                   value=r["ename"][:100]) for r in rows][:25]


@e.command(name="find", description="이모티콘을 격자 미리보기로 찾아서 보내기")
@app_commands.rename(q="검색어", field="기준", per_page="개수")
@app_commands.describe(q="비우면 전체 목록", field="어디에서 찾을지 (기본: 전체)", per_page="한 페이지에 보여줄 개수 (기본 9)")
@app_commands.choices(field=FIELDS, per_page=[Choice(name=f"{n}개", value=n) for n in PAGE_SIZES])
async def cmd_find(inter: discord.Interaction, q: str = "",
                   field: Choice[str] | None = None, per_page: Choice[int] | None = None):
    await show_gallery(inter, q, field.value if field else "all", per_page.value if per_page else 9,
                       empty_msg=None if q else "아직 등록된 이모티콘이 없습니다. `/e add-pack`으로 추가하세요.")


@cmd_find.autocomplete("q")
async def ac_find(inter, current: str):
    if not await can_autocomplete(inter):
        return []
    field = getattr(inter.namespace, "기준", None) or "all"
    if field == "tag":
        return choices(await asyncio.to_thread(core.label_names, "tags", current))
    if field == "group":
        return choices(await asyncio.to_thread(core.label_names, "grp", current))
    names = await asyncio.to_thread(core.pack_names, current)
    names += [r["ename"] for r in await asyncio.to_thread(core.find, current)] if current else []
    return choices(list(dict.fromkeys(names)))


@e.command(name="add-pack", description="카카오 이모티콘 팩 추가")
@app_commands.rename(url="카카오주소", name="팩이름")
@app_commands.describe(url="https://e.kakao.com/t/... 주소", name="팩 이름 (이모티콘마다 팩이름-1, 팩이름-2 … 로 붙음)")
async def cmd_add_pack(inter: discord.Interaction, url: str, name: str):
    await inter.response.defer(ephemeral=True, thinking=True)
    n = await asyncio.to_thread(core.add_pack, url, name, inter.user.name)
    await reply(inter, f"✅ '{name}' 팩을 추가했습니다. ({name}-1 ~ {name}-{n})", fade=True)
    await show_gallery(inter, name, "name", 20 if n > 12 else 12)


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
    await show_gallery(inter, ename, "name", 4)


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
    "**/e find** 격자 미리보기로 둘러보고 번호를 눌러 보냅니다. 기준(전체·이름·태그·그룹)과 한 페이지 개수를 고를 수 있습니다.\n"
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
