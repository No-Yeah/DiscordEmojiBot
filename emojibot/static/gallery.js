// 디스코드 /e find 링크로 여는 갤러리
//   처음: 그룹 고르기 + 검색창 → 그룹을 누르면 그 그룹의 모든 팩·이모티콘 → 누르면 채널로 전송
//   검색창에 입력하면 검색 화면(기준·팩 거르기), 검색어를 지우면 다시 그룹 화면
const app = document.getElementById("app");
const token = app.dataset.token;
const base = `/g/${encodeURIComponent(token)}`;
const listEl = document.getElementById("list");
const packsEl = document.getElementById("packs");
const fieldsEl = document.getElementById("fields");
const titleEl = document.getElementById("title");
const backEl = document.getElementById("back");
const qEl = document.getElementById("q");
const timerEl = document.getElementById("timer");
const toastEl = document.getElementById("toast");

let field = app.dataset.field || "all";
let mode = "home";      // home | group | search
let group = null;       // { key, name }
let items = [];
let pack = "";          // 검색 화면에서 거른 팩
let seconds = Number(app.dataset.seconds) || 0;
let expired = false;
let seq = 0;

function toast(msg, isError) {
  toastEl.textContent = msg;
  toastEl.className = "toast" + (isError ? " err" : "");
  toastEl.hidden = false;
  clearTimeout(toast.t);
  toast.t = setTimeout(() => { toastEl.hidden = true; }, isError ? 4000 : 1600);
}

function el(tag, props, ...children) {
  const node = Object.assign(document.createElement(tag), props || {});
  node.append(...children);
  return node;
}

function note(text) { listEl.replaceChildren(el("p", { className: "note" }, text)); }

function setExpired() {
  if (expired) return;
  expired = true;
  timerEl.textContent = "만료";
  packsEl.replaceChildren();
  note("링크가 만료됐어요. 디스코드에서 /e find 를 다시 써 주세요.");
}

async function getJSON(url) {
  const res = await fetch(url, { cache: "no-store" });
  if (res.status === 410) { setExpired(); return null; }
  if (!res.ok) throw new Error();
  const data = await res.json();
  if (data.seconds !== undefined) seconds = data.seconds;
  return data;
}

function setMode(next) {
  mode = next;
  backEl.hidden = mode !== "group";
  titleEl.hidden = mode !== "group";
  fieldsEl.hidden = mode !== "search";
  if (mode !== "group") packsEl.replaceChildren();
}

// ---- 화면 1: 그룹 고르기 ----
async function showHome() {
  setMode("home");
  const my = ++seq;
  note("불러오는 중…");
  try {
    const data = await getJSON(`${base}/groups`);
    if (!data || my !== seq) return;
    if (!data.groups.length) return note("아직 등록된 이모티콘이 없어요.");
    listEl.replaceChildren(
      el("p", { className: "lead" }, "그룹을 고르세요. 위 검색창으로 바로 찾을 수도 있어요."),
      el("div", { className: "groups" }, ...data.groups.map((g) => {
        const btn = el("button", { type: "button", className: "group" + (g.key === "f" ? " fav" : "") },
          el("img", { src: `${base}/img/${g.cover}`, alt: "", loading: "lazy" }),
          el("b", { textContent: g.name }),
          el("span", { textContent: `${g.count}개` }));
        btn.addEventListener("click", () => showGroup(g));
        return btn;
      })),
    );
  } catch (e) {
    toast("목록을 불러오지 못했어요. 연결을 확인해 주세요.", true);
  }
}

// ---- 화면 2: 그룹 안의 모든 팩·이모티콘 ----
async function showGroup(g) {
  group = g;
  setMode("group");
  titleEl.replaceChildren(g.name, el("span", { textContent: `${g.count}개` }));
  scrollTo(0, 0);
  const my = ++seq;
  note("불러오는 중…");
  try {
    const data = await getJSON(`${base}/items?group=${encodeURIComponent(g.key)}`);
    if (!data || my !== seq) return;
    items = data.items;
    renderSections(items, true);
  } catch (e) {
    toast("목록을 불러오지 못했어요. 연결을 확인해 주세요.", true);
  }
}

// ---- 화면 3: 검색 ----
async function search() {
  const q = qEl.value.trim();
  if (!q) return group && mode === "search" ? showGroup(group) : showHome();
  setMode("search");
  const my = ++seq;
  try {
    const data = await getJSON(`${base}/items?${new URLSearchParams({ q, field })}`);
    if (!data || my !== seq) return;
    items = data.items;
    pack = "";
    renderSearch();
  } catch (e) {
    toast("목록을 불러오지 못했어요. 연결을 확인해 주세요.", true);
  }
}

function renderSearch() {
  const names = [...new Set(items.map((i) => i.p))];
  packsEl.replaceChildren(...(names.length > 1 ? ["", ...names] : []).map((p) => {
    const b = el("button", { type: "button", textContent: p || `전체 ${items.length}` });
    b.setAttribute("aria-pressed", String(p === pack));
    b.addEventListener("click", () => { pack = p; renderSearch(); });
    return b;
  }));
  renderSections(pack ? items.filter((i) => i.p === pack) : items, false);
}

// 팩별로 묶어서 격자로 그린다. 그룹 화면에서는 위쪽 팩 칩이 해당 팩으로 바로 이동한다.
function renderSections(list, jumpChips) {
  if (!list.length) return note(mode === "search" ? "검색 결과가 없어요. 다른 말로 찾아보세요." : "이 그룹에는 이모티콘이 없어요.");
  const groups = new Map();
  for (const it of list) {
    if (!groups.has(it.p)) groups.set(it.p, []);
    groups.get(it.p).push(it);
  }
  const sections = [...groups].map(([name, rows], i) => el("section", { className: "sec", id: `pack-${i}` },
    el("h2", {}, name, el("span", { textContent: `${rows.length}개` })),
    el("div", { className: "grid" }, ...rows.map(cell)),
  ));
  listEl.replaceChildren(...sections);
  if (jumpChips) {
    packsEl.replaceChildren(...(groups.size > 1 ? [...groups.keys()] : []).map((name, i) => {
      const b = el("button", { type: "button", textContent: name });
      b.addEventListener("click", () => document.getElementById(`pack-${i}`).scrollIntoView({ behavior: "smooth" }));
      return b;
    }));
  }
}

function cell(it) {
  const btn = el("button", { type: "button", className: "cell", title: `${it.e} 보내기` },
    el("img", { src: `${base}/img/${it.f}`, alt: "", loading: "lazy", decoding: "async" }),
    el("span", { textContent: it.e }));
  btn.setAttribute("aria-label", `${it.e} 보내기`);
  btn.addEventListener("click", () => send(btn, it.e));
  return btn;
}

async function send(btn, ename) {
  if (expired || btn.classList.contains("busy")) return;
  btn.classList.add("busy");
  try {
    const res = await fetch(`${base}/send`, {
      method: "POST",
      headers: { "X-Requested-With": "fetch", "Content-Type": "application/json" },
      body: JSON.stringify({ ename }),
    });
    const data = await res.json().catch(() => ({ error: "응답을 읽지 못했어요." }));
    if (res.status === 410) { setExpired(); return; }
    if (!res.ok || data.error) throw new Error(data.error || "보내지 못했어요.");
    btn.classList.add("sent");
    if (navigator.vibrate) navigator.vibrate(15);
    toast(`${ename} 보냈어요`);
  } catch (e) {
    toast(e.message, true);
  } finally {
    setTimeout(() => btn.classList.remove("busy"), 700);
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

setInterval(() => {
  if (expired) return;
  seconds = Math.max(0, seconds - 1);
  if (!seconds) return setExpired();
  timerEl.textContent = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
  timerEl.classList.toggle("low", seconds < 120);
}, 1000);

if (qEl.value.trim()) search(); else showHome();
