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
  // 대화상자가 열려 있으면 그 안에 띄워야 어두운 배경에 가려지지 않는다
  (document.querySelector("dialog[open]") || document.body).appendChild(el);
  setTimeout(() => el.remove(), isError ? 5000 : 2500);
}

// 저장 후 새로고침해도 펼쳐 둔 팩과 스크롤 위치를 그대로 되살린다
function reloadWith(msg) {
  try {
    sessionStorage.setItem("toast", msg);
    const open = [...document.querySelectorAll("tr.detail:not([hidden])")].map((r) => r.id);
    sessionStorage.setItem("restore", JSON.stringify({ path: location.pathname + location.search, open, y: scrollY }));
  } catch (e) { /* 저장소를 못 쓰면 복원만 생략 */ }
  location.reload();
}
try {
  const pending = sessionStorage.getItem("toast");
  if (pending) { sessionStorage.removeItem("toast"); toast(pending); }
  const restore = JSON.parse(sessionStorage.getItem("restore") || "null");
  sessionStorage.removeItem("restore");
  if (restore && restore.path === location.pathname + location.search) {
    restore.open.forEach((id) => {
      const row = document.getElementById(id);
      const btn = document.querySelector(`[data-toggle="${id}"]`);
      if (row && btn) { row.hidden = false; btn.setAttribute("aria-expanded", "true"); }
    });
    history.scrollRestoration = "manual";
    scrollTo(0, restore.y);
  }
} catch (e) { /* 복원 실패 시 기본 화면 */ }

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

// 여러 행 체크 → 그룹 한꺼번에 붙이기/떼기. Shift+클릭으로 범위 선택.
const bulk = document.getElementById("bulk");
if (bulk) {
  const rows = [...document.querySelectorAll(".row-check")];
  const all = document.getElementById("check-all");
  let last = null;
  const chosen = () => rows.filter((r) => r.checked).map((r) => Number(r.value));
  const refresh = () => {
    const n = chosen().length;
    bulk.hidden = n === 0;
    document.getElementById("bulk-n").textContent = n;
    all.checked = n > 0 && n === rows.length;
    all.indeterminate = n > 0 && n < rows.length;
    rows.forEach((r) => r.closest("tr").classList.toggle("picked", r.checked));
  };
  rows.forEach((box, i) => box.addEventListener("click", (e) => {
    if (e.shiftKey && last !== null) {
      const [a, b] = [Math.min(last, i), Math.max(last, i)];
      rows.slice(a, b + 1).forEach((r) => { r.checked = box.checked; });
    }
    last = i;
    refresh();
  }));
  all.addEventListener("change", () => { rows.forEach((r) => { r.checked = all.checked; }); refresh(); });
  bulk.addEventListener("click", (e) => {
    const b = e.target.closest("[data-bulk]");
    if (!b) return;
    const mode = b.dataset.bulk;
    if (mode === "clear") { rows.forEach((r) => { r.checked = false; }); return refresh(); }
    const ids = chosen();
    openPicker({
      kind: "group",
      title: mode === "add" ? `선택한 ${ids.length}개에 붙일 그룹` : `선택한 ${ids.length}개에서 뗄 그룹`,
      selected: [],
      onSave: async (names) => {
        if (!names.length) { toast("그룹을 하나 이상 고르세요.", true); throw new Error("empty"); }
        const r = await api("/api/packs/groups", { ids, items: names, mode });
        reloadWith(`${r.count}개에서 그룹 ${names.join(", ")}을(를) ${mode === "add" ? "붙였습니다" : "뗐습니다"}.`);
      },
    });
  });
  refresh();
}

// 팩 추가: 주소 여러 개 → 불러오기(제목·수 검수) → 체크한 것만 / 체크한 것 빼고 / 전체 등록
const pk = document.getElementById("dlg-pack");
if (pk) {
  const $ = (id) => document.getElementById(id);
  const step1 = $("pk-step1"), step2 = $("pk-step2"), rowsEl = $("pk-rows"), allBox = $("pk-all");
  const actionBtns = [...pk.querySelectorAll("[data-pk], #pk-back")];
  let items = [], running = false, stopRequested = false, registered = 0;

  const note = (row, text, cls) => {
    const n = row.querySelector(".pk-note");
    n.textContent = text;
    n.className = "pk-note" + (cls ? " " + cls : "");
  };
  const showStep = (n) => { step1.hidden = n !== 1; step2.hidden = n !== 2; };

  function warningOf(it) {
    if (!it.ok) return [it.error, "err"];
    if (it.registered_as) {
      const g = it.registered_groups && it.registered_groups.length ? ` · 그룹: ${it.registered_groups.join(", ")}` : "";
      return [`중복: 같은 주소의 팩이 '${it.registered_as}' 이름으로 이미 등록돼 있습니다${g}. 등록할 때 덮어쓸지 건너뛸지 고릅니다.`, "warn"];
    }
    if (it.name_taken) return ["같은 이름의 팩이 이미 있습니다. 이름을 바꿔 주세요.", "warn"];
    if (it.dup_in_batch) return ["목록 안에 같은 이름이 또 있습니다. 이름을 바꿔 주세요.", "warn"];
    return ["", ""];
  }

  function render() {
    rowsEl.replaceChildren(...items.map((it, i) => {
      const tr = document.createElement("tr");
      const box = Object.assign(document.createElement("input"), { type: "checkbox", disabled: !it.ok });
      box.setAttribute("aria-label", `${it.title || it.url} 체크`);
      const name = Object.assign(document.createElement("input"), {
        type: "text", value: it.title || it.url, maxLength: 60, disabled: !it.ok,
      });
      name.setAttribute("aria-label", `${i + 1}번 팩 이름`);
      name.addEventListener("input", () => { it.title = name.value; });
      const img = it.ok ? Object.assign(document.createElement("img"), { src: it.cover, alt: "", referrerPolicy: "no-referrer", loading: "lazy" }) : null;
      if (img) img.onerror = () => img.remove();
      const nameCell = document.createElement("td");
      const wrap = document.createElement("div");
      wrap.className = "pk-name";
      const col = document.createElement("div");
      col.style.flex = "1";
      col.append(name, Object.assign(document.createElement("div"), { className: "pk-note" }));
      if (img) wrap.append(img);
      wrap.append(col);
      nameCell.append(wrap);
      tr.append(Object.assign(document.createElement("td"), { className: "num", textContent: i + 1 }), nameCell,
        Object.assign(document.createElement("td"), { className: "num", textContent: it.ok ? `${it.count}개` : "-" }),
        Object.assign(document.createElement("td"), { className: "chk" }));
      tr.lastChild.append(box);
      if (!it.ok) tr.classList.add("pk-off");
      if (it.registered_as) {
        tr.classList.add("pk-dup");
        col.prepend(Object.assign(document.createElement("span"), { className: "dup-tag", textContent: "중복" }));
      }
      it.row = tr; it.box = box; it.input = name;
      const [msg, cls] = warningOf(it);
      note(tr, msg, cls);
      box.addEventListener("change", syncAll);
      return tr;
    }));
    const okCount = items.filter((x) => x.ok).length;
    const total = items.reduce((n, x) => n + (x.ok ? x.count : 0), 0);
    $("pk-summary").textContent = `${items.length}개 중 ${okCount}개 불러옴, 이모티콘 ${total}개. 이름을 확인하고 등록하세요.`
      + (okCount < items.length ? " (불러오지 못한 주소는 등록되지 않습니다)" : "");
    syncAll();
  }

  // 중복(같은 주소) 팩이 섞여 있으면: 건너뛰기 / 덮어쓰기(+그룹 이어받기) 중 고른다
  function askDuplicate(dups, total) {
    const dlg = $("dlg-dup"), keep = $("dup-keep");
    $("dup-desc").textContent = `등록하려는 ${total}개 중 ${dups.length}개는 같은 주소의 팩이 이미 있습니다.`;
    $("dup-list").replaceChildren(...dups.map((x) => Object.assign(document.createElement("li"), {
      textContent: `${x.input.value}  ← 기존 '${x.registered_as}'`
        + (x.registered_groups && x.registered_groups.length ? ` (그룹: ${x.registered_groups.join(", ")})` : ""),
    })));
    dlg.querySelector('input[value="skip"]').checked = true;
    keep.checked = true; keep.disabled = true;
    dlg.querySelectorAll('input[name="dup-mode"]').forEach((r) => {
      r.onchange = () => { keep.disabled = dlg.querySelector('input[name="dup-mode"]:checked').value !== "replace"; };
    });
    dlg.showModal();
    return new Promise((resolve) => {
      const done = (v) => { dlg.close(); resolve(v); };
      $("dup-ok").onclick = () => {
        const mode = dlg.querySelector('input[name="dup-mode"]:checked').value;
        done({ mode, keep: mode === "replace" && keep.checked });
      };
      $("dup-cancel").onclick = () => done(null);
      dlg.oncancel = (e) => { e.preventDefault(); done(null); };
    });
  }

  function syncAll() {
    const boxes = items.filter((x) => x.ok).map((x) => x.box);
    const n = boxes.filter((b) => b.checked).length;
    allBox.checked = n > 0 && n === boxes.length;
    allBox.indeterminate = n > 0 && n < boxes.length;
  }
  allBox.addEventListener("change", () => {
    items.forEach((x) => { if (x.ok && !x.done) x.box.checked = allBox.checked; });
    syncAll();
  });

  $("pk-load").addEventListener("click", async () => {
    const btn = $("pk-load");
    btn.disabled = true;
    btn.textContent = "불러오는 중…";
    try {
      const r = await api("/api/packs/preview", { urls: $("pk-urls").value });
      items = r.items;
      registered = 0;
      render();
      showStep(2);
    } catch (e) { /* api()가 이미 알림을 띄움 */ }
    btn.disabled = false;
    btn.textContent = "불러오기";
  });
  $("pk-back").addEventListener("click", () => showStep(1));

  // 한 팩씩 차례로 등록한다 (오래 걸려도 끊기지 않고, 줄마다 진행 상황이 보인다)
  pk.querySelectorAll("[data-pk]").forEach((btn) => btn.addEventListener("click", async () => {
    const mode = btn.dataset.pk;
    let targets = items.filter((x) => x.ok && !x.done
      && (mode === "all" || (mode === "only" ? x.box.checked : !x.box.checked)));
    if (!targets.length) return toast(mode === "only" ? "먼저 등록할 팩을 체크하세요." : "등록할 팩이 없습니다.", true);
    const dups = targets.filter((x) => x.registered_as);
    let choice = { mode: "none", keep: false };
    if (dups.length) {
      choice = await askDuplicate(dups, targets.length);
      if (!choice) return;
      if (choice.mode === "skip") {
        dups.forEach((x) => note(x.row, "건너뜀 (중복: 같은 주소의 팩이 이미 있음)", "warn"));
        targets = targets.filter((x) => !x.registered_as);
        if (!targets.length) return toast("중복을 빼고 나니 등록할 팩이 없습니다.", true);
      }
    } else if (!confirm(`팩 ${targets.length}개를 등록할까요?`)) return;
    running = true; stopRequested = false;
    actionBtns.forEach((b) => { b.disabled = true; });
    targets.forEach((x) => note(x.row, "대기 중", ""));
    for (const it of targets) {
      if (stopRequested) { note(it.row, "취소됨", "warn"); continue; }
      note(it.row, "등록 중… (이미지를 받는 데 시간이 걸립니다)", "");
      it.input.disabled = true;
      try {
        const r = await fetch("/api/pack", {
          method: "POST",
          headers: { "X-Requested-With": "fetch", "Content-Type": "application/json" },
          body: JSON.stringify({ url: it.url, name: it.input.value,
            replace: !!it.registered_as && choice.mode === "replace", keep_groups: !!it.registered_as && choice.keep }),
        });
        const data = await r.json().catch(() => ({ error: `서버 응답 오류 (${r.status})` }));
        if (!r.ok || data.error) throw new Error(data.error || "등록하지 못했습니다.");
        it.done = true; registered++;
        it.box.checked = false; it.box.disabled = true;
        it.row.classList.add("pk-off");
        note(it.row, it.registered_as ? `✓ 덮어쓰기 완료 (${data.count}개${choice.keep ? ", 그룹 이어받음" : ""})`
          : `✓ 등록 완료 (${data.count}개)`, "ok");
        it.registered_as = null;
      } catch (e) {
        it.input.disabled = false;
        note(it.row, `✗ ${e.message}`, "err");
      }
    }
    running = false;
    actionBtns.forEach((b) => { b.disabled = false; });
    syncAll();
    const failed = targets.filter((x) => !x.done && !stopRequested).length;
    toast(`등록 완료 ${targets.filter((x) => x.done).length}개` + (failed ? `, 실패 ${failed}개 (이름을 고쳐 다시 등록할 수 있어요)` : ""), failed > 0);
  }));

  $("pk-cancel").addEventListener("click", () => {
    if (running) { stopRequested = true; toast("지금 등록 중인 팩까지만 하고 멈춥니다."); return; }
    pk.close();
  });
  pk.addEventListener("close", () => {
    if (registered) reloadWith(`팩 ${registered}개를 등록했습니다.`);
    showStep(1);
    items = []; rowsEl.replaceChildren();
  });
  pk.addEventListener("cancel", (e) => { if (running) { e.preventDefault(); stopRequested = true; } });
}
