const $ = (s, el = document) => el.querySelector(s);
const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const media = (rel) =>
  "/media/" + rel.split("/").map(encodeURIComponent).join("/");
const mmss = (t) => {
  t = Math.max(0, Math.round(+t || 0));
  return Math.floor(t / 60) + ":" + String(t % 60).padStart(2, "0");
};
const clipName = (rel) =>
  (rel || "")
    .split("/")
    .pop()
    .replace(/\.mp4$/, "");
const KINDS = ["bug", "change", "polish", "crash", "idea"],
  PRIOS = ["high", "normal", "low"];

let selectedGame = localStorage.getItem("qa-game") || "",
  modelCatalog = [],
  modelRequest = 0;
const gameOf = (c) =>
  c.meta?.game || c.meta?.appLabel || c.meta?.app || c.clip.split("/")[0];
const drafts = () =>
  S.drafts.filter((t) => !selectedGame || t.game === selectedGame);
let S = null,
  lastJSON = "",
  cur = null,
  dirty = {},
  saveTimer = null,
  dragging = false;
const VIEWS = ["videos", "review", "handoffs", "runs", "archive"];
let view = VIEWS.includes(location.hash.slice(1))
    ? location.hash.slice(1)
    : "videos",
  clipFilter = "all",
  acting = false,
  saving = Promise.resolve();

async function api(path, body) {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
    signal: AbortSignal.timeout(120000),
  });
  const result = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(result.error || "Could not save. Please retry.");
  return result;
}

async function poll() {
  try {
    const r = await fetch("/api/state", {
      cache: "no-store",
      signal: AbortSignal.timeout(10000),
    });
    if (!r.ok) throw new Error("Connection failed");
    const txt = await r.text();
    if (txt !== lastJSON && !dragging) {
      lastJSON = txt;
      S = JSON.parse(txt);
      render();
    } else if (S) renderStatus();
    $("#deskConnection").textContent = "● Desk online";
    $("#deskConnection").classList.remove("offline");
  } catch (e) {
    $("#deskConnection").textContent = "○ Desk disconnected";
    $("#deskConnection").classList.add("offline");
    $("#status").textContent =
      "Connection lost. Keep this tab open; edits stay here until the desk reconnects.";
  }
}
setInterval(poll, 1500);
poll();

// ---------- top bar ----------

function renderStatus() {
  const w = S.working;
  let h;
  if (w) {
    const secs = Math.round(
      Date.now() / 1000 - (w.startedAt || Date.now() / 1000),
    );
    const game = w.meta?.game || w.meta?.appLabel || w.meta?.app || "";
    h = `<span class="spin"></span><span>${esc(w.step || "Working")} · ${esc(game)} ${esc(clipName(w.clip).slice(11))} · ${mmss(secs)}</span>`;
    if (S.queued) h += `<span>· ${S.queued} more waiting</span>`;
  } else if (S.settings.paused) {
    h = `<span class="dot paused"></span><span>Queue paused · incoming clips will wait</span>`;
  } else if (S.queued && ["signed-out", "missing"].includes(S.flags.auth)) {
    h = `<span class="fail">${S.queued} clip${S.queued > 1 ? "s" : ""} waiting for the analyst</span>`;
  } else if (S.queued) {
    h = `<span class="spin"></span><span>${S.queued} clip${S.queued > 1 ? "s" : ""} waiting</span>`;
  } else {
    h = `<span class="dot"></span><span>Waiting for clips from the phone</span>`;
  }
  $("#status").innerHTML = h;
  renderHealth();
  document.querySelectorAll("[data-run-clock]").forEach((el) => {
    const r = (S.runs || []).find((r) => r.id === el.dataset.runClock);
    if (r?.startedAt)
      el.textContent =
        mmss((r.completedAt || Date.now() / 1000) - r.startedAt) + " elapsed";
  });
}

function render() {
  renderStatus();
  renderGames();
  const nd = drafts().length,
    na = S.trays
      .filter((t) => !selectedGame || t.game === selectedGame)
      .reduce((n, t) => n + t.ids.length, 0);
  $("#videoCount").textContent = S.clips.filter(
    (c) => !selectedGame || gameOf(c) === selectedGame,
  ).length;
  $("#reviewCount").textContent = nd;
  $("#handoffCount").textContent = na;
  $("#runCount").textContent = (S.runs || []).filter(
    (r) =>
      ([
        "queued",
        "preparing",
        "continuing",
        "retesting",
        "needs_review",
        "fixing",
        "testing",
        "publishing",
        "pr_ready",
        "merge_queued",
      ].includes(r.status) || canReviewRun(r)) &&
      (!selectedGame || r.game === selectedGame),
  ).length;
  $("#repoShortcut").textContent =
    selectedGame && S.repositories?.[selectedGame]
      ? "↗ " + S.repositories[selectedGame].github
      : "Connect GitHub repository ↗";
  $("#reviewCTA").textContent = nd ? `(${nd}) →` : "→";
  $("#engineLabel").textContent =
    (S.settings.provider === "codex" ? "Codex" : "Claude") +
    " · " +
    (S.settings.model || "CLI default") +
    (S.settings.effort ? " · " + S.settings.effort : "");
  document.title = (nd ? `(${nd}) ` : "") + "Playtest Demon";

  const auth = S.flags.auth,
    provider = S.settings.provider,
    login = provider === "codex" ? "codex login" : "claude auth login";
  $("#banner").innerHTML = ["signed-out", "missing"].includes(auth)
    ? `<div class="banner"><span>${esc(provider)} ${auth === "missing" ? "is not installed" : "needs sign-in"}. Clips are safely queued. ${auth === "missing" ? "Follow the setup guide, then sign in." : `Run <code>${login}</code> in Terminal.`}</span><button class="mini" onclick="openSettings()">Change analyst</button></div>`
    : "";
  if (S.flags.inbox_error)
    $("#banner").innerHTML +=
      `<div class="banner">Inbox: ${esc(S.flags.inbox_error)}</div>`;
  renderView();
}

function renderView() {
  $("#videosView").hidden = view !== "videos";
  $("#main").hidden = view !== "review";
  $("#handoffsView").hidden = view !== "handoffs";
  for (const name of VIEWS) {
    const b = $("#nav-" + name);
    b.classList.toggle("on", view === name);
    b.setAttribute("aria-current", view === name ? "page" : "false");
  }
  if (view === "videos") renderClips();
  if (view === "review") renderReview();
  $("#runsView").hidden = view !== "runs";
  $("#archiveView").hidden = view !== "archive";
  $("#pageLabel").textContent = {
    videos: "Live feed",
    review: "Review requests",
    handoffs: "Approved batches",
    runs: "Fix runs",
    archive: "History & trash",
  }[view];
  if (view === "handoffs") renderSide();
  if (view === "runs") renderRuns();
  if (view === "archive") renderArchive();
}
async function go(name) {
  if (view === "review") {
    try {
      await flush();
    } catch {
      return;
    }
    $("#vid")?.pause();
  }
  view = name;
  if (location.hash !== "#" + name) history.pushState(null, "", "#" + name);
  if (S) renderView();
  window.scrollTo(0, 0);
}
window.addEventListener("popstate", () => {
  const name = location.hash.slice(1);
  if (VIEWS.includes(name) && name !== view) go(name);
});
function filterClips(value) {
  clipFilter = value;
  renderClips();
}
function renderClips() {
  const clips = S.clips.filter(
    (c) => !selectedGame || gameOf(c) === selectedGame,
  );
  const active = clips.filter((c) =>
    ["working", "queued"].includes(c.status),
  ).length;
  const approved = S.trays
    .filter((t) => !selectedGame || t.game === selectedGame)
    .reduce((n, t) => n + t.ids.length, 0);
  $("#stats").innerHTML = [
    [clips.length, "Recordings received", "01 · CAPTURE"],
    [drafts().length, "Requests to review", "02 · HUMAN REVIEW"],
    [approved, "Approved for a batch", "03 · SEND TO AGENT"],
    [
      (S.tickets || []).filter(
        (t) =>
          t.status === "fixed" && (!selectedGame || t.game === selectedGame),
      ).length,
      "Fixes to playtest",
      "04 · CLOSE THE LOOP",
    ],
  ]
    .map(
      ([n, l, k]) =>
        `<button class="stat" onclick="go('${k.startsWith("02") ? "review" : k.startsWith("03") ? "handoffs" : k.startsWith("04") ? "runs" : "videos"}')"><small>${k}</small><strong>${n}</strong><span>${l}</span></button>`,
    )
    .join("");
  $("#pause").textContent = S.settings.paused
    ? "▶ Resume queue"
    : "Ⅱ Pause queue";
  document
    .querySelectorAll("[data-filter]")
    .forEach((b) => b.classList.toggle("on", b.dataset.filter === clipFilter));
  const query = $("#clipSearch").value.trim().toLowerCase();
  const shown = clips.filter(
    (c) =>
      (clipFilter === "all" ||
        (clipFilter === "active" && ["working", "queued"].includes(c.status)) ||
        (clipFilter === "review" && c.draftIds.length) ||
        (clipFilter === "failed" && c.status === "failed")) &&
      (c.clip + " " + gameOf(c) + " " + (c.summary || ""))
        .toLowerCase()
        .includes(query),
  );
  const queued = S.clips
    .filter((c) => c.status === "queued")
    .sort((a, b) => a.queuedAt - b.queuedAt);
  $("#clipGrid").innerHTML =
    shown
      .map((c) => {
        const status =
          c.status === "done"
            ? c.draftIds.length
              ? "Review ready"
              : c.ticketCount
                ? "Requests reviewed"
                : "No requests found"
            : {
                working: "Analysing",
                queued: S.settings.paused ? "Paused" : "Queued",
                failed: "Needs attention",
                skipped: "Not analysed",
              }[c.status] || c.status;
        const preview =
          c.preview ||
          S.drafts.find((t) => t.clip === c.clip)?.shots?.[0]?.clean;
        const position = queued.findIndex((q) => q.clip === c.clip) + 1;
        const step =
          c.status === "working"
            ? c.step
            : c.status === "queued"
              ? `Position ${position} in the queue${S.settings.paused ? " · resumes when you’re ready" : ""}`
              : c.status === "failed"
                ? c.error
                : c.summary || "Watch the clip and choose what to do next.";
        const progress =
          c.status === "working"
            ? {
                "Extracting frames": 15,
                "Transcribing audio": 35,
                "Writing tickets": 95,
              }[c.step] || 65
            : c.status === "done"
              ? 100
              : 0;
        const locked =
          c.status === "working" ||
          (S.tickets || []).some(
            (t) => t.clip === c.clip && (t.runId || t.status === "sent"),
          );
        return `<article class="clip-card ${c.status}"><button class="clip-cover" data-clip="${esc(c.clip)}" onclick="previewClip(this.dataset.clip)" aria-label="Watch ${esc(gameOf(c))}">${preview ? `<img src="${media(preview)}" alt="" loading="lazy">` : '<span class="placeholder">▶</span>'}<span class="play-overlay">▶ Watch recording</span><span class="duration">${mmss(c.meta.clipSeconds)}</span></button><div class="clip-body"><div class="clip-top"><span class="badge ${c.status}">${c.status === "working" ? '<span class="spin"></span>' : ""}${status}</span><span class="source-label">${esc(c.meta.platform || "Android")}</span></div><h2>${esc(gameOf(c))}</h2><div class="clip-date">${esc(c.meta.originalName || clipName(c.clip))}</div>${c.status === "working" ? `<div class="progress-track" aria-label="Analysis stage"><div style="width:${progress}%"></div></div>` : ""}<p class="clip-step">${esc(step)}</p><div class="clip-footer"><span class="hint">${c.ticketCount ? c.ticketCount + " requests" : c.status === "working" ? mmss(Date.now() / 1000 - c.startedAt) + " elapsed" : c.seconds ? mmss(c.seconds) + " analysis" : "Voice → structured requests"}</span><div class="card-actions">${c.draftIds.length ? `<button class="text-button" onclick="reviewClip('${c.draftIds[0]}')">Review ${c.draftIds.length} →</button>` : ["failed", "skipped"].includes(c.status) ? `<button class="text-button" data-clip="${esc(c.clip)}" onclick="retry(this.dataset.clip)">Retry →</button>` : ""}<button class="icon-button" ${locked ? "disabled" : ""} data-clip="${esc(c.clip)}" title="${locked ? "Evidence is in use" : "Move recording and its requests to trash"}" aria-label="Move to trash" onclick="trashClip(this.dataset.clip)">⌫</button></div></div></div></article>`;
      })
      .join("") ||
    `<div class="empty"><div class="empty-icon">↥</div><h2>${clips.length ? "No matching recordings" : "Your next improvement starts here."}</h2><p>${clips.length ? "Try another filter or search." : "Android: start a session and use Volume Up. iPhone: record with microphone, AirDrop to your Mac, and import."}</p><button class="btn" onclick="openImport()">Import a recording</button></div>`;
}
async function reviewClip(id) {
  await go("review");
  await openTicket(id);
}
function previewClip(rel) {
  const c = S.clips.find((c) => c.clip === rel);
  $("#clipTitle").textContent = gameOf(c);
  $("#clipSummary").textContent =
    c.summary || c.step || "Analysis has not finished yet.";
  $("#clipVideo").src = media(rel);
  $("#clipDialog").showModal();
}
function closeClip() {
  $("#clipVideo").pause();
  $("#clipDialog").close();
}
$("#clipDialog").addEventListener("close", () => $("#clipVideo").pause());
function renderGames() {
  if (S.flags.renamedGames?.[selectedGame]) {
    selectedGame = S.flags.renamedGames[selectedGame]; localStorage.setItem("qa-game", selectedGame);
  }
  const names = [
    ...new Set([
      ...(S.games || []),
      ...S.clips.map(gameOf),
      ...S.drafts.map((t) => t.game),
    ]),
  ].sort((a, b) => a.localeCompare(b));
  if (selectedGame && !names.includes(selectedGame)) names.push(selectedGame);
  const html =
    '<option value="">All games</option>' +
    names.map((n) => `<option value="${esc(n)}">${esc(n)}</option>`).join("");
  if ($("#gamePicker").innerHTML !== html) $("#gamePicker").innerHTML = html;
  $("#gamePicker").value = selectedGame;
}
async function pickGame(name) {
  try {
    await flush();
  } catch {
    $("#gamePicker").value = selectedGame;
    return;
  }
  $("#vid")?.pause();
  selectedGame = name;
  localStorage.setItem("qa-game", name);
  cur = null;
  render();
}
function addGameOpen() {
  $("#newGame").value = "";
  $("#gameDialog").showModal();
  $("#newGame").focus();
}
async function addGame() {
  try {
    const name = $("#newGame").value.trim().replace(/\s+/g, " "),
      result = await api("/api/games", { name });
    S.games = result.games;
    $("#gameDialog").close();
    await pickGame(
      result.games.find((n) => n.toLowerCase() === name.toLowerCase()) || name,
    );
    toast("Game added. Your phone syncs it when connected.");
  } catch (e) {
    toast(e.message);
  }
}
function openSettings() {
  if (!S) return;
  $("#provider").value = S.settings.provider;
  const t = S.flags.tools || {};
  $("#toolStatus").textContent = [
    "ffmpeg",
    "ffprobe",
    "whisper",
    "whisper_model",
    "claude",
    "codex",
  ]
    .map((k) => `${k}: ${t[k] ? "available" : "not found"}`)
    .join(" · ");
  $("#settingsDialog").showModal();
  loadModels(false, S.settings.model, S.settings.effort);
}
async function loadModels(refresh = false, selected = "", effort = "") {
  const request = ++modelRequest,
    provider = $("#provider").value;
  $("#model").disabled =
    $("#effort").disabled =
    $("#saveAnalyst").disabled =
      true;
  $("#modelStatus").textContent = "Reading models from your installed CLI…";
  $("#model").innerHTML = '<option value="">Loading…</option>';
  $("#effort").innerHTML = "";
  try {
    const response = await fetch(
      "/api/models?provider=" + provider + (refresh ? "&refresh=1" : ""),
    );
    if (!response.ok) throw new Error("Could not read models");
    const data = await response.json();
    if (request !== modelRequest) return;
    modelCatalog = data.models || [];
    $("#model").innerHTML =
      '<option value="">Use CLI configured default</option>' +
      modelCatalog
        .map(
          (m) =>
            `<option value="${esc(m.id)}">${esc(m.name)}${m.resolved ? " · " + esc(m.resolved) : ""}</option>`,
        )
        .join("");
    if (selected && !modelCatalog.some((m) => m.id === selected)) {
      const option = new Option(
        selected + " · saved selection (not listed)",
        selected,
      );
      $("#model").add(option);
    }
    $("#model").value = selected;
    renderEfforts(effort);
    $("#modelStatus").textContent =
      data.error ||
      "Live CLI catalog. Access depends on your account; analysis will report any restriction.";
  } catch (e) {
    if (request !== modelRequest) return;
    modelCatalog = [];
    $("#model").innerHTML =
      '<option value="">Use CLI configured default</option>';
    if (selected)
      $("#model").add(new Option(selected + " · saved selection", selected));
    $("#model").value = selected;
    renderEfforts(effort);
    $("#modelStatus").textContent = e.message + ". Refresh to retry.";
  } finally {
    if (request === modelRequest) {
      $("#model").disabled = false;
      $("#saveAnalyst").disabled = false;
    }
  }
}
function renderEfforts(selected = "") {
  const m = modelCatalog.find((m) => m.id === $("#model").value);
  $("#modelDescription").textContent =
    m?.description ||
    "Uses your CLI configuration. Choose a listed model to customize effort.";
  $("#effort").innerHTML =
    `<option value="">${m?.defaultEffort ? "CLI default (model suggests " + esc(m.defaultEffort) + ")" : "CLI default effort"}</option>` +
    (m?.efforts || [])
      .map(
        (e) =>
          `<option value="${esc(e)}">${esc(e[0].toUpperCase() + e.slice(1))}</option>`,
      )
      .join("");
  $("#effort").disabled = !m?.efforts?.length;
  if (selected && !(m?.efforts || []).includes(selected))
    $("#effort").add(
      new Option(selected + " · saved setting (not listed)", selected),
    );
  $("#effort").value = selected || "";
}
async function saveSettings() {
  try {
    await api("/api/settings", {
      provider: $("#provider").value,
      model: $("#model").value,
      effort: $("#effort").value,
    });
    $("#settingsDialog").close();
    toast("Analyst saved. Applies to the next video.");
    lastJSON = "";
    await poll();
  } catch (e) {
    toast(e.message);
  }
}
async function togglePause() {
  try {
    await api("/api/settings", { paused: !S.settings.paused });
    lastJSON = "";
    await poll();
  } catch (e) {
    toast(e.message);
  }
}

// ---------- the review card ----------

function renderReview() {
  const box = $("#review");
  if (!drafts().length) {
    cur = null;
    const approved = S.trays
      .filter((t) => !selectedGame || t.game === selectedGame)
      .reduce((n, t) => n + t.ids.length, 0);
    const busy = S.clips.some(
      (c) =>
        (!selectedGame || gameOf(c) === selectedGame) &&
        ["working", "queued"].includes(c.status),
    );
    box.innerHTML = `<div class="empty"><h2>${busy ? "Drafting tickets…" : "You’re all caught up"}</h2>
      <div>${busy ? "Your analyst is processing the queue. New tickets will appear here automatically." : approved ? approved + " approved requests are ready for your agent." : "Record a new clip, or import an iPhone playtest to keep improving the game."}</div><div class="empty-actions"><button class="btn" onclick="go('videos')">← Back to recordings</button>${approved ? '<button class="btn go" onclick="go(\'handoffs\')">Open approved batch →</button>' : ""}</div></div>`;
    return;
  }
  if (!drafts().find((t) => t.id === cur)) {
    cur = drafts()[0].id;
    buildCard();
  } else if (!$(".card", box)) buildCard();
  else {
    renderTabs();
    const list = $(".review-list");
    if (list && !list.contains(document.activeElement))
      list.innerHTML =
        '<div class="eyebrow">REQUESTS TO REVIEW</div>' +
        drafts()
          .map(
            (x) =>
              `<button class="request-row ${x.id === cur ? "selected" : ""}" onclick="openTicket('${x.id}')"><small>${esc(x.id)} · ${esc(x.kind)}</small><b>${esc(x.title)}</b><span>${esc(x.game)}</span></button>`,
          )
          .join("");
    requestAnimationFrame(sizeAll);
  }
}

function renderTabs() {
  const el = $("#tabs");
  if (!el) return;
  const i = drafts().findIndex((t) => t.id === cur);
  el.innerHTML = `<button class="text-button" onclick="go('videos')">← Videos</button><span class="count">Ticket ${i + 1} of ${drafts().length}</span><div class="grow"></div><span id="saveState" class="hint">${Object.keys(dirty).length ? "Unsaved changes" : "All changes saved"}</span><button class="btn compact" ${i === 0 ? "disabled" : ""} onclick="openTicket('${drafts()[i - 1]?.id}')">← Previous</button><button class="btn compact" ${i === drafts().length - 1 ? "disabled" : ""} onclick="openTicket('${drafts()[i + 1]?.id}')">Next →</button>`;
}

async function openTicket(id) {
  try {
    await flush();
  } catch {
    return;
  }
  cur = id;
  buildCard();
}

function buildCard() {
  const t = drafts().find((x) => x.id === cur);
  if (!t) return;
  dirty = {};
  const m = t.moment || {},
    q = t.quote;
  const low = t.confidence === "low";
  const area = (
    k,
    label,
    ph,
    val,
  ) => `<div class="field"><label for="field-${k}">${label}</label>
    <textarea id="field-${k}" data-k="${k}" rows="1" placeholder="${ph}">${esc(val ?? t[k])}</textarea></div>`;
  $("#review").innerHTML = `
    <div class="tabs" id="tabs"></div>
    <div class="review-layout"><aside class="review-list"><div class="eyebrow">REQUESTS TO REVIEW</div>${drafts()
      .map(
        (x) =>
          `<button class="request-row ${x.id === cur ? "selected" : ""}" onclick="openTicket('${x.id}')"><small>${esc(x.id)} · ${esc(x.kind)}</small><b>${esc(x.title)}</b><span>${esc(x.game)}</span></button>`,
      )
      .join("")}</aside><div class="card">
      <div class="vcol">
        <video id="vid" src="${media(t.clip)}" controls playsinline preload="auto" style="${t.frame ? `aspect-ratio:${t.frame[0]} / ${t.frame[1]}` : ""}"></video>
        <div class="jumps">
          <button class="jump" onclick="seek(${(m.from || 0) - 1.5})">▶ The moment ${mmss(m.from)}</button>
          ${t.pressedAtSecond != null ? `<button class="jump" onclick="seek(${t.pressedAtSecond - 0.5})">You pressed ${mmss(t.pressedAtSecond)}</button>` : ""}
          <button class="jump" onclick="seek(0)">From the start</button>
        </div>
      </div>
      <div class="form">
        <div class="meta"><b>${esc(t.id)}</b> · ${esc(t.game)} ${esc(t.version || "")} · clip ${esc(clipName(t.clip))}
          · <span class="${low ? "conf-low" : ""}">${esc(t.confidence || "")} confidence</span></div>
        <textarea id="ticketTitle" aria-label="Ticket title" class="title" data-k="title" rows="1" placeholder="What's wrong, or what to change">${esc(t.title)}</textarea>
        <div class="chips">
          <span class="lab">Kind</span>${KINDS.map((k) => `<button class="chip ${t.kind === k ? "on" : ""}" data-set="kind" data-v="${k}">${k[0].toUpperCase() + k.slice(1)}</button>`).join("")}
          <span class="lab">Priority</span>${PRIOS.map((k) => `<button class="chip ${t.priority === k ? "on" : ""} ${k}" data-set="priority" data-v="${k}">${k[0].toUpperCase() + k.slice(1)}</button>`).join("")}
        </div>
        ${t.duplicateCandidates?.length ? `<div class="duplicate-warning"><b>Possible repeat request</b><span>${esc(t.duplicateCandidates[0].id)} · ${esc(t.duplicateCandidates[0].title)}</span><button class="text-button" onclick="duplicateOpen()">Compare & link →</button></div>` : ""}
        ${t.checks && t.checks.length ? `<div class="checks"><b>Check before approving</b><ul>${t.checks.map((c) => `<li>${esc(c)}</li>`).join("")}</ul></div>` : ""}
        ${area("where", "Where", "Screen and position")}
        ${area("now", "Observed", "What the game does now")}
        ${area("want", "Expected", "What it should do instead")}
        ${area("steps", "Steps", "Steps to reproduce, one per line (bugs only)", (t.steps || []).join("\n"))}
        ${area("done_when", "Acceptance", "One thing the programmer can check")}
        <div class="field quote"><label for="quote">You said ${q ? `<button class="mini" onclick="seek(${q.t - 0.5})">▶ ${mmss(q.t)}</button>` : ""}</label>
          <textarea id="quote" data-k="quote" rows="1" placeholder="${q ? "" : "No words matched to this ticket"}" ${q ? "" : "disabled"}>${esc(q ? q.text : "")}</textarea></div>
        <div class="field"><label>Shots</label><div class="shots">${
          (t.shots || [])
            .map(
              (s) => `
          <div class="shot ${s.use === false ? "off" : ""}" data-file="${esc(s.file)}">
            <div class="img" data-file="${esc(s.file)}" onclick="zoom(this.dataset.file)"><img src="${media(s.file)}" alt=""></div>
            <div class="row"><button onclick="seek(${s.t - 0.5})">▶ ${mmss(s.t)}</button><button onclick="toggleShot(this)">${s.use === false ? "Use" : "Drop"}</button></div>
            <div class="cap">${esc(s.caption)}</div></div>`,
            )
            .join("") ||
          '<span class="hint" style="padding-top:7px">No screenshots</span>'
        }</div></div>
        ${area("note", "Note", "Anything else for the programmer (optional)")}
        <div class="review-tools"><button class="text-button" onclick="openShare('${t.id}')">↗ Share request</button><button class="text-button" onclick="duplicateOpen()">↗ Link duplicate</button><span class="hint">Approval adds this request to a batch; it never starts code changes.</span></div><div class="redo">Need a better draft? <button onclick="redoOpen()">Redo this clip with a hint</button>
          <div class="redo-box" id="redo" hidden><input id="redoHint" aria-label="Correction for the analyst" placeholder="e.g. I meant the buttons on the right edge, not the bottom bar" onkeydown="if (event.key === 'Enter') redo()">
          <button class="btn" onclick="redo()">Redo</button></div></div>
        <div class="actions">
          <button class="btn reject" onclick="act('reject')">Reject<kbd>R</kbd></button>
          <button class="btn" onclick="act('later')">Later<kbd>L</kbd></button>
          <button class="btn go" onclick="act('approve')">Approve request<kbd>A</kbd></button>
        </div>
      </div>
    </div></div>`;
  renderTabs();
  sizeAll();
  requestAnimationFrame(sizeAll);
  document.querySelectorAll(".form [data-k]").forEach((el) =>
    el.addEventListener("input", () => {
      if (el.tagName === "TEXTAREA") autosize(el);
      const k = el.dataset.k;
      if ($("#saveState")) $("#saveState").textContent = "Saving…";
      dirty[k] = k === "steps" ? el.value.split("\n") : el.value;
      clearTimeout(saveTimer);
      saveTimer = setTimeout(() => flush().catch(() => {}), 600);
    }),
  );
  document.querySelectorAll(".chip[data-set]").forEach((el) =>
    el.addEventListener("click", () => {
      document
        .querySelectorAll(`.chip[data-set="${el.dataset.set}"]`)
        .forEach((c) => c.classList.toggle("on", c === el));
      dirty[el.dataset.set] = el.dataset.v;
      flush();
    }),
  );
  const v = $("#vid");
  v.addEventListener(
    "loadedmetadata",
    () => {
      sizeAll();
      v.currentTime = Math.max(0, (m.from || 0) - 1.5);
      // Let the reviewer choose when to play audio.
    },
    { once: true },
  );
}

function autosize(el) {
  el.style.height = "auto";
  el.style.height = el.scrollHeight + "px";
}
function sizeAll() {
  document.querySelectorAll(".form textarea").forEach(autosize);
}
window.addEventListener("resize", sizeAll);
function seek(t) {
  const v = $("#vid");
  if (!v) return;
  v.currentTime = Math.max(0, t);
  v.play().catch(() => {});
}
function zoom(file) {
  $("#lightbox img").src = media(file);
  $("#lightbox").classList.add("on");
  $("#lightbox").focus();
}

function toggleShot(btn) {
  const sh = btn.closest(".shot");
  sh.classList.toggle("off");
  btn.textContent = sh.classList.contains("off") ? "Use" : "Drop";
  dirty.useShots = [...document.querySelectorAll(".shot:not(.off)")].map(
    (s) => s.dataset.file,
  );
  flush();
}

async function flush() {
  clearTimeout(saveTimer);
  const id = cur,
    body = dirty;
  dirty = {};
  const previous = saving;
  saving = (async () => {
    await previous.catch(() => {});
    if (!id || !Object.keys(body).length) return;
    try {
      await api("/api/ticket/" + id, body);
      if ($("#saveState"))
        $("#saveState").textContent = Object.keys(dirty).length
          ? "Saving…"
          : "All changes saved";
      const t = drafts().find((t) => t.id === id);
      if (t)
        Object.assign(
          t,
          Object.fromEntries(
            Object.entries(body).filter(
              ([k]) => k !== "quote" && k !== "useShots",
            ),
          ),
        );
    } catch (e) {
      if (cur === id) dirty = { ...body, ...dirty };
      if ($("#saveState"))
        $("#saveState").textContent = "Not saved · retry when connected";
      toast("Changes not saved. " + e.message);
      throw e;
    }
  })();
  return saving;
}

async function act(what) {
  if (
    !cur ||
    acting ||
    view !== "review" ||
    document.querySelector("dialog[open]") ||
    $("#lightbox").classList.contains("on")
  )
    return;
  acting = true;
  document
    .querySelectorAll(".actions button,.form [data-k],.form .chip,.shot button")
    .forEach((b) => (b.disabled = true));
  try {
    await flush();
    const id = cur,
      i = drafts().findIndex((t) => t.id === id),
      next = drafts()[i + 1] || drafts()[i - 1];
    await api(`/api/ticket/${id}/${what}`);
    if (what === "approve")
      toast(`${id} approved. Added to your approved batch.`, "Undo", () =>
        api(`/api/ticket/${id}/review`).then(poll),
      );
    if (what === "reject")
      toast(`${id} rejected.`, "Undo", () =>
        api(`/api/ticket/${id}/review`).then(poll),
      );
    cur =
      what === "later"
        ? drafts().length > 1
          ? next.id
          : id
        : next
          ? next.id
          : null;
    lastJSON = "";
    await poll();
    if (cur && drafts().find((t) => t.id === cur)) buildCard();
  } catch (e) {
    toast(e.message);
  } finally {
    acting = false;
    document
      .querySelectorAll(
        ".actions button,.form [data-k],.form .chip,.shot button",
      )
      .forEach((b) => {
        if (b.id !== "quote" || drafts().find((t) => t.id === cur)?.quote)
          b.disabled = false;
      });
  }
}

function redoOpen() {
  const r = $("#redo");
  r.hidden = !r.hidden;
  if (!r.hidden) $("#redoHint").focus();
}
async function redo() {
  const t = drafts().find((x) => x.id === cur);
  const hint = $("#redoHint").value.trim();
  if (!t || !hint) {
    $("#redoHint").focus();
    return;
  }
  await flush();
  await api("/api/clip/retry", { clip: t.clip, hint });
  toast("Redoing that clip with your hint. The new draft shows up here.");
  cur = null;
  lastJSON = "";
  poll();
}

// ---------- the right column: hand-off, sent, failed, rejected ----------

function renderSide() {
  const trays = S.trays.filter((t) => !selectedGame || t.game === selectedGame);
  $("#side").innerHTML =
    trays
      .map((tr) => {
        const i = S.trays.indexOf(tr),
          repo = S.repositories?.[tr.game];
        const inFlight = (S.runs || []).find(
          (r) =>
            r.repository?.github === repo?.github &&
            [
              "queued",
              "preparing",
              "continuing",
        "retesting",
              "needs_review",
              "fixing",
              "testing",
              "publishing",
              "pr_ready",
              "merge_queued",
              "failed",
              "interrupted",
            ].includes(r.status),
        );
        const saved = (S.runs || []).slice().reverse().find((r) => canReviewRun(r) && r.repository?.github === repo?.github && r.tickets.every((id) => tr.ids.includes(id)));
        return `<article class="tray">${saved ? `<div class="run-review-callout"><b>You already have saved agent work for this batch.</b><p>${saved.result.addressed.length} implemented · ${saved.result.unaddressed.length} questions. Continue the existing branch instead of starting over.</p><button class="btn go compact" onclick="go('runs');openRun('${saved.id}')">Review agent notes →</button></div>` : ""}<div class="batch-heading"><div><div class="eyebrow">APPROVED BATCH</div><h2>${esc(tr.game)}</h2><p>${tr.ids.length} human-approved request${tr.ids.length === 1 ? "" : "s"}</p></div><div class="batch-share"><span class="badge done">Ready</span><button class="btn compact" data-game="${esc(tr.game)}" onclick="openShare(null, this.dataset.game)">↗ Share feedback</button></div></div>${tr.tickets.map((t) => `<div class="trow"><span class="id">${esc(t.id)}</span><b>${esc(t.title)}</b><button class="text-button" onclick="backToReview('${t.id}')">Edit / unapprove</button></div>`).join("")}<div class="repo-summary"><div><span class="eyebrow">FIXING AGENT</span><b>${repo ? esc(repo.github) : "No repository connected yet"}</b><p>${repo ? esc(repo.provider + " · " + (repo.model || "CLI default") + " · " + repo.base) + (repo.autoMerge ? " · auto merge enabled" : " · PR for review") : "Connect once. Every batch runs in its own branch."}</p></div><button class="btn compact" data-game="${esc(tr.game)}" onclick="connectRepo(this.dataset.game)">${repo ? "Configure" : "Connect repository"}</button></div><div class="batch-actions"><button class="btn" data-game="${esc(tr.game)}" onclick="openShare(null, this.dataset.game)">↗ Share feedback</button><button class="btn" onclick="copyTray(${i})">Copy prompt</button><button class="btn go" ${!repo || inFlight || batchBusy ? "disabled" : ""} onclick="sendBatch(${i})">${batchBusy ? "Starting…" : "Send batch to agent ↗"}</button></div>${inFlight ? '<p class="hint">Finish the active run or its PR before sending another batch to this repository. <button class="text-button" onclick="go(\'runs\')">View fix runs →</button></p>' : ""}<details><summary>What the agent receives</summary><pre>${esc(tr.prompt)}</pre></details></article>`;
      })
      .join("") ||
    '<div class="empty"><div class="empty-icon">✓</div><h2>Approval comes first.</h2><p>Review each request and approve the ones you want the agent to build. They collect here by game.</p><button class="btn go" onclick="go(\'review\')">Review requests →</button></div>';
}
async function copyText(txt) {
  try {
    await navigator.clipboard.writeText(txt);
    return true;
  } catch (e) {}
  const ta = document.createElement("textarea");
  ta.value = txt;
  ta.style.cssText = "position:fixed;opacity:0";
  document.body.appendChild(ta);
  ta.select();
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch (e) {}
  ta.remove();
  return ok;
}

async function copyTray(i) {
  const tr = S.trays[i];
  if (await copyText(tr.prompt))
    toast("Prompt copied. Requests stay approved until you send the batch.");
  else
    toast(
      'The browser blocked the clipboard. Use Drag, or copy it from "Preview the prompt".',
    );
}

let shareRequest = 0;
const shareIds = () => [...document.querySelectorAll('#shareTickets input:checked')].map(el => el.value);

async function openShare(id = null, batchGame = null) {
  if (!S) return toast('Wait for the desk to connect.');
  try {
    await flush();
    await poll();
    const single = id && S.tickets.find(t => t.id === id);
    const game = single ? single.game : (batchGame ?? selectedGame);
    const tickets = S.tickets.filter(t =>
      ['draft', 'approved', 'sent', 'fixing', 'fixed', 'verified'].includes(t.status) &&
      !t.duplicateOf && (!game || t.game === game));
    const approved = tickets.filter(t => t.status === 'approved');
    const initial = new Set(id ? [id] : (approved.length ? approved : tickets).map(t => t.id));
    $('#shareScope').textContent = game || 'All games';
    $('#shareTickets').innerHTML = tickets.map(t => `<label class="share-ticket"><input type="checkbox" value="${esc(t.id)}" ${initial.has(t.id) ? 'checked' : ''} onchange="updateShare()"><span><b>${esc(t.title)}</b><small>${esc(t.id)} · ${esc(t.game)} · ${esc(t.priority)} · ${t.status === 'draft' ? 'Draft · not yet approved' : esc(t.status)}</small></span></label>`).join('') || '<p>No feedback available yet. Analyse a recording first.</p>';
    $('#shareDialog').showModal();
    await updateShare();
  } catch (e) {
    toast(e.message);
  }
}

function selectShare(checked) {
  document.querySelectorAll('#shareTickets input').forEach(el => el.checked = checked);
  updateShare();
}

async function updateShare() {
  const request = ++shareRequest, ids = shareIds();
  $('#shareCount').textContent = `${ids.length} selected`;
  $('#copyFeedback').disabled = $('#downloadFeedback').disabled = true;
  $('#shareText').value = '';
  $('#shareStatus').textContent = ids.length ? 'Preparing feedback…' : 'Select at least one request.';
  if (!ids.length) return;
  try {
    const result = await api('/api/share-preview', { ids });
    if (request !== shareRequest) return;
    $('#shareText').value = result.text;
    $('#shareStatus').textContent = 'Attach the ZIP in Slack so your teammate can see the evidence.';
    $('#copyFeedback').disabled = $('#downloadFeedback').disabled = false;
  } catch (e) {
    if (request === shareRequest) $('#shareStatus').textContent = e.message;
  }
}

async function copyFeedback() {
  const ok = await copyText($('#shareText').value);
  $('#shareStatus').textContent = ok ? 'Copied. Paste into Slack and attach the ZIP for evidence.' : 'Select the message above and copy it with ⌘C.';
}

async function downloadFeedback() {
  const ids = shareIds();
  if (!ids.length) return;
  try {
    // Validate again in case the queue changed while the dialog was open.
    await api('/api/share-preview', { ids });
    const query = new URLSearchParams({ ids: ids.join(','), recordings: $('#shareRecordings').checked ? '1' : '0' });
    const link = document.createElement('a');
    link.href = '/api/share.zip?' + query;
    link.download = '';
    document.body.appendChild(link);
    link.click();
    link.remove();
    $('#shareStatus').textContent = 'Preparing your ZIP. Large recordings may take a moment before the save starts.';
  } catch (e) {
    $('#shareStatus').textContent = e.message;
  }
}

async function commit(tr, verb) {
  const r = await api("/api/handoff", { game: tr.game, ids: tr.ids });
  const n = tr.ids.length;
  if (r.ok)
    toast(
      `${verb} ${n} ${tr.game} ticket${n > 1 ? "s" : ""}. Paste into your programmer agent.`,
      "Undo",
      () =>
        api(`/api/handoff/${r.handoff.id}/undo`).then(() => {
          lastJSON = "";
          poll();
        }),
    );
  lastJSON = "";
  poll();
}

async function copySent(id) {
  const txt = await (await fetch(`/api/handoff/${id}.md`)).text();
  toast(
    (await copyText(txt))
      ? "Copied again."
      : "The browser blocked the clipboard.",
  );
}
async function undoSent(id) {
  await api(`/api/handoff/${id}/undo`);
  toast('Back in "Ready to hand off".');
  lastJSON = "";
  poll();
}
async function backToReview(id) {
  await api(`/api/ticket/${id}/review`);
  lastJSON = "";
  await poll();
  await go("review");
  await openTicket(id);
}
async function restore(id) {
  await api(`/api/ticket/${id}/review`);
  toast(`${id} is back in review.`);
  lastJSON = "";
  poll();
}
async function retry(clip) {
  await api("/api/clip/retry", { clip });
  toast("Trying that clip again.");
  lastJSON = "";
  poll();
}

let toastTimer;
function toast(msg, label, fn) {
  const el = $("#toast");
  el.innerHTML =
    `<span>${esc(msg)}</span>` +
    (label ? `<button>${esc(label)}</button>` : "");
  if (label)
    $("button", el).onclick = () => {
      el.classList.remove("on");
      fn();
    };
  el.classList.add("on");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("on"), label ? 7000 : 3500);
}

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    $("#lightbox").classList.remove("on");
    document.activeElement.blur();
    return;
  }
  if (
    view !== "review" ||
    document.querySelector("dialog[open]") ||
    $("#lightbox").classList.contains("on")
  )
    return;
  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
    e.preventDefault();
    act("approve");
    return;
  }
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(
    document.activeElement.tagName,
  );
  if (typing || e.metaKey || e.ctrlKey || e.altKey || !cur) return;
  const k = e.key.toLowerCase();
  if (k === "a") act("approve");
  else if (k === "r") act("reject");
  else if (k === "l") act("later");
});
window.addEventListener("beforeunload", (e) => {
  if (Object.keys(dirty).length || upload || acting) {
    e.preventDefault();
    e.returnValue = "";
  }
});
window.addEventListener("unhandledrejection", (e) => {
  e.preventDefault();
  toast(e.reason?.message || "The action failed. Please retry.");
});

// ---------- connection, recovery, imports and the fixing loop ----------
let confirmFn = null,
  batchBusy = false,
  upload = null,
  runOpen = null,
  repoCatalog = [],
  repoRequest = 0;
function age(seconds) {
  if (seconds < 60) return "just now";
  if (seconds < 3600) return Math.floor(seconds / 60) + "m ago";
  return Math.floor(seconds / 3600) + "h ago";
}
function renderHealth() {
  const r = S.receiver || {},
    elapsed = Date.now() / 1000 - (r.lastSeen || 0),
    live = elapsed < 30;
  $("#phoneStatus").innerHTML =
    `<span class="dot ${live ? "" : "paused"}"></span><div><b>${live ? esc(r.device) + " · " + esc(r.transport) : r.lastSeen ? "Phone last seen " + age(elapsed) : "No phone seen yet"}</b><small>${S.flags.receiverRunning ? "Receiver ready · USB & Wi-Fi" : "Receiver off · imports still work"}${!live && r.lastSeen ? " · keep the Android session open" : ""}</small><button class="text-button" onclick="openPairPhone()">Pair Android · ${esc(S.flags.pairing?.code || "Show code")}</button></div>`;
  const timing = S.timing || {},
    typ = timing.typicalSeconds,
    w = S.working;
  let msg =
    "Time estimates appear after 3 completed recordings. AI analysis can vary by model and clip length.";
  if (timing.sampleCount >= 3 && typ) {
    const remaining = w
        ? Math.max(0, typ - (Date.now() / 1000 - w.startedAt))
        : 0,
      total = remaining + S.queued * typ;
    msg = S.settings.paused
      ? "Queue paused. Receiving and review remain available."
      : total
        ? `Queue estimate: about ${Math.max(1, Math.ceil((total * 0.7) / 60))}–${Math.max(1, Math.ceil((total * 1.5) / 60))} min · based on ${timing.sampleCount} recent recordings. Longer clips can take more time.`
        : w
          ? "This analysis is taking longer than recent clips. It is still running."
          : "Ready for the next recording.";
  }
  $("#queueTiming").textContent = msg;
}
function openPairPhone() {
  $("#pairCode").textContent = S.flags.pairing?.code || "Restart the updated Mac app";
  $("#pairDialog").showModal();
}
function askAction(title, text, label, fn) {
  confirmFn = fn;
  $("#confirmTitle").textContent = title;
  $("#confirmText").textContent = text;
  $("#confirmButton").textContent = label;
  $("#confirmDialog").showModal();
}
async function confirmAction() {
  const fn = confirmFn;
  $("#confirmButton").disabled = true;
  try {
    await fn();
    $("#confirmDialog").close();
  } catch (e) {
    toast(e.message);
  } finally {
    $("#confirmButton").disabled = false;
  }
}
function trashClip(clip) {
  askAction(
    "Move this recording to trash?",
    "Its requests leave the queue and approved batch. The video and evidence stay on disk and can be restored from History & trash.",
    "Move to trash",
    async () => {
      await api("/api/clip/trash", { clip });
      await poll();
      toast("Recording moved to trash.", "Undo", () =>
        api("/api/clip/trash", { clip, restore: true }).then(poll),
      );
    },
  );
}
async function restoreClip(clip) {
  await api("/api/clip/trash", { clip, restore: true });
  await poll();
  toast("Recording restored.");
}
function duplicateOpen() {
  const t = drafts().find((t) => t.id === cur);
  if (!t) return;
  const list = (S.tickets || []).filter(
    (x) =>
      x.id !== t.id &&
      x.game === t.game &&
      !["deleted", "rejected", "duplicate"].includes(x.status),
  );
  $("#duplicateTarget").innerHTML = list
    .map(
      (x) =>
        `<option value="${x.id}">${esc(x.id + " · " + x.title + " · " + x.status)}</option>`,
    )
    .join("");
  if (!list.length) {
    toast("No other request exists for this game yet.");
    return;
  }
  if (t.duplicateCandidates?.length)
    $("#duplicateTarget").value = t.duplicateCandidates[0].id;
  $("#duplicateDialog").showModal();
  duplicatePreview();
}
function duplicatePreview() {
  const t = (S.tickets || []).find((t) => t.id === $("#duplicateTarget").value);
  $("#duplicatePreview").textContent = t
    ? ["Observed: " + (t.now || ""), "Expected: " + (t.want || "")].join("\n")
    : "";
}
$("#duplicateTarget").onchange = duplicatePreview;
async function linkDuplicate() {
  await flush();
  const id = cur;
  await api(`/api/ticket/${id}/duplicate`, {
    target: $("#duplicateTarget").value,
  });
  $("#duplicateDialog").close();
  cur = null;
  await poll();
  toast("Linked as a duplicate. Evidence kept.", "Undo", () =>
    api(`/api/ticket/${id}/unlink`).then(poll),
  );
}
async function unlink(id) {
  await api(`/api/ticket/${id}/unlink`);
  await poll();
  toast("Request returned to review.");
}
function renderArchive() {
  const within = (x) => !selectedGame || x.game === selectedGame;
  const duplicates = (S.tickets || []).filter(
    (t) => t.status === "duplicate" && within(t),
  );
  const rows = (items, fn, empty) =>
    items.map(fn).join("") || `<p class="hint">${empty}</p>`;
  $("#archive").innerHTML =
    `<section class="archive-block"><h2>Recoverable trash <span>${(S.trash || []).filter(within).length}</span></h2>${rows((S.trash || []).filter(within), (c) => `<div class="srow"><div><b>${esc(c.game)}</b><small>${esc(clipName(c.clip))}</small></div><button class="btn compact" data-clip="${esc(c.clip)}" onclick="restoreClip(this.dataset.clip)">Restore recording</button></div>`, "No recordings in trash.")}</section><section class="archive-block"><h2>Linked duplicates <span>${duplicates.length}</span></h2>${rows(duplicates, (t) => `<div class="srow"><div><b>${esc(t.title)}</b><small>${t.id} → ${esc(t.duplicateOf)} · ${esc(t.game)}</small><details><summary>Retained observation & evidence</summary><p>${esc(t.now)}</p>${(t.shots || []).map((s) => `<button class="text-button" data-file="${esc(s.file)}" onclick="zoom(this.dataset.file)">View screenshot ↗</button>`).join("")}</details></div><button class="btn compact" onclick="unlink('${t.id}')">Separate / restore</button></div>`, "No findings linked as duplicates.")}</section><section class="archive-block"><h2>Rejected requests</h2>${rows(S.rejected.filter(within), (t) => `<div class="srow"><div><b>${esc(t.title)}</b><small>${t.id} · ${esc(t.game)}</small></div><button class="btn compact" onclick="restore('${t.id}')">Review again</button></div>`, "No rejected requests.")}</section><section class="archive-block"><h2>Earlier prompt exports</h2>${rows(S.sent.filter(within), (h) => `<div class="srow"><div><b>${esc(h.game)} · ${h.tickets.length} requests</b><small>${esc(h.at)} · ${h.id}</small></div><button class="text-button" onclick="copySent('${h.id}')">Copy again</button><button class="btn compact" onclick="undoSent('${h.id}')">Return to batch</button></div>`, "No previous exports.")}</section>`;
}
function openImport(batch = false) {
  if (!S) return;
  if (upload) return;
  $("#importGame").innerHTML = '<option value="">Choose game…</option>' + (S.games || [])
    .map((g) => `<option value="${esc(g)}">${esc(g)}</option>`)
    .join("");
  if (selectedGame) $("#importGame").value = selectedGame;
  $('#importPlatform').value = batch ? 'AndroidBatch' : 'iOS';
  $('#importFile').value = '';
  $('#fileName').textContent = batch ? 'Drop a batch ZIP here, or choose a file' : 'Drop a recording here, or choose a file';
  $('#importStatus').textContent = '';
  updateImportMode();
  $("#importDialog").showModal();
}
function updateImportMode() {
  const batch = $('#importPlatform').value === 'AndroidBatch';
  $('#batchGuide').hidden = !batch;
  $('#recordingGuide').hidden = batch;
  $('#importGameField').hidden = batch;
  $('#importGame').required = !batch;
  $('#importButton').textContent = batch ? 'Import batch & analyse' : 'Import & analyse';
}
function closeImport() {
  if (upload) {
    toast("Import is in progress. Keep this tab open until it completes.");
    return;
  }
  $("#importDialog").close();
}
$("#importDialog").addEventListener("cancel", (e) => {
  if (upload) e.preventDefault();
});
function setFile(file) {
  if (!file) return;
  const dt = new DataTransfer();
  dt.items.add(file);
  $("#importFile").files = dt.files;
  $("#fileName").textContent = file.name;
  if (/\.zip$/i.test(file.name)) $('#importPlatform').value = 'AndroidBatch';
  else if ($('#importPlatform').value === 'AndroidBatch') $('#importPlatform').value = 'Imported';
  updateImportMode();
}
$("#dropZone").addEventListener("dragover", (e) => {
  e.preventDefault();
  $("#dropZone").classList.add("over");
});
$("#dropZone").addEventListener("dragleave", () =>
  $("#dropZone").classList.remove("over"),
);
$("#dropZone").addEventListener("drop", (e) => {
  e.preventDefault();
  $("#dropZone").classList.remove("over");
  setFile(e.dataTransfer.files[0]);
});
document.addEventListener("dragover", (e) => {
  if (e.dataTransfer.types.includes("Files")) e.preventDefault();
});
document.addEventListener("drop", (e) => {
  if (e.defaultPrevented || !e.dataTransfer.files.length) return;
  e.preventDefault();
  openImport();
  setFile(e.dataTransfer.files[0]);
});
async function importRecording() {
  const file = $("#importFile").files[0],
    game = $("#importGame").value;
  const batch = $('#importPlatform').value === 'AndroidBatch';
  if (!file || (!batch && !game) || upload) return;
  if (file.size > (batch ? 2048 : 750) * 1024 * 1024) {
    $("#importStatus").textContent = batch ? 'Choose a batch under 2 GB.' : "Trim your recording under 750 MB first.";
    return;
  }
  $("#importButton").disabled = true;
  $("#importStatus").textContent = "Uploading…";
  const xhr = new XMLHttpRequest();
  upload = xhr;
  xhr.open("POST", batch ? '/api/import-batch' : "/api/import");
  xhr.setRequestHeader("Content-Type", "application/octet-stream");
  xhr.setRequestHeader("X-Game", encodeURIComponent(game));
  xhr.setRequestHeader("X-Filename", encodeURIComponent(file.name));
  xhr.setRequestHeader("X-Platform", $("#importPlatform").value);
  xhr.timeout = batch ? 1200000 : 360000;
  xhr.upload.onprogress = (e) => {
    $("#importStatus").textContent = e.lengthComputable
      ? e.loaded === e.total
        ? batch ? 'Checking the batch recordings…' : "Preparing the recording for analysis…"
        : "Uploading " + Math.round((e.loaded / e.total) * 100) + "%"
      : "Uploading…";
  };
  const finish = () => {
    upload = null;
    $("#importButton").disabled = false;
  };
  xhr.onload = async () => {
    finish();
    let r;
    try {
      r = JSON.parse(xhr.responseText);
    } catch {
      r = { error: "Import failed. Try again." };
    }
    if (xhr.status !== 200) {
      $("#importStatus").textContent = r.error;
      return;
    }
    $("#importStatus").textContent = "";
    $("#importDialog").close();
    await poll();
    await go("videos");
    toast(
      batch ? `${r.imported} recording(s) imported · ${r.duplicates} already received.` + (S.settings.paused ? ' Resume the queue when ready.' : ' Analysis starts automatically.') : r.duplicate
        ? "This exact recording is already in your queue. No duplicate was created."
        : S.settings.paused
          ? "Imported. Resume the queue when ready."
          : "Imported. The analyst will process it automatically.",
    );
  };
  xhr.onerror = xhr.ontimeout = () => {
    finish();
    $("#importStatus").textContent =
      "Connection interrupted. Retry the same file safely; it will not create a second recording.";
  };
  xhr.send(file);
}
let repoInspection = null, repoChecking = false, repoSaving = false, repoModelLoading = false, repoInspectRequest = 0;
function repoActions() {
  const checked = repoInspection && repoInspection.source === $("#repoSource").value.trim() && repoInspection.game === $("#repoGame").value;
  $("#repoSave").disabled = !checked || repoChecking || repoSaving || repoModelLoading || !$("#repoTest").value.trim();
  $("#repoCheck").disabled = !$("#repoGame").value || !$("#repoSource").value.trim() || repoChecking || repoSaving;
  $("#repoCheck").textContent = repoChecking ? "Checking GitHub…" : "Check repository";
  $("#repoSave").textContent = repoSaving ? "Connecting…" : "Connect game";
  for (const id of ["repoSource", "repoGame", "repoBase", "repoTest", "repoProvider", "repoAuto"]) $("#" + id).disabled = repoSaving;
  $("#repoModel").disabled = repoSaving || repoModelLoading;
  const model = repoCatalog.find((m) => m.id === $("#repoModel").value);
  $("#repoEffort").disabled = repoSaving || (!model?.efforts?.length && !$("#repoEffort").value);
}
function repoChanged() {
  ++repoInspectRequest; repoInspection = null; repoChecking = false;
  $("#repoPreview").hidden = true; $("#repoError").textContent = ""; $("#repoProgress").textContent = "";
  repoActions();
}
function repoSummary() {
  if (!repoInspection) return;
  const repo = repoInspection.repo;
  $("#repoSummaryName").textContent = repo.github;
  $("#repoSummaryBranch").textContent = $("#repoBase").value.trim() || repo.base;
  $("#repoSummaryCheck").textContent = $("#repoTest").value.trim() === repo.testCommand ? repo.checkLabel || "Project checks" : "Custom project check";
  $("#repoCheckNote").textContent = repo.checkNote || "Your verification command runs after each fixing batch.";
  const model = $("#repoModel").selectedOptions[0]?.textContent || "CLI configured default";
  $("#repoSummaryAgent").textContent = ($("#repoProvider").value === "codex" ? "Codex · " : "Claude · ") + model + ($("#repoEffort").value ? " · " + $("#repoEffort").value : "");
}
async function connectRepo(game = selectedGame) {
  if (!S.games?.length) { addGameOpen(); return; }
  $("#repoGame").innerHTML = '<option value="">Choose a game…</option>' + S.games.map((g) => `<option value="${esc(g)}">${esc(g)}</option>`).join("");
  if (game) $("#repoGame").value = game;
  $("#repoDialog").showModal();
  await fillRepo();
}
async function fillRepo() {
  ++repoInspectRequest; repoChecking = false; repoSaving = false;
  const game = $("#repoGame").value, r = S.repositories?.[game];
  $("#repoTitle").textContent = game ? "Connect " + game : "Connect your game";
  $("#repoSource").value = r?.github ? "https://github.com/" + r.github : "";
  $("#repoBase").value = r?.base || "";
  $("#repoTest").value = r?.testCommand || "";
  $("#repoAuto").checked = !!r?.autoMerge;
  $("#repoProvider").value = r?.provider || S.settings.provider;
  $("#repoError").textContent = ""; $("#repoProgress").textContent = "";
  $("#repoAdvanced").open = false;
  repoInspection = r ? {source: $("#repoSource").value, game, repo: r} : null;
  $("#repoPreview").hidden = !r;
  repoActions();
  await repoModels(r ? r.model : S.settings.model, r ? r.effort : S.settings.effort);
  repoSummary();
}
async function checkRepository() {
  const source = $("#repoSource").value.trim(), game = $("#repoGame").value, request = ++repoInspectRequest;
  if (!source || !game || repoSaving) return;
  repoChecking = true; repoInspection = null; $("#repoPreview").hidden = true;
  $("#repoError").textContent = ""; $("#repoProgress").textContent = "Checking GitHub access and finding the game’s build/test scripts…";
  repoActions();
  try {
    const response = await api("/api/repository/inspect", {source});
    if (request !== repoInspectRequest || source !== $("#repoSource").value.trim() || game !== $("#repoGame").value) return;
    const repo = response.result;
    repoInspection = {source, game, repo};
    $("#repoBase").value = repo.base; $("#repoTest").value = repo.testCommand || "";
    $("#repoPreview").hidden = false; $("#repoProgress").textContent = repo.testCommand ? "Ready. Review the setup, then connect this game." : "One more step: add your project’s verification command below.";
    if (!repo.testCommand) $("#repoAdvanced").open = true;
    repoSummary();
  } catch (e) {
    if (request === repoInspectRequest) { $("#repoError").textContent = e.message; $("#repoProgress").textContent = ""; }
  } finally { if (request === repoInspectRequest) { repoChecking = false; repoActions(); } }
}
async function repoModels(model = "", effort = "") {
  const request = ++repoRequest;
  repoModelLoading = true; repoActions();
  $("#repoModel").disabled = true;
  $("#repoModelInfo").textContent = "Reading the installed CLI catalog…";
  try {
    const r = await fetch("/api/models?provider=" + $("#repoProvider").value);
    const data = await r.json();
    if (request !== repoRequest) return;
    repoCatalog = data.models || [];
    $("#repoModel").innerHTML =
      '<option value="">CLI configured default</option>' +
      repoCatalog
        .map((m) => `<option value="${esc(m.id)}">${esc(m.name)}</option>`)
        .join("");
    if (model && !repoCatalog.some((m) => m.id === model))
      $("#repoModel").add(new Option(model + " · saved", model));
    $("#repoModel").value = model;
    repoEfforts(effort);
    $("#repoModelInfo").textContent =
      data.error ||
      "Uses your CLI login. Fixing settings are separate from the video analyst.";
  } catch (e) {
    if (request !== repoRequest) return;
    repoCatalog = [];
    $("#repoModel").innerHTML =
      '<option value="">CLI configured default</option>';
    if (model) { $("#repoModel").add(new Option(model + " · saved", model)); $("#repoModel").value = model; }
    repoEfforts(effort);
    $("#repoModelInfo").textContent =
      "Catalog unavailable. Your chosen model is preserved; refresh settings later.";
  } finally {
    if (request === repoRequest) {
      repoModelLoading = false; repoActions(); repoSummary();
      $("#repoModel").disabled = false;
    }
  }
}
function repoEfforts(selected = "") {
  const m = repoCatalog.find((m) => m.id === $("#repoModel").value);
  $("#repoEffort").innerHTML =
    '<option value="">CLI default effort</option>' +
    (m?.efforts || [])
      .map((e) => `<option value="${e}">${e}</option>`)
      .join("");
  $("#repoEffort").disabled = !m?.efforts?.length;
  if (selected && !(m?.efforts || []).includes(selected)) {
    $("#repoEffort").add(new Option(selected + " · saved, verify", selected)); $("#repoEffort").disabled = false;
  }
  $("#repoEffort").value = selected;
  repoSummary();
}
async function saveRepo() {
  if (!repoInspection || repoSaving || repoChecking || repoModelLoading) return;
  const source = $("#repoSource").value.trim(), game = $("#repoGame").value;
  if (source !== repoInspection.source || game !== repoInspection.game) { repoChanged(); return; }
  repoSaving = true; repoActions();
  $("#repoError").textContent = ""; $("#repoProgress").textContent = "Saving the game’s repository connection…";
  try {
    await api("/api/repository", {
      game, source, base: $("#repoBase").value.trim(), testCommand: $("#repoTest").value.trim(),
      provider: $("#repoProvider").value, model: $("#repoModel").value,
      effort: $("#repoEffort").value, autoMerge: $("#repoAuto").checked,
    });
    $("#repoDialog").close(); await poll();
    toast("Repository connected. Send approved requests when you’re ready.");
  } catch (e) { $("#repoError").textContent = e.message; $("#repoProgress").textContent = ""; }
  finally { repoSaving = false; repoActions(); }
}
async function sendBatch(i) {
  if (batchBusy) return;
  batchBusy = true;
  const tray = S.trays[i];
  renderSide();
  try {
    await api("/api/run", { game: tray.game, ids: tray.ids });
    await poll();
    await go("runs");
    toast("Batch sent. Follow the branch, checks and PR here.");
  } catch (e) {
    toast(e.message);
  } finally {
    batchBusy = false;
    if (view === "handoffs") renderSide();
  }
}
const runLabels = {
  queued: "Waiting to start",
  preparing: "Preparing repository",
  fixing: "Agent implementing requests",
  testing: "Verifying changes",
  publishing: "Publishing PR",
  recovering: "Recovering publication",
  continuing: "Continuing saved work",
  retesting: "Retrying checks · work saved",
  needs_review: "Your answers needed",
  pr_ready: "PR ready for review",
  merge_queued: "Merge queued on GitHub",
  merged: "Merged · playtest again",
  failed: "Needs attention",
  interrupted: "Interrupted · work saved",
  cancelled: "Cancelled · tickets returned",
  closed: "PR closed without merging",
};
function runSteps(r) {
  const order = [
      "preparing",
      "fixing",
      "testing",
      "publishing",
      "pr_ready",
      "merged",
    ],
    index = order.indexOf(canReviewRun(r) || r.status === "continuing" ? "fixing" : r.status === "retesting" ? "testing" : r.status === "merge_queued" ? "pr_ready" : r.status);
  return `<div class="run-steps">${["Branch", "Implement", "Verify", "PR", "Review / merge", "Playtest"].map((s, i) => `<span class="${i < index ? "complete" : i === index ? "current" : ""}">${i < index ? "✓" : i + 1} ${s}</span>`).join("")}</div>`;
}
function runActions(r) {
  const editable = [
    "queued",
    "preparing",
    "continuing",
        "retesting",
    "needs_review",
    "fixing",
    "testing",
    "failed",
    "interrupted",
  ].includes(r.status);
  return `<div class="run-actions">${canReviewRun(r) ? `<button class="btn go compact" onclick="openRun('${r.id}')">Review agent notes · ${r.result.unaddressed.length} →</button>` : ""}<button class="btn compact" onclick="openRun('${r.id}')">Details & log</button>${r.pr ? `<a class="btn compact" target="_blank" rel="noopener" href="${esc(r.pr)}">Open PR ↗</a><button class="text-button" onclick="runAction('${r.id}','refresh')">Refresh GitHub</button>` : ""}${["pr_ready", "merge_queued"].includes(r.status) && r.repository.autoMerge && !r.autoMergeDisabled ? `<button class="text-button" onclick="runAction('${r.id}','disable_merge')">Stop auto merge</button>` : ""}${r.status === "pr_ready" && !r.autoMergeDisabled ? `<button class="btn go compact" onclick="mergeRun('${r.id}')">Queue merge</button>` : ""}${editable ? `<button class="text-button danger-text" onclick="cancelRun('${r.id}')">${["failed", "interrupted", "needs_review"].includes(r.status) ? "Return tickets to batch" : "Cancel run"}</button>` : ""}${["failed", "interrupted"].includes(r.status) && !r.headSha && r.result?.addressed?.length === r.tickets.length && !r.result?.unaddressed?.length ? `<button class="btn go compact" onclick="runAction('${r.id}','retry_checks')">Retry checks on saved work →</button>` : ""}${["failed", "interrupted"].includes(r.status) && r.testsPassed ? `<button class="btn compact" onclick="runAction('${r.id}','recover')">Recover publication</button>` : ""}</div>`;
}
function renderRuns() {
  const runs = (S.runs || [])
    .filter((r) => !selectedGame || r.game === selectedGame)
    .slice()
    .reverse();
  const fixes = (S.tickets || []).filter(
    (t) => t.status === "fixed" && (!selectedGame || t.game === selectedGame),
  );
  $("#runs").innerHTML =
    (fixes.length
      ? `<section class="retest-panel"><div class="eyebrow">CLOSE THE LOOP</div><h2>Playtest these changes in the new build.</h2><p>Merge is recorded. Confirm the behavior in the game, or send a request back with what still needs work.</p>${fixes.map((t) => `<div class="srow"><div><b>${esc(t.title)}</b><small>${t.id} · ${esc(t.game)}</small></div><button class="btn compact" onclick="verifyFix('${t.id}',false)">Still needs work</button><button class="btn go compact" onclick="verifyFix('${t.id}',true)">Verified in game ✓</button></div>`).join("")}</section>`
      : "") +
    runs
      .map(
        (r) =>
          `<article class="run-card"><div class="batch-heading"><div><div class="eyebrow">${esc(r.repository.github)} · ${r.tickets.length} REQUESTS</div><h2>${esc(r.game)}</h2><p>${esc(r.repository.provider)} · ${esc(r.repository.model || "CLI default")} · <span data-run-clock="${r.id}">${r.startedAt ? mmss((r.completedAt || Date.now() / 1000) - r.startedAt) + " elapsed" : age((Date.now() - new Date(r.created)) / 1000)}</span></p></div><span class="badge ${["failed", "interrupted"].includes(r.status) ? "failed" : r.status === "merged" ? "done" : "working"}">${esc(canReviewRun(r) ? "Your answers needed · work saved" : runLabels[r.status] || r.status)}</span></div>${runSteps(r)}<p class="run-summary">${esc(r.result?.summary || "The agent works only on the approved requests in this batch.")}</p>${canReviewRun(r) ? `<p class="run-review-callout"><b>${r.result.addressed.length} implemented · ${r.result.unaddressed.length} need your decisions</b><br>Saved changes are kept. Answer the agent here and continue this branch.</p>` : ""}<div class="ticket-tags">${r.tickets.map((id) => `<span>${esc(id)}</span>`).join("")}</div>${r.error ? `<div class="error-box">${esc(r.error)}</div>` : ""}${r.mergeError || r.githubError ? `<p class="fail">${esc(r.mergeError || r.githubError)}</p>` : ""}${runActions(r)}</article>`,
      )
      .join("") +
    (runs.length
      ? ""
      : '<div class="empty"><div class="empty-icon">↗</div><h2>Your next fix starts with approval.</h2><p>Connect a game repository, review the requests, and send a batch. Runs will appear here automatically.</p><button class="btn go" onclick="go(\'handoffs\')">Open approved batches →</button></div>');
  if ($("#runDialog").open) renderRunDetail();
}
async function openRun(id) {
  runOpen = id; runReviewKey = null;
  $("#runDialog").showModal();
  renderRunDetail();
  await loadRunLog();
}
function renderRunDetail() {
  const r = (S.runs || []).find((r) => r.id === runOpen);
  if (!r) return;
  $("#runTitle").textContent =
    r.game + " · " + (runLabels[r.status] || r.status);
  $("#runDetail").innerHTML =
    `${runSteps(r)}<p>${esc(r.result?.summary || "Working from your approved batch.")}</p><dl><dt>Branch</dt><dd>${esc(r.branch)}</dd><dt>Check command</dt><dd>${esc(r.repository.testCommand)}</dd><dt>Saved run folder</dt><dd>${esc("AgentRuns/" + r.id)} in your inbox</dd></dl>${r.result?.notes ? `<details class="agent-notes"><summary>All agent notes · ${r.result.addressed.length} implemented, ${r.result.unaddressed.length} pending</summary><pre>${esc(r.result.notes)}</pre></details>` : ""}${r.diff ? `<pre>${esc(r.diff)}</pre>` : ""}${r.error ? `<p class="fail">${esc(r.error)}</p>` : ""}`;
  renderRunReview(r);
}
let runReviewKey = null, runReviewDraft = null, runReviewIndex = 0, runReviewBusy = false;
function canReviewRun(r) {
  return ["needs_review", "failed", "interrupted", "cancelled"].includes(r.status) && r.result?.unaddressed?.length && !r.headSha && !r.pr;
}
function runReviewStorage(r) { return "qa-run-review-" + r.id; }
function renderRunReview(r) {
  const section = $("#runReview");
  section.hidden = !canReviewRun(r);
  if (section.hidden) return;
  const key = r.id + JSON.stringify(r.result);
  if (runReviewKey === key) return; // Polling must never replace a typed answer or its selection.
  runReviewKey = key; runReviewIndex = 0; runReviewBusy = false;
  let local;
  try { local = JSON.parse(localStorage.getItem(runReviewStorage(r))); } catch {}
  runReviewDraft = {answers: {...(local?.answers || r.review?.answers || {})}, note: local?.note ?? r.review?.note ?? ""};
  section.innerHTML = `<div class="eyebrow">KEEP THE WORK. ANSWER THE QUESTIONS.</div><h3>Review agent notes</h3><p>${r.result.addressed.length} requests implemented. ${r.result.unaddressed.length} need your decisions. Continuing keeps this run’s saved changes, evidence and branch.</p><nav id="runQuestions" aria-label="Agent questions"></nav><div id="runQuestionBody"></div><label for="runReviewExtra">Anything else for the agent? <span class="hint">Optional</span></label><textarea id="runReviewExtra" rows="2" maxlength="8000" oninput="editRunReview()" placeholder="Feedback on the implemented changes or overall approach…">${esc(runReviewDraft.note)}</textarea><p id="runReviewStatus" class="hint" role="status">${r.review?.savedAt ? "Previously saved answers loaded. You can edit them." : "Draft answers stay on this Mac as you type. Save answers to keep them with this run."}</p><p id="runReviewError" class="fail" role="alert"></p><div class="run-review-buttons"><button class="btn" id="runReviewSave" onclick="saveRunReview(false)">Save answers</button><button class="btn go" id="runReviewContinue" onclick="saveRunReview(true)">Continue saved work →</button></div><p class="hint">Continue starts ${esc(r.repository.provider)} · ${esc(r.repository.model || "CLI default")} on the existing branch. Project checks must pass before a PR can be published. Saving answers does not start an agent.</p>`;
  renderRunQuestion(r);
}
function runQuestionNote(r, id) {
  const blocks = (r.result.notes || "").split(/(?=^[A-Z0-9]+-\d+\s*[—–:−-])/m);
  return blocks.filter((b) => b.trim().startsWith(id + " ") || b.trim().startsWith(id + ":")).join("\n").trim() || r.result.notes || "The agent needs clarification for this request.";
}
function renderRunQuestion(r) {
  const pending = r.result.unaddressed, id = pending[runReviewIndex];
  const t = r.snapshot.find((t) => t.id === id) || {id, title:id};
  $("#runQuestions").innerHTML = pending.map((tid, i) => `<button class="btn compact ${i === runReviewIndex ? "selected" : ""}" aria-current="${i === runReviewIndex ? "step" : "false"}" onclick="selectRunQuestion(${i})">${runReviewDraft.answers[tid]?.trim() ? "✓ " : ""}${esc(tid)}</button>`).join("");
  $("#runQuestionBody").innerHTML = `<div class="run-question-heading"><span class="eyebrow">QUESTION ${runReviewIndex + 1} OF ${pending.length}</span><span><button class="text-button" data-boundary="${runReviewIndex === 0}" ${runReviewIndex === 0 ? "disabled" : ""} onclick="selectRunQuestion(${runReviewIndex - 1})">← Previous</button><button class="text-button" data-boundary="${runReviewIndex === pending.length - 1}" ${runReviewIndex === pending.length - 1 ? "disabled" : ""} onclick="selectRunQuestion(${runReviewIndex + 1})">Next →</button></span></div><h3>${esc(t.title)}</h3><div class="agent-question"><small>AGENT NEEDS TO KNOW</small><p>${esc(runQuestionNote(r,id))}</p></div><details><summary>Original approved request & recording</summary><p>${esc(t.want)}</p><p><b>Done when:</b> ${esc(t.done_when)}</p>${t.clip ? `<video src="${media(t.clip)}" controls playsinline preload="none"></video>` : ""}</details><label for="runReviewAnswer">Your answer for ${esc(id)}</label><textarea id="runReviewAnswer" rows="4" maxlength="4000" oninput="editRunReview()" placeholder="Give the missing decision so the agent can finish this request…">${esc(runReviewDraft.answers[id] || "")}</textarea>`;
  runReviewActions(r);
}
function selectRunQuestion(index) {
  const r = S.runs.find((r) => r.id === runOpen);
  if (!r || runReviewBusy || index < 0 || index >= r.result.unaddressed.length) return;
  editRunReview(); runReviewIndex = index; renderRunQuestion(r); $("#runReviewAnswer").focus();
}
function editRunReview() {
  const r = S.runs.find((r) => r.id === runOpen);
  if (!r || !runReviewDraft) return;
  runReviewDraft.answers[r.result.unaddressed[runReviewIndex]] = $("#runReviewAnswer").value;
  runReviewDraft.note = $("#runReviewExtra").value;
  try { localStorage.setItem(runReviewStorage(r), JSON.stringify(runReviewDraft)); $("#runReviewStatus").textContent = "Draft kept on this Mac. Save answers to keep them with the run."; }
  catch { $("#runReviewStatus").textContent = "Browser draft storage unavailable. Use Save answers before closing."; }
  runReviewActions(r);
}
function runReviewActions(r) {
  $("#runReviewSave").disabled = runReviewBusy;
  $("#runReviewContinue").disabled = runReviewBusy || r.result.unaddressed.some((id) => !runReviewDraft.answers[id]?.trim());
  $("#runReviewContinue").textContent = runReviewBusy ? "Saving…" : "Continue saved work →";
  for (const el of $("#runReview").querySelectorAll("textarea, #runQuestions button, #runQuestionBody button")) el.disabled = runReviewBusy || el.dataset.boundary === "true";
}
async function saveRunReview(continueWork) {
  const r = S.runs.find((r) => r.id === runOpen);
  if (!r || runReviewBusy) return;
  editRunReview();
  const body = {answers:Object.fromEntries(r.result.unaddressed.map((id) => [id, runReviewDraft.answers[id] || ""])),note:runReviewDraft.note};
  if (continueWork && Object.values(body.answers).some((v) => !v.trim())) return;
  runReviewBusy = true; runReviewActions(r); $("#runReviewError").textContent = "";
  try {
    await api(`/api/run/${r.id}/${continueWork ? "continue" : "review"}`, body);
    try { localStorage.removeItem(runReviewStorage(r)); } catch {}
    await poll();
    if (continueWork) { toast("Continuing the saved branch. Existing work is kept."); }
    else $("#runReviewStatus").textContent = "Answers saved with this run. The agent has not started.";
  } catch (e) { $("#runReviewError").textContent = e.message; }
  finally { runReviewBusy = false; if (!$("#runReview").hidden) runReviewActions(r); }
}
async function loadRunLog() {
  if (!$("#runDialog").open || !runOpen) return;
  try {
    const r = await fetch(`/api/run/${runOpen}/log`);
    const d = await r.json();
    $("#runLog").textContent = d.text || "No output yet.";
  } catch {
    $("#runLog").textContent = "Could not load the log. Reconnect the desk.";
  }
}
setInterval(loadRunLog, 3000);
async function runAction(id, action) {
  await api(`/api/run/${id}/${action}`);
  await poll();
  toast(
    action === "recover"
      ? "Recovering the verified branch and PR."
      : action === "retry_checks" ? "Retrying checks on the saved branch. The agent will not rerun." : "Run updated.",
  );
}
function cancelRun(id) {
  askAction(
    "Return this batch to approval?",
    "Use Review agent notes to answer questions and continue the saved branch. Returning tickets releases this batch so you can start fresh; saved files and logs remain in your inbox. Published PRs must be finished on GitHub first.",
    "Stop & return tickets",
    () => runAction(id, "cancel"),
  );
}
function mergeRun(id) {
  askAction(
    "Queue this PR to merge?",
    "GitHub checks and required branch rules must pass. Only the exact agent commit can be merged. The next step is to install a new game build and playtest the fixes.",
    "Queue merge",
    () => runAction(id, "merge"),
  );
}
async function verifyFix(id, passed) {
  await api(`/api/ticket/${id}/verify`, { passed });
  await poll();
  toast(
    passed
      ? "Verified in game. The loop is complete for this request."
      : "Returned to review. Add what still needs work before approving again.",
  );
}
