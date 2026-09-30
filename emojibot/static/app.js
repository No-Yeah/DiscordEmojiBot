// 모든 변경 요청은 이 함수를 거친다. X-Requested-With 헤더가 서버의 CSRF 검사 조건이다.
async function api(url, body) {
  const opt = { method: "POST", headers: { "X-Requested-With": "fetch" } };
  if (body instanceof FormData) opt.body = body;
  else { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body || {}); }
  const res = await fetch(url, opt);
  const data = await res.json().catch(() => ({ error: `서버 응답 오류 (${res.status})` }));
  if (!res.ok || data.error) { toast(data.error || "요청이 실패했습니다.", true); throw new Error(data.error); }
  return data;
}

function toast(msg, isError) {
  const el = document.createElement("div");
  el.className = "toast" + (isError ? " err" : "");
  el.setAttribute("role", "status");
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), isError ? 5000 : 2500);
}

function reloadWith(msg) {
  try { sessionStorage.setItem("toast", msg); } catch (e) { /* 알림만 생략 */ }
  location.reload();
}
try {
  const pending = sessionStorage.getItem("toast");
  if (pending) { sessionStorage.removeItem("toast"); toast(pending); }
} catch (e) { /* 저장소를 못 쓰면 알림만 생략 */ }

// 한 줄 입력 대화상자: 이름 변경, 태그·그룹 목록 편집에 함께 쓴다
const editDlg = document.getElementById("dlg-edit");
function openEdit({ title, value, hint, url, key }) {
  editDlg.querySelector("h2").textContent = title;
  editDlg.querySelector(".hint").textContent = hint || "";
  const input = editDlg.querySelector("input");
  input.value = value || "";
  editDlg.onsubmit = async (ev) => {
    ev.preventDefault();
    await api(url, { [key]: input.value });
    reloadWith("저장했습니다.");
  };
  editDlg.showModal();
  input.select();
}

document.addEventListener("click", async (ev) => {
  const t = ev.target.closest("[data-edit],[data-delete],[data-toggle],[data-open],[data-close]");
  if (!t) return;
  const d = t.dataset;
  if (d.toggle !== undefined) {
    const row = document.getElementById(d.toggle);
    const open = row.hidden;
    row.hidden = !open;
    t.setAttribute("aria-expanded", String(open));
  } else if (d.open) {
    document.getElementById(d.open).showModal();
  } else if (d.close !== undefined) {
    t.closest("dialog").close();
  } else if (d.edit) {
    openEdit({ title: d.title, value: d.value, hint: d.hint, url: d.edit, key: d.key || "name" });
  } else if (d.delete) {
    if (!confirm(d.confirm || "삭제할까요?")) return;
    const r = await api(d.delete);
    reloadWith(r.count !== undefined ? `이모티콘 ${r.count}개를 삭제했습니다.` : "삭제했습니다.");
  }
});

// data-api 폼: FormData 그대로 전송
document.addEventListener("submit", async (ev) => {
  const form = ev.target.closest("form[data-api]");
  if (!form) return;
  ev.preventDefault();
  form.classList.add("busy");
  try {
    const r = await api(form.dataset.api, new FormData(form));
    reloadWith(form.dataset.done || (r.count ? `이모티콘 ${r.count}개를 추가했습니다.` : "저장했습니다."));
  } catch (e) {
    form.classList.remove("busy");
  }
});

// 권한 체크박스
document.addEventListener("change", async (ev) => {
  const box = ev.target.closest("[data-perm]");
  if (!box) return;
  try {
    await api(box.dataset.perm, { field: box.name, value: box.checked });
    toast("권한을 바꿨습니다.");
  } catch (e) {
    box.checked = !box.checked;
  }
});

// 단일 추가: 파일 선택, 끌어놓기, 클립보드 붙여넣기
const single = document.getElementById("dlg-single");
if (single) {
  const drop = single.querySelector(".drop");
  const file = single.querySelector("input[type=file]");
  const setFile = (f) => {
    if (!f || !f.type.startsWith("image/")) return toast("이미지 파일만 쓸 수 있습니다.", true);
    const dt = new DataTransfer();
    dt.items.add(f);
    file.files = dt.files;
    drop.querySelector("img").src = URL.createObjectURL(f);
    drop.querySelector("img").hidden = false;
    drop.querySelector("span").textContent = f.name || "붙여넣은 이미지";
  };
  drop.addEventListener("click", () => file.click());
  drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); file.click(); } });
  file.addEventListener("change", () => file.files[0] && setFile(file.files[0]));
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("over"); setFile(e.dataTransfer.files[0]); });
  single.addEventListener("paste", (e) => {
    const item = [...e.clipboardData.items].find((i) => i.type.startsWith("image/"));
    if (item) { e.preventDefault(); setFile(item.getAsFile()); }
  });
}

// 그룹·태그 관리 화면의 즉석 검색
const filter = document.getElementById("filter");
if (filter) {
  filter.addEventListener("input", () => {
    const q = filter.value.trim().toLowerCase();
    document.querySelectorAll("[data-name]").forEach((row) => {
      row.hidden = q && !row.dataset.name.toLowerCase().includes(q);
    });
  });
}

// 그룹·태그 선택: 등록된 것 중에서 고른다. 새로 만들 때는 '새로 만들기'를 눌러야만 생긴다(오타 방지).
const labelData = document.getElementById("labels");
const labels = labelData ? JSON.parse(labelData.textContent) : { tag: [], group: [] };
const pickDlg = document.getElementById("dlg-pick");
const WORD = { tag: "태그", group: "그룹" };

function splitNames(v) { return (v || "").split(",").map((x) => x.trim()).filter(Boolean); }

function openPicker({ kind, title, selected, onSave }) {
  const q = pickDlg.querySelector("#pick-q");
  const list = pickDlg.querySelector(".pick-list");
  const newBtn = pickDlg.querySelector(".pick-new");
  const empty = pickDlg.querySelector(".pick-empty");
  const sel = new Set(selected);
  pickDlg.querySelector("h2").textContent = title;
  q.value = "";

  const render = () => {
    const term = q.value.trim().toLowerCase();
    const names = labels[kind].filter((n) => !term || n.toLowerCase().includes(term));
    list.replaceChildren(...names.map((n) => {
      const label = document.createElement("label");
      label.className = "pick-item" + (kind === "tag" ? " t" : " g");
      const box = document.createElement("input");
      box.type = "checkbox";
      box.checked = sel.has(n);
      box.addEventListener("change", () => { box.checked ? sel.add(n) : sel.delete(n); });
      label.append(box, document.createTextNode(n));
      return label;
    }));
    const exact = labels[kind].some((n) => n.toLowerCase() === term);
    newBtn.hidden = !term || exact;
    newBtn.textContent = `'${q.value.trim()}' ${WORD[kind]} 새로 만들기`;
    empty.hidden = labels[kind].length > 0 || !!term;
    empty.textContent = `등록된 ${WORD[kind]}가 없습니다. 찾기 칸에 이름을 쓰고 새로 만들기를 누르세요.`;
  };
  q.oninput = render;
  q.onkeydown = (e) => { if (e.key === "Enter") e.preventDefault(); };
  newBtn.onclick = async () => {
    const name = q.value.trim();
    await api(`/api/${kind}`, { name });
    labels[kind].push(name);
    labels[kind].sort((a, b) => a.localeCompare(b, "ko"));
    sel.add(name);
    q.value = "";
    render();
    toast(`${WORD[kind]} '${name}'를 만들었습니다.`);
  };
  pickDlg.onsubmit = async (e) => {
    e.preventDefault();
    const chosen = labels[kind].filter((n) => sel.has(n));
    await onSave(chosen);
    pickDlg.close();
  };
  render();
  pickDlg.showModal();
  q.focus();
}

function showChips(button, kind, names) {
  button.replaceChildren(...(names.length ? names.map((n) => {
    const s = document.createElement("span");
    s.className = "tag " + (kind === "tag" ? "t" : "g");
    s.textContent = n;
    return s;
  }) : [Object.assign(document.createElement("span"), { className: "edit-hint", textContent: `+ ${WORD[kind]} 선택` })]));
}

document.addEventListener("click", (ev) => {
  const t = ev.target.closest("[data-pick]");
  if (!t || !pickDlg) return;
  const kind = t.dataset.pick;
  if (t.dataset.target) {  // 추가 폼 안의 선택 칸: hidden input 에 채운다
    const input = document.getElementById(t.dataset.target);
    openPicker({ kind, title: t.dataset.title, selected: splitNames(input.value),
      onSave: (names) => { input.value = names.join(", "); showChips(t, kind, names); } });
  } else {  // 목록의 그룹·태그: 바로 저장
    openPicker({ kind, title: t.dataset.title, selected: splitNames(t.dataset.value),
      onSave: async (names) => { await api(t.dataset.url, { items: names }); reloadWith("저장했습니다."); } });
  }
});
