// 디스코드 액티비티: /e pick 으로 디스코드 앱 안에서 열리는 이모티콘 고르기 창
//   1) 디스코드 로그인(최초 1회 동의) → 2) 그룹 칸(★ 즐겨찾기, 🔥 자주 쓰는, 그룹들) → 3) 스크롤하며 누르면 전송
//   이모티콘을 길게 누르면 메뉴(보내기 / 즐겨찾기), ★ 편집 버튼을 켜면 누를 때마다 즐겨찾기만 넣고 뺀다
//   검색창에 입력하면 검색 화면, 지우면 원래 화면
// 페이지를 연 것과 같은 URL Mapping("/" → 도메인/activity)을 그대로 탄다. (/.proxy 접두어는 쓰지 않음)
const P = "";
const app = document.getElementById("app");
const listEl = document.getElementById("list");
const packsEl = document.getElementById("packs");
const fieldsEl = document.getElementById("fields");
const titleEl = document.getElementById("title");
const backEl = document.getElementById("back");
const qEl = document.getElementById("q");
const toastEl = document.getElementById("toast");
const editEl = document.getElementById("edit");
const editHintEl = document.getElementById("edit-hint");

// 모바일 디스코드는 창 위쪽에 앱 이름·나가기 버튼을 겹쳐 그린다 → 그만큼 내려서 그린다
if (new URLSearchParams(location.search).get("platform") === "mobile") document.body.classList.add("mobile");

let sdk = null;
let session = "";
let mode = "home";   // home | group | search
let group = null;
let field = "all";
let seq = 0;
let editing = false;   // ★ 편집 모드: 누르면 보내지 않고 즐겨찾기만 넣고 뺀다

function el(tag, props, ...children) {
  const node = Object.assign(document.createElement(tag), props || {});
  node.append(...children);
  return node;
}
function note(text) { listEl.replaceChildren(el("p", { className: "note" }, text)); }
function toast(msg, isError) {
  toastEl.textContent = msg;
  toastEl.className = "toast" + (isError ? " err" : "");
  toastEl.hidden = false;
  clearTimeout(toast.t);
  toast.t = setTimeout(() => { toastEl.hidden = true; }, isError ? 4500 : 1500);
}
const img = (f) => `${P}/img/${f}?s=${encodeURIComponent(session)}`;

async function api(path, body) {
  const opt = { headers: { "X-Session": session, "X-Requested-With": "fetch" }, cache: "no-store" };
  if (body) {
    opt.method = "POST";
    opt.headers["Content-Type"] = "application/json";
    opt.body = JSON.stringify(body);
  }
  const res = await fetch(P + path, opt);
  const data = await res.json().catch(() => ({}));
  if (res.status === 401) throw new Error("로그인이 만료됐어요. 창을 닫고 다시 열어 주세요.");
  if (!res.ok || data.error) throw new Error(data.error || `요청 실패 (${res.status})`);
  return data;
}

// ---- 시작: 디스코드 연결 + 로그인 ----
async function start() {
  try {
    sdk = new DiscordSDKLib.DiscordSDK(app.dataset.client);
  } catch (e) {
    return note("이 화면은 디스코드 안에서 열려야 해요. 디스코드에서 /e pick 을 써 주세요.");
  }
  try {
    await sdk.ready();
    const { code } = await sdk.commands.authorize({
      client_id: app.dataset.client, response_type: "code", state: "", prompt: "none", scope: ["identify"],
    });
    const res = await fetch(`${P}/token`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Requested-With": "fetch" },
      body: JSON.stringify({ code }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || "로그인하지 못했어요.");
    await sdk.commands.authenticate({ access_token: data.access_token });
    session = data.session;
    qEl.disabled = false;
    showHome();
  } catch (e) {
    note(e.message || "디스코드에 연결하지 못했어요. 창을 닫고 다시 열어 주세요.");
  }
}

function setMode(next) {
  mode = next;
  backEl.hidden = mode !== "group";
  titleEl.hidden = mode !== "group";
  fieldsEl.hidden = mode !== "search";
  editEl.hidden = mode === "home";
  if (mode === "home") setEditing(false);
  if (mode !== "group") packsEl.replaceChildren();
  closeMenu();
}

function setEditing(on) {
  editing = on;
  editEl.setAttribute("aria-pressed", String(on));
  editHintEl.hidden = !on;
  document.body.classList.toggle("editing", on);
}

// ---- 화면 1: 그룹 칸 ----
async function showHome() {
  setMode("home");
  const my = ++seq;
  note("불러오는 중…");
  try {
    const { groups } = await api("/groups");
    if (my !== seq) return;
    if (!groups.length) return note("아직 등록된 이모티콘이 없어요.");
    listEl.replaceChildren(el("div", { className: "tiles" }, ...groups.map((g) => {
      const covers = g.covers.length >= 4 ? g.covers.slice(0, 4) : g.covers.slice(0, 1);
      const quad = covers.length
        ? el("div", { className: "quad" + (covers.length === 1 ? " one" : "") },
          ...covers.map((f) => el("img", { src: img(f), alt: "", loading: "lazy" })))
        : el("div", { className: "quad one" }, el("span", { className: "empty-star", textContent: "★" }));
      const mark = { s: "★ ", f: "🔥 " }[g.key] || "";
      const btn = el("button", { type: "button", className: "tile" + ({ s: " star", f: " hot" }[g.key] || "") },
        quad, el("b", { textContent: mark + g.name }), el("span", { textContent: `${g.count}개` }));
      btn.setAttribute("aria-label", `${g.name} 그룹 열기, ${g.count}개`);
      btn.addEventListener("click", () => showGroup(g));
      return btn;
    })));
  } catch (e) {
    note(e.message);
  }
}

// ---- 화면 2: 그룹의 모든 팩·이모티콘 ----
async function showGroup(g) {
  group = g;
  setMode("group");
  titleEl.replaceChildren(g.name, el("span", { textContent: `${g.count}개` }));
  scrollTo(0, 0);
  const my = ++seq;
  note("불러오는 중…");
  try {
    const { items } = await api(`/items?group=${encodeURIComponent(g.key)}`);
    if (my !== seq) return;
    if (!items.length && g.key === "s") {
      return note("아직 즐겨찾기가 없어요. 이모티콘을 길게 누르거나, 그룹 안에서 ★ 버튼을 켜고 눌러서 넣으세요.");
    }
    render(items, g.key !== "f" && g.key !== "s");
  } catch (e) {
    note(e.message);
  }
}

// ---- 화면 3: 검색 ----
async function search() {
  const q = qEl.value.trim();
  if (!q) return group ? showGroup(group) : showHome();
  setMode("search");
  const my = ++seq;
  try {
    const { items } = await api(`/items?${new URLSearchParams({ q, field })}`);
    if (my !== seq) return;
    render(items, true);
  } catch (e) {
    note(e.message);
  }
}

// 팩별로 묶어서 그린다. 단일 이모티콘은 '단일 이모티콘' 하나로 모은다. 위쪽 팩 이름을 누르면 그 팩으로 이동.
function render(items, byPack) {
  if (!items.length) return note(mode === "search" ? "검색 결과가 없어요." : "이 그룹에는 이모티콘이 없어요.");
  const packs = new Map();
  for (const it of items) {
    const name = !byPack ? "" : (it.k === "pack" ? it.p : "단일 이모티콘");
    if (!packs.has(name)) packs.set(name, []);
    packs.get(name).push(it);
  }
  listEl.replaceChildren(...[...packs].map(([name, rows], i) => el("section", { className: "sec", id: `pack-${i}` },
    ...(name ? [el("h2", {}, name, el("span", { textContent: `${rows.length}개` }))] : []),
    el("div", { className: "grid" }, ...rows.map(cell)))));
  packsEl.replaceChildren(...(packs.size > 1 ? [...packs.keys()] : []).map((name, i) => {
    const b = el("button", { type: "button", textContent: name });
    b.addEventListener("click", () => document.getElementById(`pack-${i}`).scrollIntoView({ behavior: "smooth" }));
    return b;
  }));
}

// 짧게 누르기 = 보내기(편집 모드면 별표 토글), 길게 누르기 = 메뉴(보내기 / 즐겨찾기)
const LONG_PRESS_MS = 500;
const MOVE_CANCEL_PX = 10;   // 손가락이 이만큼 움직이면 스크롤로 보고 길게 누르기 취소

function cell(it) {
  const btn = el("button", { type: "button", className: "cell", title: it.e },
    el("img", { src: img(it.f), alt: "", loading: "lazy", decoding: "async", draggable: false }));
  btn.dataset.id = it.i;
  btn.setAttribute("aria-label", `${it.e} 보내기. 길게 누르면 즐겨찾기 메뉴`);
  paintStar(btn, it.s);
  let timer = null, startX = 0, startY = 0, longFired = false;
  const cancel = () => { clearTimeout(timer); timer = null; };
  btn.addEventListener("pointerdown", (e) => {
    longFired = false;
    startX = e.clientX; startY = e.clientY;
    timer = setTimeout(() => { longFired = true; timer = null; openMenu(btn, it); }, LONG_PRESS_MS);
  });
  btn.addEventListener("pointermove", (e) => {
    if (timer && Math.hypot(e.clientX - startX, e.clientY - startY) > MOVE_CANCEL_PX) cancel();
  });
  ["pointerup", "pointercancel", "pointerleave"].forEach((t) => btn.addEventListener(t, cancel));
  btn.addEventListener("contextmenu", (e) => { e.preventDefault(); if (!longFired) { longFired = true; openMenu(btn, it); } });
  btn.addEventListener("click", (e) => {
    if (longFired) { e.preventDefault(); longFired = false; return; }  // 길게 누른 뒤 손을 뗀 것은 클릭이 아님
    closeMenu();
    if (editing) toggleStar(it); else send(btn, it);
  });
  return btn;
}

function paintStar(btn, on) {
  let badge = btn.querySelector(".badge");
  if (on && !badge) btn.append(el("span", { className: "badge", textContent: "★", ariaHidden: "true" }));
  if (!on && badge) badge.remove();
  btn.classList.toggle("unstarred", !on && group && group.key === "s" && mode === "group");
}

async function toggleStar(it) {
  const on = !it.s;
  try {
    const { starred } = await api("/star", { id: it.i, on });
    it.s = starred;
    document.querySelectorAll(`.cell[data-id="${it.i}"]`).forEach((b) => paintStar(b, starred));
    toast(starred ? `★ ${it.e} 즐겨찾기에 넣었어요` : `${it.e} 즐겨찾기에서 뺐어요`);
  } catch (e) {
    toast(e.message, true);
  }
}

function closeMenu() {
  document.querySelectorAll(".menu").forEach((m) => m.remove());
}

function openMenu(btn, it) {
  closeMenu();
  if (navigator.vibrate) navigator.vibrate(10);
  const menu = el("div", { className: "menu", role: "menu" },
    el("button", { type: "button", role: "menuitem", textContent: `보내기  ${it.e}`,
      onclick: () => { closeMenu(); send(btn, it); } }),
    el("button", { type: "button", role: "menuitem", textContent: it.s ? "☆ 즐겨찾기에서 빼기" : "★ 즐겨찾기에 넣기",
      onclick: () => { closeMenu(); toggleStar(it); } }));
  document.body.append(menu);
  const r = btn.getBoundingClientRect();
  const w = menu.offsetWidth, h = menu.offsetHeight;
  const left = Math.min(Math.max(8, r.left), innerWidth - w - 8);
  const top = r.bottom + h + 8 < innerHeight ? r.bottom + 6 : Math.max(8, r.top - h - 6);
  Object.assign(menu.style, { left: `${left}px`, top: `${top}px` });
  menu.querySelector("button").focus();
}

// 메뉴 바깥을 누르거나 스크롤하면 메뉴를 닫는다
document.addEventListener("pointerdown", (e) => { if (!e.target.closest(".menu")) closeMenu(); }, true);
addEventListener("scroll", closeMenu, { passive: true });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenu(); });

async function send(btn, it) {
  if (btn.classList.contains("busy")) return;
  btn.classList.add("busy");
  try {
    await api("/send", { id: it.i, channel_id: sdk.channelId });
    btn.classList.add("sent");
    if (navigator.vibrate) navigator.vibrate(15);
    toast(`${it.e} 보냈어요`);
  } catch (e) {
    toast(e.message, true);
  } finally {
    setTimeout(() => btn.classList.remove("busy"), 600);
  }
}

qEl.addEventListener("input", () => { clearTimeout(search.t); search.t = setTimeout(search, 300); });
qEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); qEl.blur(); clearTimeout(search.t); search(); }
});
fieldsEl.addEventListener("click", (e) => {
  const b = e.target.closest("button[data-field]");
  if (!b) return;
  field = b.dataset.field;
  fieldsEl.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
  search();
});
backEl.addEventListener("click", () => { group = null; qEl.value = ""; showHome(); });
editEl.addEventListener("click", () => setEditing(!editing));

start();
