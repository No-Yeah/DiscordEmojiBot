// 디스코드 액티비티: /e pick 으로 디스코드 앱 안에서 열리는 이모티콘 고르기 창
//   1) 디스코드 로그인(최초 1회 동의) → 2) 그룹 칸(대표 2×2) → 3) 그룹의 모든 팩·이모티콘 스크롤 → 누르면 전송
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

// 모바일 디스코드는 창 위쪽에 앱 이름·나가기 버튼을 겹쳐 그린다 → 그만큼 내려서 그린다
if (new URLSearchParams(location.search).get("platform") === "mobile") document.body.classList.add("mobile");

let sdk = null;
let session = "";
let mode = "home";   // home | group | search
let group = null;
let field = "all";
let seq = 0;

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
  if (mode !== "group") packsEl.replaceChildren();
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
      const quad = el("div", { className: "quad" + (covers.length === 1 ? " one" : "") },
        ...covers.map((f) => el("img", { src: img(f), alt: "", loading: "lazy" })));
      const btn = el("button", { type: "button", className: "tile" + (g.key === "f" ? " fav" : "") },
        quad, el("b", { textContent: (g.key === "f" ? "⭐ " : "") + g.name }), el("span", { textContent: `${g.count}개` }));
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
    render(items, g.key !== "f");
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

function cell(it) {
  const btn = el("button", { type: "button", className: "cell", title: it.e },
    el("img", { src: img(it.f), alt: "", loading: "lazy", decoding: "async" }));
  btn.setAttribute("aria-label", `${it.e} 보내기`);
  btn.addEventListener("click", () => send(btn, it));
  return btn;
}

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

start();
