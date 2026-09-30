// 디스코드 /e find 링크로 여는 갤러리: 검색 → 팩별 격자 → 누르면 채널로 전송
const app = document.getElementById("app");
const token = app.dataset.token;
const base = `/g/${encodeURIComponent(token)}`;
const listEl = document.getElementById("list");
const packsEl = document.getElementById("packs");
const qEl = document.getElementById("q");
const timerEl = document.getElementById("timer");
const toastEl = document.getElementById("toast");

let field = app.dataset.field || "all";
let items = [];
let pack = "";          // 선택한 팩 ("" = 전체)
let seconds = Number(app.dataset.seconds) || 0;
let expired = false;
let loadSeq = 0;

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

function setExpired() {
  if (expired) return;
  expired = true;
  timerEl.textContent = "만료";
  listEl.replaceChildren(el("p", { className: "note" }, "링크가 만료됐어요. 디스코드에서 /e find 를 다시 써 주세요."));
  packsEl.replaceChildren();
}

async function load() {
  const seq = ++loadSeq;
  const params = new URLSearchParams({ q: qEl.value.trim(), field });
  try {
    const res = await fetch(`${base}/items?${params}`, { cache: "no-store" });
    if (res.status === 410) return setExpired();
    const data = await res.json();
    if (seq !== loadSeq) return;  // 더 최근 검색이 있으면 버린다
    items = data.items;
    seconds = data.seconds;
    pack = "";
    render();
  } catch (e) {
    toast("목록을 불러오지 못했어요. 연결을 확인해 주세요.", true);
  }
}

function render() {
  const packNames = [...new Set(items.map((i) => i.p))];
  packsEl.replaceChildren(...(packNames.length > 1 ? ["", ...packNames] : []).map((p) =>
    el("button", { type: "button", textContent: p || `전체 ${items.length}`, onclick: () => { pack = p; render(); } },
    )));
  packsEl.querySelectorAll("button").forEach((b, i) => b.setAttribute("aria-pressed", String((i === 0 ? "" : packNames[i - 1]) === pack)));

  if (!items.length) {
    listEl.replaceChildren(el("p", { className: "note" }, "검색 결과가 없어요. 다른 말로 찾아보세요."));
    return;
  }
  const groups = new Map();
  for (const it of items) {
    if (pack && it.p !== pack) continue;
    if (!groups.has(it.p)) groups.set(it.p, []);
    groups.get(it.p).push(it);
  }
  listEl.replaceChildren(...[...groups].map(([name, list]) => el("section", { className: "sec" },
    el("h2", {}, name, el("span", { textContent: `${list.length}개` })),
    el("div", { className: "grid" }, ...list.map(cell)),
  )));
}

function cell(it) {
  const img = el("img", { src: `${base}/img/${it.f}`, alt: "", loading: "lazy", decoding: "async" });
  const btn = el("button", { type: "button", className: "cell", title: `${it.e} 보내기` },
    img, el("span", { textContent: it.e }));
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

// 검색: 입력을 멈추면 0.3초 뒤 다시 불러온다
qEl.addEventListener("input", () => { clearTimeout(load.t); load.t = setTimeout(load, 300); });
qEl.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); qEl.blur(); clearTimeout(load.t); load(); } });
document.getElementById("fields").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-field]");
  if (!b) return;
  field = b.dataset.field;
  document.querySelectorAll("#fields button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
  load();
});

// 남은 시간
setInterval(() => {
  if (expired) return;
  seconds = Math.max(0, seconds - 1);
  if (!seconds) return setExpired();
  timerEl.textContent = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")} 남음`;
  timerEl.classList.toggle("low", seconds < 120);
}, 1000);

load();
