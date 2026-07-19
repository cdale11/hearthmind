"use strict";

// Hearthmind browser window — read-only, no build step (see docs/DECISIONS.md, F1/F2).
// Terrain is fetched once (it never changes); everything else arrives via
// GET /state (initial paint) and then a WebSocket stream, one message per
// tick, in the exact same shape.

const CELL = 8; // px per terrain tile

// Shared upward-pointing triangle path (predator packs, and the LLM
// core-cast agent marker, v0.72.0) — fill/stroke style is the caller's
// choice; this only builds the path via the current fillStyle/context
// transform, does not begin/close/fill on its own beyond what's needed
// to leave a closed path ready to fill or stroke.
function drawAgentTriangle(ctx, cx, cy, r) {
  ctx.beginPath();
  ctx.moveTo(cx, cy - r);
  ctx.lineTo(cx - r, cy + r);
  ctx.lineTo(cx + r, cy + r);
  ctx.closePath();
}

// Skips the innerHTML write (and the reflow/scroll-reset it causes) when
// the new markup is identical to what's already there — most ticks don't
// actually change a slow-growing list (beliefs/traditions/inventions/
// festivals/infrastructure), so this both cuts needless per-tick DOM churn
// and stops a user's mid-scroll position in one of these panels from
// snapping back to the top on every message. See docs/DECISIONS.md, UI
// flicker fix.
function setInnerHTMLIfChanged(el, html) {
  if (!el || el.__lastHtml === html) return;
  el.__lastHtml = html;
  el.innerHTML = html;
}

function escapeHtmlAttr(text) {
  return String(text).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
}

// --- stat-grid hover tooltip -------------------------------------------------
// Delegated on the stable `#stat-grid` container (not the tiles inside it,
// which get replaced wholesale on nearly every broadcast — see the
// `data-tooltip` comment above) so hover keeps working regardless of how
// often the grid's own DOM churns underneath the cursor.
{
  const statGrid = document.getElementById("stat-grid");
  const statTooltip = document.getElementById("stat-tooltip");
  if (statGrid && statTooltip) {
    statTooltip.style.position = "fixed";
    statGrid.addEventListener("mousemove", (ev) => {
      const tile = ev.target.closest(".stat-tile[data-tooltip]");
      if (!tile) {
        statTooltip.classList.add("hidden");
        return;
      }
      statTooltip.textContent = tile.dataset.tooltip;
      statTooltip.style.left = `${ev.clientX + 14}px`;
      statTooltip.style.top = `${ev.clientY + 14}px`;
      statTooltip.classList.remove("hidden");
    });
    statGrid.addEventListener("mouseleave", () => statTooltip.classList.add("hidden"));
  }
}

const BIOME_COLORS = {
  deep_water: "#1c3f6e",
  shallow_water: "#2e6ea6",
  beach: "#d8c58a",
  grassland: "#4c7a3d",
  forest: "#2f5233",
  hills: "#7a6a4f",
  mountain: "#6b6b73",
  snowcap: "#e8ecf2",
  river: "#3a7fbf",
};

const BUILDING_COLORS = {
  hut: "#c98a3c", granary: "#d9a441", workshop: "#8a7fd6", school: "#4fa3c9",
  hospital: "#e0473c", university: "#2f7fc9", factory: "#5c5c66", shrine: "#c9a3e0",
  power_plant: "#e0c93c", market: "#3ccf9e", bridge: "#b08968",
  pasture: "#8fbf5e", hatchery: "#4ab5cf", dock: "#5c9ead", oil_rig: "#3c3c46",
};
const FARM_COLORS = { growing: "#7fae4a", ready: "#e0c34a" };

// Per-event-category presentation: icon, human label prefix, and whether
// it's noisy enough to skip in the log entirely (still stored server-side
// via /events — this is a display-only filter). See docs/DECISIONS.md,
// the "make recent events human-readable" UI pass.
const CATEGORY_META = {
  genesis: { icon: "🌍" },
  founding: { icon: "🗺️" },
  day_end: { skip: true }, // redundant with the header's date/clock — one line per day would drown real events
  week_end: { skip: true }, // same rationale as day_end — 52/year is too frequent for the log
  month_end: { skip: true }, // ~12/year, still redundant with the header's date — season_end/year_end are the notable calendar beats
  season_end: { icon: "🍂" },
  year_end: { icon: "🎆" },
  era_advance: { icon: "🏭" },
  settlement_named: { icon: "🏘️" },
  construction_started: { icon: "🔨" },
  building_completed: { icon: "🏠" },
  building_ruined: { icon: "🏚️" },
  building_reclaimed: { icon: "🌿" },
  farm_planted: { icon: "🌱" },
  birth: { icon: "👶" },
  death: { icon: "💀" },
  dialogue: { skip: true }, // routine background chatter — recorded internally (/events, dev console) but not the main feed; see dialogue_surfaced
  dialogue_surfaced: { icon: "💬" }, // a conversation that actually changed a belief/relationship/rumor — see population.py's apply_dialogue `surfaced` flag
  rumor: { icon: "📣" },
  tradition: { icon: "🎭" },
  invention: { icon: "💡" },
  festival: { icon: "🎉" },
  predator_attack: { icon: "🐺" },
  chronicle: { icon: "📜" },
  documentary: { icon: "🎬" },
  sim_summary: { icon: "🧭" },
  vehicle_started: { icon: "🛠️" },
  vehicle_completed: { icon: "🐎" },
  vehicle_broken: { icon: "⚠️" },
  terrain_thinned: { icon: "🪓" },
  terrain_reclaimed: { icon: "🌲" },
  climate_drift: { icon: "🌡️" },
  wildlife_hunt: { icon: "🐾" },
  wildlife_extinct: { icon: "🦴" },
  wildlife_recolonized: { icon: "🐇" },
  town_brain: { icon: "🧠" },
  intervention: { icon: "✨" },
  belief_formed: { icon: "💭" },
  belief_revised: { icon: "🔄" },
  omen: { icon: "🌫️" },
  disaster_flood: { icon: "🌊" },
  disaster_wildfire: { icon: "🔥" },
  disaster_storm: { icon: "🌩️" },
  disaster_heatwave: { icon: "🌡️" },
  disaster_frost: { icon: "❄️" },
  lake_rose: { icon: "💧" },
  lake_receded: { icon: "🏖️" },
  migrant_arrived: { icon: "🚶" },
  migrant_departed: { icon: "🎒" },
  inheritance: { icon: "🪦" },
  family_formed: { icon: "🏡" },
  council_formed: { icon: "⚖️" },
  council_seat_filled: { icon: "🪑" },
  council_seat_contested: { icon: "👑" },
  guild_formed: { icon: "🔨" },
  guild_joined: { icon: "🔨" },
  faction_formed: { icon: "🚩" },
  illness: { icon: "🤒" },
  recovery: { icon: "💊" },
  caravan: { icon: "🐫" },
  wildlife_migrated: { icon: "🦌" },
  dispute: { icon: "🤝" },
  record_written: { icon: "✍️" },
  place_named: { icon: "🗺️" },
  institution_belief: { icon: "🏛️" },
  ritual_formed: { icon: "🕯️" },
  religion_formed: { icon: "⛩️" },
  narrative_direction: { icon: "📖" },
  consciousness_intervention: { icon: "🌫️" },
  family_feud: { icon: "⚔️" },
  knowledge_lost: { icon: "📉" },
  theft: { icon: "🕵️" },
  law_enacted: { icon: "📜" },
  diplomacy_event: { icon: "🤝" },
  dialect_coined: { icon: "🗣️" },
  letter_delivered: { icon: "✉️" },
  letter_arrived_too_late: { icon: "📭" },
  prophecy_formed: { icon: "🔮" },
  prophecy_confirmed: { icon: "🔮" },
  prophecy_forgotten: { icon: "🔮" },
  chronicler_answer: { icon: "📖" },
  mining_scarred: { icon: "⛏️" },
};

// Event-log filter chips (v0.64.0 UI backlog): coarse groups, display-only —
// everything is still stored and still reaches /events untouched.
const EVENT_GROUP_OF = {
  birth: "people", death: "people", dialogue_surfaced: "people", rumor: "people",
  migrant_arrived: "people", migrant_departed: "people", inheritance: "people", dispute: "people",
  record_written: "people", illness: "people", recovery: "people", predator_attack: "people",
  family_feud: "people", knowledge_lost: "people", theft: "people",
  letter_delivered: "people", letter_arrived_too_late: "people",
  construction_started: "town", building_completed: "town", building_ruined: "town",
  building_reclaimed: "town", farm_planted: "town", vehicle_started: "town",
  vehicle_completed: "town", vehicle_broken: "town", era_advance: "town",
  settlement_named: "town", guild_formed: "town", guild_joined: "town", faction_formed: "town",
  council_formed: "town", council_seat_filled: "town", council_seat_contested: "town", family_formed: "town",
  intervention: "town", town_brain: "town", caravan: "town", founding: "town", genesis: "town",
  law_enacted: "town", diplomacy_event: "town",
  terrain_thinned: "nature", terrain_reclaimed: "nature", climate_drift: "nature",
  wildlife_hunt: "nature", wildlife_extinct: "nature", wildlife_recolonized: "nature",
  wildlife_migrated: "nature", disaster_flood: "nature", disaster_wildfire: "nature",
  disaster_storm: "nature", disaster_heatwave: "nature", disaster_frost: "nature",
  lake_rose: "nature", lake_receded: "nature", season_end: "nature", year_end: "nature",
  place_named: "nature", mining_scarred: "nature",
  chronicle: "mind", documentary: "mind", sim_summary: "mind", tradition: "mind", invention: "mind",
  festival: "mind", belief_formed: "mind", belief_revised: "mind", omen: "mind",
  institution_belief: "mind", ritual_formed: "mind", religion_formed: "mind",
  narrative_direction: "mind", consciousness_intervention: "mind", dialect_coined: "mind",
  prophecy_formed: "mind", prophecy_confirmed: "mind", prophecy_forgotten: "mind", chronicler_answer: "mind",
};
let activeEventGroup = "all";

// Terrain evolves now (deforestation, reclamation, climate drift), so the
// once-per-boot static canvas can go stale — re-fetch /terrain and redraw
// only on ticks that actually reported a terrain-changing life event,
// rather than polling every tick for a change that's rare by design.
const TERRAIN_CHANGING_CATEGORIES = new Set([
  "terrain_thinned", "terrain_reclaimed", "climate_drift",
  "disaster_flood", "disaster_wildfire", "lake_rose", "lake_receded",
  "mining_scarred",
]);
function categoryMeta(category) {
  return CATEGORY_META[category] || (category.endsWith("_migration") ? { icon: "🔧" } : { icon: "•" });
}

let terrain = null;
let latest = null; // last full payload: {summary, life_events, agents, buildings, farms, wildlife, roads, diagnostics}

function pavingUnlockedFlag() {
  return !!(latest && latest.summary && latest.summary.roads && latest.summary.roads.paving_unlocked);
}
let staticCanvas = null; // offscreen: biome grid, drawn once

// --- zoom/pan view state (v0.64.0 UI backlog) -------------------------------
// The whole map layer (terrain + everything drawn per frame) renders through
// one canvas transform; scale 1 shows the full map exactly as before, so the
// feature is invisible until the user scrolls to zoom. The weather overlay
// stays screen-space (ambient rain/darkness doesn't need to zoom).
const VIEW_MIN_SCALE = 1;
const VIEW_MAX_SCALE = 8;
const view = { scale: 1, x: 0, y: 0 };

function clampView() {
  view.scale = Math.max(VIEW_MIN_SCALE, Math.min(VIEW_MAX_SCALE, view.scale));
  const minX = canvas.width * (1 - view.scale);
  const minY = canvas.height * (1 - view.scale);
  view.x = Math.min(0, Math.max(minX, view.x));
  view.y = Math.min(0, Math.max(minY, view.y));
}

function screenToGrid(px, py) {
  return {
    gx: Math.floor((px - view.x) / view.scale / CELL),
    gy: Math.floor((py - view.y) / view.scale / CELL),
  };
}

function centerViewOn(gx, gy) {
  view.x = canvas.width / 2 - (gx * CELL + CELL / 2) * view.scale;
  view.y = canvas.height / 2 - (gy * CELL + CELL / 2) * view.scale;
  clampView();
}

// --- follow-agent camera + movement trail (v0.64.0 UI backlog) --------------
let followAgentId = null;
const TRAIL_MAX_POINTS = 40;
const agentTrails = new Map(); // id -> [[gx, gy], ...] most-recent-last

// --- timeline v2 ghost mode (v0.64.0 UI backlog): render the past map -------
const ghost = { active: false, map: null, canvas: null, tick: null };

const canvas = document.getElementById("map-canvas");
const ctx = canvas.getContext("2d");
const weatherCanvas = document.getElementById("weather-canvas");
const weatherCtx = weatherCanvas.getContext("2d");
const tooltip = document.getElementById("tooltip");
const devConsole = document.getElementById("dev-console");
const devToggle = document.getElementById("dev-toggle");
const devConsoleContent = document.getElementById("dev-console-content");
const devFullReportBtn = document.getElementById("dev-full-report");
const devReportStatus = document.getElementById("dev-report-status");

// Header decluttering (v0.87.24): "explore" and "view" dropdowns each
// collapse a cluster of header buttons behind one trigger. Every button
// inside keeps its original id/listener — this only changes whether it's
// always visible or one click away.
[
  ["explore-menu-trigger", "explore-menu-list"],
  ["view-menu-trigger", "view-menu-list"],
].forEach(([triggerId, listId]) => {
  const trigger = document.getElementById(triggerId);
  const list = document.getElementById(listId);
  if (!trigger || !list) return;
  trigger.addEventListener("click", (ev) => {
    ev.stopPropagation();
    const opening = list.classList.contains("hidden");
    document.querySelectorAll(".header-menu-list").forEach((el) => el.classList.add("hidden"));
    document.querySelectorAll(".header-menu-trigger").forEach((el) => el.classList.remove("active"));
    if (opening) {
      list.classList.remove("hidden");
      trigger.classList.add("active");
    }
  });
  list.addEventListener("click", (ev) => {
    // A button inside the dropdown was clicked — close the menu after
    // its own listener (already wired to the same button id) has run.
    if (ev.target.closest("button")) {
      list.classList.add("hidden");
      trigger.classList.remove("active");
    }
  });
});
document.addEventListener("click", () => {
  document.querySelectorAll(".header-menu-list").forEach((el) => el.classList.add("hidden"));
  document.querySelectorAll(".header-menu-trigger").forEach((el) => el.classList.remove("active"));
});

function legacyCopy(text) {
  // navigator.clipboard requires a secure context (https, or localhost) —
  // accessing the server over plain http on a LAN IP (the common case for
  // this project's target hardware) silently lacks the API entirely, not
  // just permission. document.execCommand is deprecated but still works
  // as a fallback in every browser that lacks the modern API. See
  // docs/DECISIONS.md, dev-console-copy-fallback.
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch (e) {
    ok = false;
  }
  document.body.removeChild(textarea);
  return ok;
}

devFullReportBtn.addEventListener("click", async () => {
  devReportStatus.textContent = "fetching…";
  try {
    const report = await fetchJSON("/diagnostics");
    const text = JSON.stringify(report, null, 2);
    devConsoleContent.textContent = text;
    try {
      await navigator.clipboard.writeText(text);
      devReportStatus.textContent = "copied to clipboard";
    } catch (e) {
      devReportStatus.textContent = legacyCopy(text)
        ? "copied to clipboard (legacy fallback)"
        : "shown below (copy failed — select manually; the page must be served over https or localhost for one-click copy)";
    }
  } catch (e) {
    devReportStatus.textContent = `failed: ${e.message}`;
  }
});

devToggle.addEventListener("click", () => {
  devConsole.classList.toggle("hidden");
  devToggle.classList.toggle("active");
  if (!devConsole.classList.contains("hidden") && latest) renderDevConsole(latest);
});

// LLM training recorder (§8, hearthmind/llm/recorder.py) — OFF by default;
// this panel is the only way to turn it on from the browser. Status reads
// straight off the live broadcast payload's diagnostics.training_recorder
// (see renderDevConsole below), same cadence as every other dev-console field.
const recorderStatusEl = document.getElementById("recorder-status");
const recorderSessionNameInput = document.getElementById("recorder-session-name");
const recorderSessionTagsInput = document.getElementById("recorder-session-tags");
const recorderStartBtn = document.getElementById("recorder-start-btn");
const recorderStopBtn = document.getElementById("recorder-stop-btn");
const recorderExportBtn = document.getElementById("recorder-export-btn");

function renderRecorderStatus(recorder) {
  if (!recorderStatusEl || !recorder) return;
  if (recorder.recording) {
    const tagsSuffix = recorder.session_tags && recorder.session_tags.length
      ? ` [${recorder.session_tags.join(", ")}]` : "";
    recorderStatusEl.textContent =
      `RECORDING — session "${recorder.session_name}"${tagsSuffix} — ${recorder.examples_collected} examples this session ` +
      `(${recorder.total_examples || 0} total) — archive ${(recorder.archive_size_bytes / 1_000_000).toFixed(2)} MB` +
      (recorder.dropped ? ` — ${recorder.dropped} dropped (queue full)` : "");
  } else {
    recorderStatusEl.textContent = "off";
  }
}

recorderStartBtn?.addEventListener("click", async () => {
  const sessionName = recorderSessionNameInput.value.trim() || undefined;
  // Session tags (§8 recorder-enhancement item 5): free-text comma-
  // separated field, edited before recording begins per the spec's
  // own explicit ask — sent as a plain array, empty entries dropped.
  const tags = recorderSessionTagsInput.value.split(",").map((t) => t.trim()).filter(Boolean);
  await fetch("/recorder/start", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_name: sessionName, policy: "all_tasks", tags }),
  });
  recorderStatusEl.textContent = "starting…";
});

recorderStopBtn?.addEventListener("click", async () => {
  await fetch("/recorder/stop", { method: "POST" });
  recorderStatusEl.textContent = "stopping…";
});

recorderExportBtn?.addEventListener("click", async () => {
  recorderStatusEl.textContent = "exporting review pack…";
  try {
    const resp = await fetch("/recorder/export-review-pack", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}),
    });
    const result = await resp.json();
    if (result.error) {
      recorderStatusEl.textContent = `export failed: ${result.error}`;
      return;
    }
    window.location.href = `/recorder/download?path=${encodeURIComponent(result.path)}`;
    recorderStatusEl.textContent = `exported ${result.filename}`;
  } catch (e) {
    recorderStatusEl.textContent = `export failed: ${e.message}`;
  }
});

const historyPanel = document.getElementById("history-panel");
const historyToggle = document.getElementById("history-toggle");
const historyList = document.getElementById("history-list");

async function loadHistory() {
  historyList.innerHTML = "<li>loading…</li>";
  try {
    const rows = await fetchJSON("/history?limit=200");
    historyList.innerHTML = rows.length
      ? rows.map((r) => {
          const meta = categoryMeta(r.category);
          return `<li>${meta.icon || "•"} <span class="muted">tick ${r.tick}</span> ${r.description}</li>`;
        }).join("")
      : "<li>nothing notable yet</li>";
  } catch (e) {
    historyList.innerHTML = `<li>failed to load: ${e.message}</li>`;
  }
}

historyToggle.addEventListener("click", () => {
  historyPanel.classList.toggle("hidden");
  historyToggle.classList.toggle("active");
  if (!historyPanel.classList.contains("hidden")) loadHistory();
});

// --- on-demand LLM simulation summary --------------------------------------

const summaryPanel = document.getElementById("summary-panel");
const summaryToggle = document.getElementById("summary-toggle");
const summaryGenerateBtn = document.getElementById("summary-generate");
const summaryStatus = document.getElementById("summary-status");
const summaryText = document.getElementById("summary-text");
let summaryPollTimer = null;

function renderSummary(data) {
  if (data.pending) {
    summaryStatus.textContent = "generating…";
    summaryGenerateBtn.disabled = true;
  } else {
    summaryStatus.textContent = data.tick >= 0 ? `as of tick ${data.tick}` : "";
    summaryGenerateBtn.disabled = false;
  }
  if (data.text) summaryText.textContent = data.text;
}

async function loadSummary() {
  try {
    renderSummary(await fetchJSON("/summary"));
  } catch (e) {
    summaryStatus.textContent = `failed to load: ${e.message}`;
  }
}

function pollSummaryUntilDone() {
  if (summaryPollTimer) clearInterval(summaryPollTimer);
  summaryPollTimer = setInterval(async () => {
    try {
      const data = await fetchJSON("/summary");
      renderSummary(data);
      if (!data.pending) clearInterval(summaryPollTimer);
    } catch (e) {
      clearInterval(summaryPollTimer);
    }
  }, 2000);
}

summaryToggle.addEventListener("click", () => {
  summaryPanel.classList.toggle("hidden");
  summaryToggle.classList.toggle("active");
  if (!summaryPanel.classList.contains("hidden")) loadSummary();
});

summaryGenerateBtn.addEventListener("click", async () => {
  summaryGenerateBtn.disabled = true;
  summaryStatus.textContent = "generating…";
  try {
    await fetch("/summary/request", { method: "POST" });
    pollSummaryUntilDone();
  } catch (e) {
    summaryStatus.textContent = `failed: ${e.message}`;
    summaryGenerateBtn.disabled = false;
  }
});

// --- Ask the Chronicler (§3, docs/IDEAS-2026-07-EMERGENCE.md) --------------
// Same on-demand request/poll shape as the simulation summary above, but
// the answer is a subjective in-fiction voice, not a stats readout.

const chroniclerPanel = document.getElementById("chronicler-panel");
const chroniclerToggle = document.getElementById("chronicler-toggle");
const chroniclerForm = document.getElementById("chronicler-form");
const chroniclerInput = document.getElementById("chronicler-input");
const chroniclerStatus = document.getElementById("chronicler-status");
const chroniclerQuestionEcho = document.getElementById("chronicler-question-echo");
const chroniclerAnswer = document.getElementById("chronicler-answer");
let chroniclerPollTimer = null;

function renderChronicler(data) {
  if (data.pending) {
    chroniclerStatus.textContent = "the chronicler is thinking…";
  } else {
    chroniclerStatus.textContent = data.tick >= 0 ? `as of tick ${data.tick}` : "";
    chroniclerForm.querySelector("button").disabled = false;
  }
  if (data.question) {
    chroniclerQuestionEcho.textContent = `"${data.question}"`;
    chroniclerQuestionEcho.classList.remove("hidden");
  }
  if (data.answer) chroniclerAnswer.textContent = data.answer;
}

async function loadChronicler() {
  try {
    renderChronicler(await fetchJSON("/chronicler"));
  } catch (e) {
    chroniclerStatus.textContent = `failed to load: ${e.message}`;
  }
}

function pollChroniclerUntilDone() {
  if (chroniclerPollTimer) clearInterval(chroniclerPollTimer);
  chroniclerPollTimer = setInterval(async () => {
    try {
      const data = await fetchJSON("/chronicler");
      renderChronicler(data);
      if (!data.pending) clearInterval(chroniclerPollTimer);
    } catch (e) {
      clearInterval(chroniclerPollTimer);
    }
  }, 2000);
}

chroniclerToggle.addEventListener("click", () => {
  chroniclerPanel.classList.toggle("hidden");
  chroniclerToggle.classList.toggle("active");
  if (!chroniclerPanel.classList.contains("hidden")) loadChronicler();
});

chroniclerForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = chroniclerInput.value.trim();
  if (!question) return;
  chroniclerForm.querySelector("button").disabled = true;
  chroniclerStatus.textContent = "the chronicler is thinking…";
  try {
    const body = { question, settlement_id: activeSettlementId };
    await fetch("/ask-chronicler", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    chroniclerInput.value = "";
    pollChroniclerUntilDone();
  } catch (e2) {
    chroniclerStatus.textContent = `failed: ${e2.message}`;
    chroniclerForm.querySelector("button").disabled = false;
  }
});

// --- §5 "While you were away" digest (docs/IDEAS-2026-07-EMERGENCE.md) -----
// Same on-demand request/poll shape as the simulation summary above.

const digestPanel = document.getElementById("digest-panel");
const digestToggle = document.getElementById("digest-toggle");
const digestGenerateBtn = document.getElementById("digest-generate");
const digestStatus = document.getElementById("digest-status");
const digestText = document.getElementById("digest-text");
let digestPollTimer = null;

function renderDigest(data) {
  if (data.pending) {
    digestStatus.textContent = "catching you up…";
    digestGenerateBtn.disabled = true;
  } else {
    digestStatus.textContent = data.tick >= 0 ? `as of tick ${data.tick}` : "";
    digestGenerateBtn.disabled = false;
  }
  if (data.text) digestText.textContent = data.text;
}

async function loadDigest() {
  try {
    renderDigest(await fetchJSON("/digest"));
  } catch (e) {
    digestStatus.textContent = `failed to load: ${e.message}`;
  }
}

function pollDigestUntilDone() {
  if (digestPollTimer) clearInterval(digestPollTimer);
  digestPollTimer = setInterval(async () => {
    try {
      const data = await fetchJSON("/digest");
      renderDigest(data);
      if (!data.pending) clearInterval(digestPollTimer);
    } catch (e) {
      clearInterval(digestPollTimer);
    }
  }, 2000);
}

digestToggle.addEventListener("click", () => {
  digestPanel.classList.toggle("hidden");
  digestToggle.classList.toggle("active");
  if (!digestPanel.classList.contains("hidden")) loadDigest();
});

digestGenerateBtn.addEventListener("click", async () => {
  digestGenerateBtn.disabled = true;
  digestStatus.textContent = "catching you up…";
  try {
    await fetch("/digest/request", { method: "POST" });
    pollDigestUntilDone();
  } catch (e) {
    digestStatus.textContent = `failed: ${e.message}`;
    digestGenerateBtn.disabled = false;
  }
});

// --- §5 anomaly/highlight log (docs/IDEAS-2026-07-EMERGENCE.md) ------------

const highlightsPanel = document.getElementById("highlights-panel");
const highlightsToggle = document.getElementById("highlights-toggle");
const highlightsList = document.getElementById("highlights-list");

async function loadHighlights() {
  highlightsList.innerHTML = "<li>loading…</li>";
  try {
    const rows = await fetchJSON("/highlights");
    highlightsList.innerHTML = rows.length
      ? rows.map((r) => `<li>✨ <span class="muted">tick ${r.tick}</span> ${r.detail}</li>`).join("")
      : "<li>nothing flagged yet</li>";
  } catch (e) {
    highlightsList.innerHTML = `<li>failed to load: ${e.message}</li>`;
  }
}

highlightsToggle.addEventListener("click", () => {
  highlightsPanel.classList.toggle("hidden");
  highlightsToggle.classList.toggle("active");
  if (!highlightsPanel.classList.contains("hidden")) loadHighlights();
});

// Observatory UI depth pass: a read-only scrub-through-time view over
// whatever snapshot ticks are still on file (see docs/ROADMAP.md's
// flagged "a true scrub-through-time replay view" gap, and
// persistence/snapshot.py's SNAPSHOT_KEEP_RECENT/SNAPSHOT_KEYFRAME_
// INTERVAL_TICKS for why the available ticks are sparse, not every
// tick ever run). Slider index -> tick, not tick -> index directly,
// since available ticks are irregularly spaced.
const timelinePanel = document.getElementById("timeline-panel");
const timelineToggle = document.getElementById("timeline-toggle");
const timelineSlider = document.getElementById("timeline-slider");
const timelineLabel = document.getElementById("timeline-label");
const timelineSummary = document.getElementById("timeline-summary");
let timelineTicks = []; // oldest-first, so the slider reads left (past) to right (recent)

async function loadTimelineIndex() {
  try {
    const rows = await fetchJSON("/snapshots");
    timelineTicks = rows.map((r) => r.tick).reverse();
    if (!timelineTicks.length) {
      timelineLabel.textContent = "no snapshots yet";
      return;
    }
    timelineSlider.max = String(timelineTicks.length - 1);
    timelineSlider.value = String(timelineTicks.length - 1);
    await loadTimelineTick(timelineTicks[timelineTicks.length - 1]);
  } catch (e) {
    timelineLabel.textContent = `failed to load: ${e.message}`;
  }
}

async function loadTimelineTick(tick) {
  timelineLabel.textContent = `tick ${tick} — loading…`;
  try {
    const snap = await fetchJSON(`/snapshots/${tick}`);
    timelineLabel.textContent = `tick ${snap.tick} — ${snap.month} ${snap.day}, year ${snap.year} (${snap.season})`;
    // Timeline v2: don't just describe the past — show it. The main map
    // switches to a rendering of this snapshot until "return to live".
    if (snap.map) enterGhostMode(snap.tick, snap.map);
    const s = snap.settlement, p = snap.population;
    timelineSummary.innerHTML = [
      `<li>${s.name || "(unnamed)"} — era: ${s.era}</li>`,
      `<li>population: ${p.total} (avg hunger ${p.avg_hunger.toFixed(2)})</li>`,
      `<li>buildings: ${s.standing} standing, ${s.under_construction} building, ${s.ruined} ruined</li>`,
      `<li>currency ${s.currency.toFixed(1)}, materials ${s.materials.toFixed(1)}</li>`,
      `<li>priority: ${s.current_priority || "(none yet)"}</li>`,
    ].join("");
  } catch (e) {
    timelineLabel.textContent = `tick ${tick} — failed to load: ${e.message}`;
    timelineSummary.innerHTML = "";
  }
}

timelineSlider.addEventListener("input", () => {
  stopReplay(); // hand-scrubbing takes over from any running replay
  const tick = timelineTicks[Number(timelineSlider.value)];
  if (tick !== undefined) loadTimelineTick(tick);
});

timelineToggle.addEventListener("click", () => {
  timelinePanel.classList.toggle("hidden");
  timelineToggle.classList.toggle("active");
  if (!timelinePanel.classList.contains("hidden")) loadTimelineIndex();
  else {
    stopReplay();
    exitGhostMode(); // closing the timeline always returns the map to live
  }
});

// --- frame-by-frame replay (v0.65.0): play the saved snapshots in order ----
// True replay over timeline v2's real past maps: each stored snapshot
// renders as one frame (ghost mode), advancing at a chosen frames/sec,
// prefetching the next frame while the current one is on screen (the
// server keeps a small cache of built map payloads, so scrubbing back
// over replayed ground is instant). Snapshot pruning means old frames
// are sparser than recent ones — the replay simply plays what history
// was kept, keyframes included.

const timelinePlayBtn = document.getElementById("timeline-play");
const timelineSpeedSel = document.getElementById("timeline-speed");
let replayActive = false;
let replayTimer = null;

function stopReplay() {
  replayActive = false;
  if (replayTimer) { clearTimeout(replayTimer); replayTimer = null; }
  if (timelinePlayBtn) timelinePlayBtn.textContent = "▶ replay";
}

async function replayStep() {
  if (!replayActive) return;
  let idx = Number(timelineSlider.value);
  if (idx >= timelineTicks.length - 1) { stopReplay(); return; }
  idx += 1;
  timelineSlider.value = String(idx);
  await loadTimelineTick(timelineTicks[idx]);
  if (idx + 1 < timelineTicks.length) {
    fetchJSON(`/snapshots/${timelineTicks[idx + 1]}`).catch(() => {}); // prefetch, best-effort
  }
  if (!replayActive) return;
  const fps = Number((timelineSpeedSel && timelineSpeedSel.value) || 2);
  replayTimer = setTimeout(replayStep, Math.max(120, 1000 / fps));
}

if (timelinePlayBtn) {
  timelinePlayBtn.addEventListener("click", () => {
    if (replayActive) { stopReplay(); return; }
    if (!timelineTicks.length) return;
    if (Number(timelineSlider.value) >= timelineTicks.length - 1) {
      timelineSlider.value = "0"; // at the end: replay from the beginning
      loadTimelineTick(timelineTicks[0]);
    }
    replayActive = true;
    timelinePlayBtn.textContent = "⏸ pause";
    const fps = Number((timelineSpeedSel && timelineSpeedSel.value) || 2);
    replayTimer = setTimeout(replayStep, Math.max(120, 1000 / fps));
  });
}

// --- §5 "Year-reel export" (docs/IDEAS-2026-07-EMERGENCE.md) ---------------
// Purely client-side: drives the same replay step loop as the ▶ replay
// button above, but records the map canvas via MediaRecorder/
// captureStream instead of (or alongside) drawing to screen, then
// downloads the result as a .webm — no backend involvement, snapshot
// keyframes + chronicle already exist to stitch into a scrubbed replay.

const timelineExportBtn = document.getElementById("timeline-export");
const timelineExportStatus = document.getElementById("timeline-export-status");
let exportRecorder = null;

async function exportYearReel() {
  if (!timelineTicks.length) return;
  if (typeof MediaRecorder === "undefined" || !canvas.captureStream) {
    timelineExportStatus.textContent = "recording isn't supported in this browser";
    return;
  }
  stopReplay();
  timelineExportBtn.disabled = true;
  const startIdx = Number(timelineSlider.value);
  const chunks = [];
  const stream = canvas.captureStream(0); // manual frame capture below
  const track = stream.getVideoTracks()[0];
  const mimeType = MediaRecorder.isTypeSupported("video/webm;codecs=vp9")
    ? "video/webm;codecs=vp9" : "video/webm";
  exportRecorder = new MediaRecorder(stream, { mimeType });
  exportRecorder.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data); };
  const done = new Promise((resolve) => { exportRecorder.onstop = resolve; });
  exportRecorder.start();

  const fps = Number((timelineSpeedSel && timelineSpeedSel.value) || 2);
  for (let idx = startIdx; idx < timelineTicks.length; idx++) {
    timelineSlider.value = String(idx);
    await loadTimelineTick(timelineTicks[idx]);
    timelineExportStatus.textContent = `recording… frame ${idx - startIdx + 1}/${timelineTicks.length - startIdx}`;
    if (track && track.requestFrame) track.requestFrame();
    await new Promise((r) => setTimeout(r, Math.max(120, 1000 / fps)));
  }
  exportRecorder.stop();
  await done;
  const blob = new Blob(chunks, { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `hearthmind-year-reel-tick${timelineTicks[startIdx]}.webm`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
  timelineExportStatus.textContent = "downloaded.";
  timelineExportBtn.disabled = false;
}

if (timelineExportBtn) {
  timelineExportBtn.addEventListener("click", () => {
    exportYearReel().catch((e) => {
      timelineExportStatus.textContent = `export failed: ${e.message}`;
      timelineExportBtn.disabled = false;
    });
  });
}

// Map-as-primary-interface: raw stats/culture-lists/infrastructure detail
// are reachable but not shown by default — same toggle-panel pattern as
// history/relationships/dev console, not a fourth kind of UI surface.
const detailsPanel = document.getElementById("details-panel");
const detailsToggle = document.getElementById("details-toggle");
detailsToggle.addEventListener("click", () => {
  detailsPanel.classList.toggle("hidden");
  detailsToggle.classList.toggle("active");
});

// --- relationship graph ------------------------------------------------------
// Force-directed layout computed client-side (no backend change needed —
// each agent already carries its own `relationships` map in the per-tick
// payload). Node positions persist in relNodes across frames/ticks so the
// graph settles into a stable layout instead of jittering on every update.

const relationshipPanel = document.getElementById("relationship-panel");
const relationshipToggle = document.getElementById("relationship-toggle");
const relCanvas = document.getElementById("relationship-canvas");
const relTooltip = document.getElementById("relationship-tooltip");
// Below this magnitude a relationship is dropped from the graph entirely
// — every agent pair has *some* affinity by the time they've interacted
// once, and drawing all of them would turn the graph into an unreadable
// mesh; only bonds strong enough to matter are worth a line.
const REL_MIN_AFFINITY = 0.08;
let relVisible = false;
let relAnimHandle = null;
const relNodes = new Map(); // agent id -> {x, y, vx, vy, name}

// Family-tree edges (docs/DECISIONS.md, "continue expanding"): a
// living FAMILY institution's member_agent_ids gives real kinship
// pairs, distinct from the affinity-driven fondness edges above — a
// parent/child pair is family regardless of how they currently feel
// about each other, so these are drawn even below REL_MIN_AFFINITY.
function relFamilyPairs(institutions) {
  const pairs = new Set();
  for (const inst of institutions || []) {
    if (inst.kind !== "family") continue;
    const ids = inst.member_agent_ids || [];
    for (let i = 0; i < ids.length; i++) {
      for (let j = i + 1; j < ids.length; j++) {
        const key = ids[i] < ids[j] ? `${ids[i]}:${ids[j]}` : `${ids[j]}:${ids[i]}`;
        pairs.add(key);
      }
    }
  }
  return pairs;
}

function relBuildEdges(agents, institutions) {
  const byId = new Map(agents.map((a) => [a.id, a]));
  const familyPairs = relFamilyPairs(institutions);
  const seen = new Set();
  const edges = [];
  for (const a of agents) {
    for (const [otherIdStr, affinity] of Object.entries(a.relationships || {})) {
      const otherId = Number(otherIdStr);
      const key = a.id < otherId ? `${a.id}:${otherId}` : `${otherId}:${a.id}`;
      if (!byId.has(otherId) || seen.has(key)) continue;
      const isFamily = familyPairs.has(key);
      if (!isFamily && Math.abs(affinity) < REL_MIN_AFFINITY) continue;
      seen.add(key);
      edges.push({ a: a.id, b: otherId, affinity, family: isFamily });
    }
  }
  // A family pair with no relationships entry at all (e.g. hasn't
  // interacted enough yet to register affinity) still gets a line —
  // kinship doesn't require prior contact the way a fondness bond does.
  for (const key of familyPairs) {
    if (seen.has(key)) continue;
    const [aId, bId] = key.split(":").map(Number);
    if (!byId.has(aId) || !byId.has(bId)) continue;
    seen.add(key);
    edges.push({ a: aId, b: bId, affinity: 0, family: true });
  }
  return edges;
}

function relStep(agents, edges) {
  const w = relCanvas.width, h = relCanvas.height;
  const liveIds = new Set(agents.map((a) => a.id));
  for (const id of Array.from(relNodes.keys())) {
    if (!liveIds.has(id)) relNodes.delete(id);
  }
  for (const a of agents) {
    if (!relNodes.has(a.id)) {
      relNodes.set(a.id, {
        x: w / 2 + (Math.random() - 0.5) * w * 0.7,
        y: h / 2 + (Math.random() - 0.5) * h * 0.7,
        vx: 0, vy: 0,
      });
    }
    relNodes.get(a.id).name = a.name;
  }
  const entries = Array.from(relNodes.values());
  for (let i = 0; i < entries.length; i++) {
    for (let j = i + 1; j < entries.length; j++) {
      const n1 = entries[i], n2 = entries[j];
      const dx = n1.x - n2.x, dy = n1.y - n2.y;
      const dist2 = Math.max(dx * dx + dy * dy, 4);
      const force = 700 / dist2;
      const dist = Math.sqrt(dist2);
      const fx = (dx / dist) * force, fy = (dy / dist) * force;
      n1.vx += fx; n1.vy += fy;
      n2.vx -= fx; n2.vy -= fy;
    }
  }
  for (const e of edges) {
    const n1 = relNodes.get(e.a), n2 = relNodes.get(e.b);
    if (!n1 || !n2) continue;
    const dx = n2.x - n1.x, dy = n2.y - n1.y;
    const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
    const targetDist = e.affinity >= 0 ? 55 : 150; // fond pairs cluster close; sour ones drift apart
    const strength = 0.012 * Math.min(1, Math.abs(e.affinity) * 3);
    const force = (dist - targetDist) * strength;
    const fx = (dx / dist) * force, fy = (dy / dist) * force;
    n1.vx += fx; n1.vy += fy;
    n2.vx -= fx; n2.vy -= fy;
  }
  for (const n of relNodes.values()) {
    n.vx += (w / 2 - n.x) * 0.001;
    n.vy += (h / 2 - n.y) * 0.001;
    n.vx *= 0.82; n.vy *= 0.82;
    n.x = Math.max(8, Math.min(w - 8, n.x + n.vx));
    n.y = Math.max(8, Math.min(h - 8, n.y + n.vy));
  }
}

function relDraw(edges) {
  const ctx = relCanvas.getContext("2d");
  ctx.clearRect(0, 0, relCanvas.width, relCanvas.height);
  for (const e of edges) {
    const n1 = relNodes.get(e.a), n2 = relNodes.get(e.b);
    if (!n1 || !n2) continue;
    ctx.beginPath();
    if (e.family) {
      // Kinship, not current fondness — a distinct warm gold dashed
      // line, drawn independent of affinity color so a family pair
      // who happen to be at odds still visibly reads as family.
      ctx.setLineDash([4, 3]);
      ctx.strokeStyle = "rgba(216, 178, 84, 0.85)";
      ctx.lineWidth = 1.3;
    } else {
      ctx.setLineDash([]);
      const alpha = Math.min(1, Math.abs(e.affinity) * 1.5);
      ctx.strokeStyle = e.affinity >= 0 ? `rgba(127, 174, 74, ${alpha})` : `rgba(224, 71, 60, ${alpha})`;
      ctx.lineWidth = Math.max(0.6, Math.abs(e.affinity) * 3);
    }
    ctx.moveTo(n1.x, n1.y);
    ctx.lineTo(n2.x, n2.y);
    ctx.stroke();
  }
  ctx.setLineDash([]);
  ctx.fillStyle = "#d8c9a3";
  for (const n of relNodes.values()) {
    ctx.beginPath();
    ctx.arc(n.x, n.y, 4, 0, Math.PI * 2);
    ctx.fill();
  }
}

function relFrame() {
  if (!relVisible) return;
  const agents = (latest && latest.agents) || [];
  const institutions = (latest && latest.institutions) || [];
  const edges = relBuildEdges(agents, institutions);
  relStep(agents, edges);
  relDraw(edges);
  relAnimHandle = requestAnimationFrame(relFrame);
}

if (relationshipToggle) {
  relationshipToggle.addEventListener("click", () => {
    relVisible = relationshipPanel.classList.contains("hidden");
    relationshipPanel.classList.toggle("hidden", !relVisible);
    relationshipToggle.classList.toggle("active", relVisible);
    if (relVisible) relFrame();
    else if (relAnimHandle) cancelAnimationFrame(relAnimHandle);
  });
  relCanvas.addEventListener("mousemove", (ev) => {
    const rect = relCanvas.getBoundingClientRect();
    const scale = relCanvas.width / rect.width;
    const mx = (ev.clientX - rect.left) * scale, my = (ev.clientY - rect.top) * scale;
    let hitName = null;
    for (const n of relNodes.values()) {
      if (Math.hypot(n.x - mx, n.y - my) < 8) { hitName = n.name; break; }
    }
    if (hitName) {
      relTooltip.textContent = hitName;
      relTooltip.style.left = `${ev.clientX - rect.left + 10}px`;
      relTooltip.style.top = `${ev.clientY - rect.top + 10}px`;
      relTooltip.classList.remove("hidden");
    } else {
      relTooltip.classList.add("hidden");
    }
  });
  relCanvas.addEventListener("mouseleave", () => relTooltip.classList.add("hidden"));
}

async function fetchJSON(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json();
}

// --- §5 "Era-styled cartography" (docs/IDEAS-2026-07-EMERGENCE.md) ---------
// Pure client polish: the map's rendering style ages with the era system —
// rough hand-drawn early (industrial), surveyed clean lines later (digital).
// Progress felt on the map itself, not just read off a stat tile.

const ERA_TIER = { industrial: 0, electrical: 1, modern: 2, digital: 3 };

function currentEraTier() {
  const settlements = latest && latest.summary && latest.summary.settlements;
  if (!settlements || !settlements.length) return 0;
  let best = 0;
  for (const s of settlements) {
    const tier = ERA_TIER[s.era] || 0;
    if (tier > best) best = tier;
  }
  return best;
}

// Deterministic per-tile pseudo-random (no Math.random — the overlay must
// stay stable across redraws until the next terrain refresh, not flicker).
function tileNoise(x, y) {
  const n = Math.sin(x * 127.1 + y * 311.7) * 43758.5453;
  return n - Math.floor(n);
}

function paintEraOverlay(sctx, tier) {
  if (tier >= ERA_TIER.modern) {
    // Surveyed: a faint clean grid over the whole map — progress read as
    // precision, not decoration.
    sctx.strokeStyle = tier >= ERA_TIER.digital ? "rgba(255,255,255,0.10)" : "rgba(255,255,255,0.05)";
    sctx.lineWidth = 1;
    const step = tier >= ERA_TIER.digital ? CELL * 4 : CELL * 8;
    for (let x = 0; x <= staticCanvas.width; x += step) {
      sctx.beginPath(); sctx.moveTo(x, 0); sctx.lineTo(x, staticCanvas.height); sctx.stroke();
    }
    for (let y = 0; y <= staticCanvas.height; y += step) {
      sctx.beginPath(); sctx.moveTo(0, y); sctx.lineTo(staticCanvas.width, y); sctx.stroke();
    }
    return;
  }
  // Rough hand-drawn: scattered stipple dots over land tiles, density
  // fading as the era advances from industrial to electrical.
  const density = tier === ERA_TIER.industrial ? 0.35 : 0.15;
  sctx.fillStyle = "rgba(0,0,0,0.10)";
  for (let y = 0; y < terrain.height; y++) {
    for (let x = 0; x < terrain.width; x++) {
      const biome = terrain.biomes[y][x];
      if (biome === "ocean" || biome === "river" || biome === "lake") continue;
      if (tileNoise(x, y) >= density) continue;
      const jx = tileNoise(x + 0.37, y) * CELL, jy = tileNoise(x, y + 0.61) * CELL;
      sctx.beginPath();
      sctx.arc(x * CELL + jx, y * CELL + jy, Math.max(1, CELL * 0.06), 0, Math.PI * 2);
      sctx.fill();
    }
  }
}

// §8 "NPC activity reshapes geography" (v0.87.27): a hillside worked by
// sustained mining darkens and pits, intensity-scaled — the visible
// counterpart to the deterministic invisible-until-now ResourceNode
// depletion this idea explicitly asked to make legible on the map.
function paintMiningScars(sctx, scars) {
  if (!scars) return;
  for (const key in scars) {
    const intensity = scars[key];
    if (!(intensity > 0)) continue;
    const [xs, ys] = key.split(":");
    const x = parseInt(xs, 10), y = parseInt(ys, 10);
    sctx.fillStyle = `rgba(40,30,20,${(0.15 + intensity * 0.35).toFixed(3)})`;
    sctx.fillRect(x * CELL, y * CELL, CELL, CELL);
    const pits = Math.max(1, Math.round(intensity * 4));
    sctx.fillStyle = "rgba(0,0,0,0.35)";
    for (let i = 0; i < pits; i++) {
      const jx = tileNoise(x + 0.19 * (i + 1), y) * CELL;
      const jy = tileNoise(x, y + 0.29 * (i + 1)) * CELL;
      sctx.beginPath();
      sctx.arc(x * CELL + jx, y * CELL + jy, Math.max(1, CELL * 0.1), 0, Math.PI * 2);
      sctx.fill();
    }
  }
}

function drawStaticTerrain() {
  staticCanvas = document.createElement("canvas");
  staticCanvas.width = terrain.width * CELL;
  staticCanvas.height = terrain.height * CELL;
  const sctx = staticCanvas.getContext("2d");
  for (let y = 0; y < terrain.height; y++) {
    for (let x = 0; x < terrain.width; x++) {
      sctx.fillStyle = BIOME_COLORS[terrain.biomes[y][x]] || "#000";
      sctx.fillRect(x * CELL, y * CELL, CELL, CELL);
    }
  }
  paintEraOverlay(sctx, currentEraTier());
  paintMiningScars(sctx, terrain.mining_scars);
  canvas.width = staticCanvas.width;
  canvas.height = staticCanvas.height;
  weatherCanvas.width = staticCanvas.width;
  weatherCanvas.height = staticCanvas.height;
}

function drawFrame() {
  if (!staticCanvas) return;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  // Timeline v2 ghost mode: the past map replaces the live layer
  // entirely (it has its own terrain — floods/deforestation as they
  // were), same view transform so zoom/pan works in the past too.
  if (ghost.active && ghost.canvas) {
    ctx.setTransform(view.scale, 0, 0, view.scale, view.x, view.y);
    ctx.drawImage(ghost.canvas, 0, 0);
    drawMinimap();
    return;
  }
  if (!latest) return;

  // Follow-agent camera: keep the followed agent's interpolated
  // position centered every frame (zoom level stays the user's).
  if (followAgentId !== null) {
    const target = (latest.agents || []).find((a) => a.id === followAgentId);
    if (target) {
      const { px, py } = agentRenderPos(target);
      view.x = canvas.width / 2 - px * view.scale;
      view.y = canvas.height / 2 - py * view.scale;
      clampView();
    } else {
      stopFollowing(); // followed agent died/despawned
    }
  }

  ctx.setTransform(view.scale, 0, 0, view.scale, view.x, view.y);
  ctx.drawImage(staticCanvas, 0, 0);

  // Roads: worn tiles get a visible dirt-path tint from the very first
  // bit of wear (a 0.35 floor alpha, not scaled from 0), darkening
  // further as they approach "established" — drawn first so farms/
  // buildings/agents sit on top. The old pure `wear * 0.6` scaling made
  // anything below "established" (wear >= 0.5) nearly invisible
  // (alpha ~0.06 at wear 0.1), which read as "roads aren't showing up."
  // Paved tiles (v0.87.43, era-scaled infrastructure: wear >= 0.85 once
  // any settlement has reached `modern`+, see RoadNetwork.is_paved) get
  // a distinct cool grey instead of the dirt-path amber — a genuinely
  // different surface, not just "more worn."
  const pavingUnlocked = pavingUnlockedFlag();
  for (const [x, y, wear] of latest.roads || []) {
    if (pavingUnlocked && wear >= 0.85) {
      ctx.fillStyle = "rgba(150, 156, 168, 0.85)";
    } else {
      const alpha = wear >= 0.5 ? 0.75 : Math.max(0.35, wear * 1.2);
      ctx.fillStyle = `rgba(196, 148, 58, ${alpha})`;
    }
    ctx.fillRect(x * CELL, y * CELL, CELL, CELL);
  }

  // Grave marks (v0.64.0): a small grey cross where each villager fell —
  // persistent history on the map itself, hover a bare tile to read who.
  for (const m of latest.memorials || []) {
    const cx = m.x * CELL + CELL / 2, cy = m.y * CELL + CELL / 2;
    ctx.strokeStyle = "rgba(170, 170, 180, 0.7)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(cx, cy - 2.5); ctx.lineTo(cx, cy + 2.5);
    ctx.moveTo(cx - 1.8, cy - 0.8); ctx.lineTo(cx + 1.8, cy - 0.8);
    ctx.stroke();
  }

  // Wild resource nodes (bushes/mines): small, unobtrusive markers so
  // the map shows what agents are actually foraging/gathering from, not
  // just an aggregate count in a stat tile. Dimmed toward the terrain
  // color as a node depletes, brightening again as it regrows.
  const RESOURCE_NODE_MAX_AMOUNT = { ore: 2.0, fish: 1.5, food: 1.0 };
  const RESOURCE_NODE_COLOR = { ore: "#9aa0ab", fish: "#4fa8d8", food: "#7fbf5a" };
  for (const n of latest.resources || []) {
    const cx = n.x * CELL + CELL / 2, cy = n.y * CELL + CELL / 2;
    const fullness = Math.max(0.15, n.amount / (RESOURCE_NODE_MAX_AMOUNT[n.kind] || 1.0));
    ctx.globalAlpha = 0.4 + fullness * 0.6;
    ctx.beginPath();
    ctx.fillStyle = RESOURCE_NODE_COLOR[n.kind] || "#7fbf5a";
    ctx.arc(cx, cy, n.kind === "ore" ? 2.2 : 1.6, 0, Math.PI * 2);
    ctx.fill();
    ctx.globalAlpha = 1.0;
  }

  // Mineral veins (v0.87.26, world/minerals.py): distinct from the
  // wild-resource dots above — a small diamond marker (iron/gold have
  // their own colors) so a hills tile holding a real ore deposit reads
  // differently from a plain stone/wood gather node. Dims as the vein
  // depletes, same fullness treatment as wild resources.
  const MINERAL_MAX_AMOUNT = { iron: 1.5, gold: 0.8 };
  const MINERAL_COLOR = { iron: "#c97b4a", gold: "#e8c445" };
  for (const m of latest.minerals || []) {
    const cx = m.x * CELL + CELL / 2, cy = m.y * CELL + CELL / 2;
    const fullness = Math.max(0.2, m.amount / (MINERAL_MAX_AMOUNT[m.kind] || 1.0));
    ctx.globalAlpha = 0.5 + fullness * 0.5;
    ctx.fillStyle = MINERAL_COLOR[m.kind] || "#c9a24a";
    ctx.beginPath();
    ctx.moveTo(cx, cy - 2.6);
    ctx.lineTo(cx + 2.2, cy);
    ctx.lineTo(cx, cy + 2.6);
    ctx.lineTo(cx - 2.2, cy);
    ctx.closePath();
    ctx.fill();
    ctx.strokeStyle = "rgba(0,0,0,0.35)";
    ctx.lineWidth = 0.5;
    ctx.stroke();
    ctx.globalAlpha = 1.0;
  }

  for (const farm of latest.farms) {
    ctx.fillStyle = FARM_COLORS[farm.stage] || "#888";
    ctx.fillRect(farm.x * CELL + 2, farm.y * CELL + 2, CELL - 4, CELL - 4);
  }

  for (const b of latest.buildings) {
    ctx.fillStyle = BUILDING_COLORS[b.kind] || "#aaa";
    ctx.globalAlpha = b.stage === "under_construction" ? 0.45 : b.stage === "ruined" ? 0.35 : 1.0;
    ctx.fillRect(b.x * CELL - 1, b.y * CELL - 1, CELL + 2, CELL + 2);
    ctx.globalAlpha = 1.0;
    ctx.strokeStyle = "#f5f5f5";
    ctx.lineWidth = 1;
    ctx.strokeRect(b.x * CELL - 0.5, b.y * CELL - 0.5, CELL + 1, CELL + 1);
    // A bridge's own tile is just its land anchor (see BuildingKind.
    // BRIDGE) — the actual water crossing is bridge_span, drawn as a
    // thin deck across the water tiles it covers so the crossing
    // itself is visible, not just a marker on one shore.
    if (b.kind === "bridge" && b.bridge_span && b.bridge_span.length) {
      ctx.globalAlpha = b.stage === "under_construction" ? 0.4 : b.stage === "ruined" ? 0.3 : 0.85;
      ctx.fillStyle = BUILDING_COLORS.bridge;
      for (const [sx, sy] of b.bridge_span) {
        ctx.fillRect(sx * CELL + 1, sy * CELL + CELL / 2 - 1.5, CELL - 2, 3);
      }
      ctx.globalAlpha = 1.0;
    }
  }

  // Vehicles: a small icon-like mark at their build/home tile — carts as
  // an amber square and rafts as a teal square (both settlement-wide
  // passive bonuses, not personally claimed, so neither uses the
  // claimed/unclaimed diamond below), mounts/automobiles/boats as a
  // diamond (personal, claimed/unclaimed shown via color; automobile
  // gets a distinct steel-blue hue and boat a distinct aqua hue from
  // mount's violet, so era-driven/water transport progress is visible
  // on the map, not just in stat tiles).
  for (const v of latest.vehicles || []) {
    const cx = v.x * CELL + CELL / 2, cy = v.y * CELL + CELL / 2;
    ctx.globalAlpha = v.stage === "building" ? 0.4 : v.stage === "broken" ? 0.3 : 1.0;
    if (v.kind === "cart") {
      ctx.fillStyle = "#c9863c";
      ctx.fillRect(cx - CELL / 4, cy - CELL / 4, CELL / 2, CELL / 2);
    } else if (v.kind === "raft") {
      ctx.fillStyle = "#3ba8a0";
      ctx.fillRect(cx - CELL / 4, cy - CELL / 4, CELL / 2, CELL / 2);
    } else {
      const isAutomobile = v.kind === "automobile";
      const isBoat = v.kind === "boat";
      const claimedColor = isAutomobile ? "#5b9bd6" : isBoat ? "#3cc9d6" : "#a679d6";
      const unclaimedColor = isAutomobile ? "#33546e" : isBoat ? "#1f6d75" : "#6b5580";
      ctx.beginPath();
      ctx.fillStyle = v.assigned_agent_id != null ? claimedColor : unclaimedColor;
      ctx.moveTo(cx, cy - CELL / 2.2);
      ctx.lineTo(cx + CELL / 2.2, cy);
      ctx.lineTo(cx, cy + CELL / 2.2);
      ctx.lineTo(cx - CELL / 2.2, cy);
      ctx.closePath();
      ctx.fill();
    }
    ctx.globalAlpha = 1.0;
  }

  // Wildlife: grazer herds as green dots (radius scales with herd size),
  // predator packs as red triangles — a visible second trophic layer.
  for (const h of latest.wildlife || []) {
    const cx = h.x * CELL + CELL / 2, cy = h.y * CELL + CELL / 2;
    if (h.species === "grazer") {
      ctx.beginPath();
      ctx.fillStyle = "#9fd66b";
      ctx.arc(cx, cy, Math.min(CELL / 2, 1.5 + h.count * 0.25), 0, Math.PI * 2);
      ctx.fill();
    } else {
      ctx.fillStyle = "#c94c4c";
      drawAgentTriangle(ctx, cx, cy, CELL / 2.4);
      ctx.fill();
    }
  }

  for (const a of latest.agents) {
    const { px, py } = agentRenderPos(a);
    ctx.beginPath();
    if (a.is_core) {
      // LLM core cast (v0.72.0): the persistent, model-authored
      // protagonists (Config.llm_core_cast_size) get a distinct blue
      // triangle instead of the plain dot everyone else renders as —
      // Observatory UI direction: this should be readable at a glance
      // on the map itself, not only in the inspector. Resting still
      // dims it the same way a resting dot dims, so state stays legible.
      ctx.fillStyle = a.state === "resting" ? "#5c7fc9" : "#4d8dff";
      drawAgentTriangle(ctx, px, py, CELL / 2.6);
    } else {
      ctx.fillStyle = a.state === "resting" ? "#8894c9" : "#f2f2f2";
      ctx.arc(px, py, CELL / 3, 0, Math.PI * 2);
    }
    ctx.fill();
    if (a.starving_ticks > 0) {
      ctx.strokeStyle = "#e0473c";
      ctx.lineWidth = 1;
      ctx.stroke();
    }
    // "Continue expanding, round three": sick_ticks/immune_ticks were
    // already broadcast per-agent (disease v2, v0.59.0) but never
    // rendered anywhere — a distinct outer ring (magenta while sick,
    // faint green while recently immune) closes that gap the same way
    // starving_ticks' own ring already does, without colliding with it.
    if (a.sick_ticks > 0) {
      ctx.beginPath();
      ctx.strokeStyle = "#c94cef";
      ctx.lineWidth = 1;
      ctx.arc(px, py, CELL / 3 + 2, 0, Math.PI * 2);
      ctx.stroke();
    } else if (a.immune_ticks > 0) {
      ctx.beginPath();
      ctx.strokeStyle = "rgba(120, 220, 150, 0.65)";
      ctx.lineWidth = 1;
      ctx.arc(px, py, CELL / 3 + 2, 0, Math.PI * 2);
      ctx.stroke();
    }
  }

  // Movement trail for the followed agent: a fading line through their
  // recent tiles (see agentTrails, updated per payload).
  if (followAgentId !== null) {
    const trail = agentTrails.get(followAgentId);
    if (trail && trail.length > 1) {
      for (let i = 1; i < trail.length; i++) {
        ctx.beginPath();
        ctx.strokeStyle = `rgba(217, 164, 65, ${0.12 + (i / trail.length) * 0.55})`;
        ctx.lineWidth = 1.4;
        ctx.moveTo(trail[i - 1][0] * CELL + CELL / 2, trail[i - 1][1] * CELL + CELL / 2);
        ctx.lineTo(trail[i][0] * CELL + CELL / 2, trail[i][1] * CELL + CELL / 2);
        ctx.stroke();
      }
    }
  }

  // Settlement name labels (multiple named settlements, v0.65.0):
  // small floating nameplates at each named settlement's center — the
  // one always-on hint that there is more than one community out
  // there, readable at a glance like everything else on the map.
  const settlementList = (latest && latest.summary && latest.summary.settlements) || [];
  if (settlementList.length) {
    ctx.font = "9px system-ui, sans-serif";
    ctx.textAlign = "center";
    for (const s of settlementList) {
      if (!s.name || !s.center) continue;
      const lx = s.center[0] * CELL + CELL / 2;
      const ly = s.center[1] * CELL - 6;
      const w = ctx.measureText(s.name).width + 8;
      ctx.fillStyle = "rgba(8, 10, 14, 0.55)";
      ctx.fillRect(lx - w / 2, ly - 9, w, 12);
      ctx.fillStyle = "rgba(236, 231, 218, 0.92)";
      ctx.fillText(s.name, lx, ly);
    }
    ctx.textAlign = "left";
  }

  ctx.setTransform(1, 0, 0, 1, 0, 0);
  drawMinimap();
}

// --- minimap (v0.64.0 UI backlog) -------------------------------------------

const minimapEl = document.getElementById("minimap");

function drawMinimap() {
  if (!minimapEl || !staticCanvas) return;
  // Only worth screen space once the user has actually zoomed in (at
  // scale 1 the map is already fully visible).
  const zoomed = view.scale > 1.01;
  minimapEl.classList.toggle("hidden", !zoomed && !ghost.active);
  if (!zoomed && !ghost.active) return;
  const mctx = minimapEl.getContext("2d");
  const source = ghost.active && ghost.canvas ? ghost.canvas : staticCanvas;
  mctx.clearRect(0, 0, minimapEl.width, minimapEl.height);
  mctx.drawImage(source, 0, 0, minimapEl.width, minimapEl.height);
  // Viewport rectangle: which slice of the map the main canvas shows.
  const sx = (-view.x / view.scale) / canvas.width * minimapEl.width;
  const sy = (-view.y / view.scale) / canvas.height * minimapEl.height;
  const sw = minimapEl.width / view.scale;
  const sh = minimapEl.height / view.scale;
  mctx.strokeStyle = "#d9a441";
  mctx.lineWidth = 1;
  mctx.strokeRect(sx, sy, sw, sh);
}

if (minimapEl) {
  minimapEl.addEventListener("click", (ev) => {
    const rect = minimapEl.getBoundingClientRect();
    const fx = (ev.clientX - rect.left) / rect.width;
    const fy = (ev.clientY - rect.top) / rect.height;
    stopFollowing();
    centerViewOn(fx * (terrain ? terrain.width : 0), fy * (terrain ? terrain.height : 0));
  });
}

// --- follow controls ----------------------------------------------------------

const followBanner = document.getElementById("follow-banner");
const followBannerLabel = document.getElementById("follow-banner-label");
const followStopBtn = document.getElementById("follow-stop");

function startFollowing(agentId, name) {
  followAgentId = agentId;
  if (view.scale <= 1.01) {
    view.scale = 3; // following at full-map zoom would be a no-op — zoom in to make it read
  }
  clampView();
  if (followBanner) {
    followBannerLabel.textContent = `following ${name}`;
    followBanner.classList.remove("hidden");
  }
  closeNpcInspector();
}

function stopFollowing() {
  followAgentId = null;
  if (followBanner) followBanner.classList.add("hidden");
}

if (followStopBtn) followStopBtn.addEventListener("click", stopFollowing);
window.hmFollowAgent = startFollowing; // reachable from inspector-rendered HTML

// --- timeline v2 ghost mode ---------------------------------------------------

const ghostBanner = document.getElementById("ghost-banner");
const ghostBannerLabel = document.getElementById("ghost-banner-label");
const ghostReturnBtn = document.getElementById("ghost-return");

function enterGhostMode(tick, map) {
  ghost.active = true;
  ghost.tick = tick;
  ghost.map = map;
  const g = document.createElement("canvas");
  g.width = map.width * CELL;
  g.height = map.height * CELL;
  const gctx = g.getContext("2d");
  for (let y = 0; y < map.height; y++) {
    for (let x = 0; x < map.width; x++) {
      gctx.fillStyle = BIOME_COLORS[map.biomes[y][x]] || "#000";
      gctx.fillRect(x * CELL, y * CELL, CELL, CELL);
    }
  }
  for (const m of map.memorials || []) {
    const cx = m.x * CELL + CELL / 2, cy = m.y * CELL + CELL / 2;
    gctx.strokeStyle = "rgba(170, 170, 180, 0.7)";
    gctx.beginPath();
    gctx.moveTo(cx, cy - 2.5); gctx.lineTo(cx, cy + 2.5);
    gctx.moveTo(cx - 1.8, cy - 0.8); gctx.lineTo(cx + 1.8, cy - 0.8);
    gctx.stroke();
  }
  for (const f of map.farms || []) {
    gctx.fillStyle = FARM_COLORS[f.stage] || "#888";
    gctx.fillRect(f.x * CELL + 2, f.y * CELL + 2, CELL - 4, CELL - 4);
  }
  for (const b of map.buildings || []) {
    gctx.fillStyle = BUILDING_COLORS[b.kind] || "#aaa";
    gctx.globalAlpha = b.stage === "under_construction" ? 0.45 : b.stage === "ruined" ? 0.35 : 1.0;
    gctx.fillRect(b.x * CELL - 1, b.y * CELL - 1, CELL + 2, CELL + 2);
    gctx.globalAlpha = 1.0;
  }
  gctx.fillStyle = "#f2f2f2";
  for (const [ax, ay] of map.agents || []) {
    gctx.beginPath();
    gctx.arc(ax * CELL + CELL / 2, ay * CELL + CELL / 2, CELL / 3, 0, Math.PI * 2);
    gctx.fill();
  }
  if (map.labels && map.labels.length) {
    gctx.font = "9px system-ui, sans-serif";
    gctx.textAlign = "center";
    for (const l of map.labels) {
      if (!l.name || !l.center) continue;
      gctx.fillStyle = "rgba(236, 231, 218, 0.92)";
      gctx.fillText(l.name, l.center[0] * CELL + CELL / 2, l.center[1] * CELL - 5);
    }
    gctx.textAlign = "left";
  }
  ghost.canvas = g;
  if (ghostBanner) {
    ghostBannerLabel.textContent = `viewing tick ${tick} — the world as it was`;
    ghostBanner.classList.remove("hidden");
  }
}

function exitGhostMode() {
  ghost.active = false;
  ghost.canvas = null;
  ghost.map = null;
  if (ghostBanner) ghostBanner.classList.add("hidden");
}

if (ghostReturnBtn) ghostReturnBtn.addEventListener("click", exitGhostMode);

// --- smooth inter-tick agent movement --------------------------------------
// Server ticks (and thus new agent positions) arrive at most a few times a
// second; snapping each dot straight to its new tile on every tick reads as
// jittery teleportation. Instead each agent's last-known and newest grid
// positions are tracked here and linearly interpolated over
// AGENT_ANIM_DURATION_MS, driven by `renderLoop`'s own requestAnimationFrame
// loop (independent of tick cadence, same pattern as the weather overlay).

const AGENT_ANIM_DURATION_MS = 350;
const agentAnim = new Map(); // id -> {fx, fy, tx, ty, t0, dur} (grid coords)

function updateAgentAnimTargets(agents) {
  const now = performance.now();
  const seen = new Set();
  for (const a of agents) {
    seen.add(a.id);
    // Movement trail bookkeeping (v0.64.0): only meaningful while
    // followed, but cheap enough to track for everyone (bounded at
    // TRAIL_MAX_POINTS per living agent, deleted on death below).
    const trail = agentTrails.get(a.id) || [];
    const last = trail[trail.length - 1];
    if (!last || last[0] !== a.x || last[1] !== a.y) {
      trail.push([a.x, a.y]);
      if (trail.length > TRAIL_MAX_POINTS) trail.shift();
      agentTrails.set(a.id, trail);
    }
    const prev = agentAnim.get(a.id);
    if (!prev) {
      agentAnim.set(a.id, { fx: a.x, fy: a.y, tx: a.x, ty: a.y, t0: now, dur: 1 });
      continue;
    }
    const t = Math.min(1, (now - prev.t0) / prev.dur);
    const curX = prev.fx + (prev.tx - prev.fx) * t;
    const curY = prev.fy + (prev.ty - prev.fy) * t;
    agentAnim.set(a.id, { fx: curX, fy: curY, tx: a.x, ty: a.y, t0: now, dur: AGENT_ANIM_DURATION_MS });
  }
  for (const id of agentAnim.keys()) {
    if (!seen.has(id)) agentAnim.delete(id); // agent died/despawned
  }
  for (const id of agentTrails.keys()) {
    if (!seen.has(id)) agentTrails.delete(id);
  }
}

function agentRenderPos(a) {
  const anim = agentAnim.get(a.id);
  if (!anim) return { px: a.x * CELL + CELL / 2, py: a.y * CELL + CELL / 2 };
  const t = Math.min(1, (performance.now() - anim.t0) / anim.dur);
  const gx = anim.fx + (anim.tx - anim.fx) * t;
  const gy = anim.fy + (anim.ty - anim.fy) * t;
  return { px: gx * CELL + CELL / 2, py: gy * CELL + CELL / 2 };
}

// --- LLM "thought" flashes ---------------------------------------------
// A brief marker over a core-cast agent the instant a genuine LLM-authored
// exchange involving them lands — the concrete, moment-to-moment "this
// mind just reasoned about something" cue the map otherwise never gives
// you (dialogue only ever showed up as sidebar text, disconnected from
// WHERE it happened). Only fires for `dialogue`/`dialogue_surfaced`
// events, which are logged only for genuine LLM-authored core-cast
// exchanges (never the deterministic crowd fallback) — see engine.py's
// `is_llm` gating — so this reads as "the model just thought," not noise.
const THOUGHT_FLASH_DURATION_MS = 2600;
const thoughtFlashes = new Map(); // agentId -> startTime (performance.now())

// Dialogue events are logged as `Name: "line" — Name: "line"` (engine.py's
// _maybe_schedule_dialogue) — parsed back into names here rather than
// widening the event schema just for this cosmetic effect. Best-effort:
// a name collision or malformed line just skips the flash, never breaks
// anything else.
const DIALOGUE_EVENT_RE = /^(.+?): "[\s\S]*" — (.+?): "/;

function registerThoughtFlashes(events, agents) {
  if (!events || !events.length || !agents || !agents.length) return;
  const now = performance.now();
  const byName = new Map(agents.map((a) => [a.name, a.id]));
  for (const e of events) {
    if (e.category !== "dialogue" && e.category !== "dialogue_surfaced") continue;
    const m = DIALOGUE_EVENT_RE.exec(e.description || "");
    if (!m) continue;
    for (const name of [m[1], m[2]]) {
      const id = byName.get(name);
      if (id !== undefined) thoughtFlashes.set(id, now);
    }
  }
}

function drawThoughtFlashes(ctx) {
  if (!thoughtFlashes.size) return;
  const now = performance.now();
  for (const [id, start] of thoughtFlashes) {
    const t = (now - start) / THOUGHT_FLASH_DURATION_MS;
    if (t >= 1) { thoughtFlashes.delete(id); continue; }
    const agent = latest.agents.find((a) => a.id === id);
    if (!agent) { thoughtFlashes.delete(id); continue; }
    const { px, py } = agentRenderPos(agent);
    // An expanding, fading ring — a vector shape rather than an emoji
    // glyph so it renders identically regardless of the browser/OS's
    // emoji font coverage. Two rings a beat apart read as a pulse
    // rather than a single static ripple.
    ctx.save();
    ctx.strokeStyle = "#8fd6ff";
    ctx.lineWidth = 1.2;
    for (const offset of [0, 0.35]) {
      const rt = Math.min(1, Math.max(0, t - offset) / (1 - offset));
      if (rt <= 0 || rt >= 1) continue;
      ctx.globalAlpha = (1 - rt) * 0.8;
      ctx.beginPath();
      ctx.arc(px, py, CELL * 0.6 + rt * CELL * 1.8, 0, Math.PI * 2);
      ctx.stroke();
    }
    ctx.restore();
  }
}

function renderLoop() {
  drawFrame();
  drawThoughtFlashes(ctx);
  requestAnimationFrame(renderLoop);
}
requestAnimationFrame(renderLoop);

// --- weather particle overlay --------------------------------------------
// Runs its own requestAnimationFrame loop, independent of tick cadence, so
// rain/snow reads as continuous motion rather than snapping once/tick. Reads
// current conditions from `latest.summary.weather_detail` (precipitation
// 0..1, wind 0..1, is_snowing) each frame; a separate canvas layered over
// the map so this never has to redraw terrain/agents/buildings.

let weatherParticles = [];

// Precipitation is an EMA-smoothed value that (per hearthmind/world/
// weather.py's CLEAR_PRECIPITATION_THRESHOLD docstring) realistically
// never drops much below ~0.10 or climbs much past ~0.67. RAIN_FLOOR is
// the precipitation at/below which NO rain particles are drawn — it must
// match the backend's "it is actually raining" onset. v0.87.12 retune
// (live report: "reduce the amount of rain, there is no variety"):
// weather.py split its old four sky bands into six (clear/partly_cloudy/
// overcast/drizzle/light_rain/heavy_rain) and rebalanced them so real
// rain (drizzle+light+heavy) is ~22% of ticks, down from ~47%. RAIN_
// FLOOR now matches OVERCAST_PRECIPITATION_THRESHOLD (0.45, the drizzle
// onset) rather than the old light-rain cutoff — the map shows (light)
// particles starting exactly when the sky label first mentions any
// precipitation ("drizzling"), scaling up through "light rain" to
// "heavy rain"; "clear", "partly cloudy", and "overcast" ticks stay dry,
// overcast still just reading darker via the WEATHER_DARKEN tint below.
const RAIN_FLOOR = 0.45;
const RAIN_CEILING = 0.65;

function currentWeatherDetail() {
  return (latest && latest.summary && latest.summary.weather_detail) || null;
}

function spawnWeatherParticles(w) {
  if (!w || weatherCanvas.width === 0) return;
  const intensity = w.is_snowing
    ? w.precipitation
    : Math.max(0, (w.precipitation - RAIN_FLOOR) / (RAIN_CEILING - RAIN_FLOOR));
  const target = w.is_snowing
    ? Math.round(intensity * 120)
    : Math.round(intensity * 90);
  // Keep every EXISTING particle's type in sync with the current weather,
  // not just newly-spawned ones — the loop below only ever appends once
  // the array is below target, so a particle left over from a moment ago
  // (e.g. rain) never got its `snow`/`speed`/`drift`/`size` refreshed on
  // a rain -> snow transition, and just kept behaving as rain forever.
  // Root cause of the live "it's snowing but I don't see snow" report:
  // snow directly following rain (a common transition, both requiring
  // precipitation) inherited a canvas full of stale rain-streak particles
  // instead of snowflakes. A transition from clear sky (0 particles) was
  // unaffected, which is why this was easy to miss in a quick check.
  for (const p of weatherParticles) {
    if (p.snow !== w.is_snowing) {
      p.snow = w.is_snowing;
      p.speed = w.is_snowing ? 0.4 + Math.random() * 0.6 : 4 + Math.random() * 4;
      p.drift = (w.wind - 0.5) * (w.is_snowing ? 1.2 : 2.5);
      p.size = w.is_snowing ? 1 + Math.random() * 1.5 : 1;
    }
  }
  while (weatherParticles.length < target) {
    weatherParticles.push({
      x: Math.random() * weatherCanvas.width,
      y: Math.random() * weatherCanvas.height,
      snow: w.is_snowing,
      speed: w.is_snowing ? 0.4 + Math.random() * 0.6 : 4 + Math.random() * 4,
      drift: (w.wind - 0.5) * (w.is_snowing ? 1.2 : 2.5),
      size: w.is_snowing ? 1 + Math.random() * 1.5 : 1,
    });
  }
  if (weatherParticles.length > target) weatherParticles.length = target;
}

// --- day/night + weather lighting -------------------------------------
// A flat dark tint over the map whose strength depends on time of day
// (darkest around midnight, none at noon) plus a smaller bump for heavy
// precipitation/snow (overcast reads darker than clear skies) — drawn
// into the same weather canvas, underneath the rain/snow particles, so
// this needs no extra layer. See docs/DECISIONS.md, visual-richness pass.

const NIGHT_MAX_ALPHA = 0.55;
const WEATHER_DARKEN_MAX_ALPHA = 0.15;

// Approximate real UK (London-latitude) sunrise/sunset local clock
// times by month, decimal hours, including the seasonal daylight-hours
// swing (~8h in December vs ~16.5h in June) — replaces the old fixed
// "always 6am-6pm" day/night ramp, which never varied by season despite
// the sim having a real UK-climate calendar. See docs/DECISIONS.md,
// "map/UI/ecology follow-up."
const UK_DAYLIGHT_HOURS = {
  January: [8.08, 16.00], February: [7.67, 17.00], March: [6.50, 18.17],
  April: [6.50, 20.00], May: [5.33, 20.83], June: [4.75, 21.33],
  July: [5.00, 21.25], August: [5.75, 20.50], September: [6.58, 19.33],
  October: [7.42, 18.17], November: [7.25, 16.25], December: [8.00, 15.92],
};
const DAWN_DUSK_TRANSITION_HOURS = 1.0;

function currentSunTimes() {
  const month = latest && latest.summary && latest.summary.month;
  return UK_DAYLIGHT_HOURS[month] || [6, 18];
}

function nightFactor(clockStr, monthName) {
  if (!clockStr) return 0;
  const parts = clockStr.split(":");
  const hour = Number(parts[0]) + Number(parts[1] || 0) / 60;
  if (Number.isNaN(hour)) return 0;
  const [sunrise, sunset] = UK_DAYLIGHT_HOURS[monthName] || [6, 18];
  if (hour <= sunrise - DAWN_DUSK_TRANSITION_HOURS || hour >= sunset + DAWN_DUSK_TRANSITION_HOURS) return 1;
  if (hour >= sunrise && hour <= sunset) return 0;
  if (hour < sunrise) return (sunrise - hour) / DAWN_DUSK_TRANSITION_HOURS;
  return (hour - sunset) / DAWN_DUSK_TRANSITION_HOURS;
}

const SNOW_TINT_MAX_ALPHA = 0.22;

function drawLighting(w) {
  const night = nightFactor(
    latest && latest.summary && latest.summary.clock,
    latest && latest.summary && latest.summary.month,
  );
  // Snow reads as a pale, overcast-white ground tint — real snowy days
  // are bright, not gloomy — distinct from (and drawn instead of) rain's
  // darkening tint below. This is the map-level "it's snowing" cue the
  // falling particles alone don't give you at a glance when the map is
  // zoomed out or the particles are sparse (light snow). Layered UNDER
  // the night darkening so a snowy night still reads as night.
  if (w && w.is_snowing) {
    const snowAlpha = Math.min(SNOW_TINT_MAX_ALPHA, 0.08 + w.precipitation * 0.22);
    weatherCtx.fillStyle = `rgba(232, 238, 250, ${snowAlpha})`;
    weatherCtx.fillRect(0, 0, weatherCanvas.width, weatherCanvas.height);
  }
  const weatherDark = w && !w.is_snowing ? Math.min(1, w.precipitation) * WEATHER_DARKEN_MAX_ALPHA : 0;
  const alpha = Math.min(0.75, night * NIGHT_MAX_ALPHA + weatherDark);
  if (alpha <= 0.01) return;
  weatherCtx.fillStyle = `rgba(4, 6, 16, ${alpha})`;
  weatherCtx.fillRect(0, 0, weatherCanvas.width, weatherCanvas.height);
}

function stepWeatherParticles() {
  const w = currentWeatherDetail();
  weatherCtx.clearRect(0, 0, weatherCanvas.width, weatherCanvas.height);
  drawLighting(w);
  if (!w || (w.precipitation <= RAIN_FLOOR && !w.is_snowing)) {
    weatherParticles.length = 0;
    requestAnimationFrame(stepWeatherParticles);
    return;
  }
  spawnWeatherParticles(w);
  weatherCtx.strokeStyle = "rgba(190, 210, 235, 0.55)";
  weatherCtx.fillStyle = "rgba(255, 255, 255, 0.85)";
  for (const p of weatherParticles) {
    p.x += p.drift;
    p.y += p.speed;
    if (p.y > weatherCanvas.height) { p.y = -4; p.x = Math.random() * weatherCanvas.width; }
    if (p.x < 0) p.x = weatherCanvas.width;
    if (p.x > weatherCanvas.width) p.x = 0;
    if (p.snow) {
      weatherCtx.beginPath();
      weatherCtx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
      weatherCtx.fill();
    } else {
      weatherCtx.beginPath();
      weatherCtx.moveTo(p.x, p.y);
      weatherCtx.lineTo(p.x - p.drift * 0.6, p.y - p.speed * 1.8);
      weatherCtx.stroke();
    }
  }
  requestAnimationFrame(stepWeatherParticles);
}

requestAnimationFrame(stepWeatherParticles);

function findAgentAt(gx, gy) {
  if (!latest) return null;
  for (const a of latest.agents) {
    if (a.x === gx && a.y === gy) return a;
  }
  return null;
}

function findBuildingAt(gx, gy) {
  if (!latest) return null;
  for (const b of latest.buildings || []) {
    if (b.x === gx && b.y === gy) return b;
  }
  return null;
}

// --- zoom (wheel) + pan (drag) on the map canvas (v0.64.0 UI backlog) --------

let panState = null; // {startX, startY, viewX, viewY, moved}

canvas.addEventListener("wheel", (ev) => {
  ev.preventDefault();
  const rect = canvas.getBoundingClientRect();
  const px = ev.clientX - rect.left, py = ev.clientY - rect.top;
  const factor = ev.deltaY < 0 ? 1.2 : 1 / 1.2;
  const before = view.scale;
  view.scale = Math.max(VIEW_MIN_SCALE, Math.min(VIEW_MAX_SCALE, view.scale * factor));
  // Zoom around the cursor: the world point under it stays put.
  view.x = px - (px - view.x) * (view.scale / before);
  view.y = py - (py - view.y) * (view.scale / before);
  clampView();
}, { passive: false });

canvas.addEventListener("mousedown", (ev) => {
  panState = { startX: ev.clientX, startY: ev.clientY, viewX: view.x, viewY: view.y, moved: false };
});
window.addEventListener("mouseup", () => {
  if (panState && panState.moved) {
    // Swallow the click that ends a drag (see the click handler).
    setTimeout(() => { panState = null; }, 0);
  } else {
    panState = null;
  }
});

// Hover inspection covers everything on the map, not just agents (Observatory
// UI direction, CLAUDE.md): agent, then building, then bare terrain — each
// with its own tooltip content, cheapest/most-specific check first.
canvas.addEventListener("mousemove", (ev) => {
  const rect = canvas.getBoundingClientRect();
  const px = ev.clientX - rect.left, py = ev.clientY - rect.top;
  if (panState) {
    const dx = ev.clientX - panState.startX, dy = ev.clientY - panState.startY;
    if (panState.moved || Math.hypot(dx, dy) > 4) {
      panState.moved = true;
      stopFollowing(); // a manual pan takes the camera back
      view.x = panState.viewX + dx;
      view.y = panState.viewY + dy;
      clampView();
      tooltip.classList.add("hidden");
      return;
    }
  }
  const { gx, gy } = screenToGrid(px, py);
  tooltip.style.left = `${px + 12}px`;
  tooltip.style.top = `${py + 12}px`;
  if (ghost.active) {
    tooltip.classList.add("hidden");
    return; // the past is a picture — hover/click inspection is live-only
  }

  const a = findAgentAt(gx, gy);
  if (a) {
    tooltip.classList.remove("hidden");
    const lastMemory = a.memories && a.memories.length ? a.memories[a.memories.length - 1] : null;
    tooltip.innerHTML =
      `<b>${a.name}</b>${a.is_core ? ' <span class="core-badge" title="LLM core cast: model-authored goals and dialogue">▲ core</span>' : ""} (${a.state}, goal=${a.goal})<br>` +
      `hunger ${a.hunger.toFixed(2)} · energy ${a.energy.toFixed(2)} · age ${a.age_ticks}` +
      (a.goal_reason ? `<br><i>"${a.goal_reason}"</i>` : "") +
      (lastMemory ? `<br><span class="tooltip-memory">${lastMemory}</span>` : "") +
      `<br><span class="muted">click for details</span>`;
    canvas.style.cursor = "pointer";
    return;
  }
  canvas.style.cursor = "default";

  const b = findBuildingAt(gx, gy);
  if (b) {
    tooltip.classList.remove("hidden");
    const pct = Math.round((b.condition || 0) * 100);
    if (subjectiveMode) {
      // §3 "subjective map mode": the village doesn't read a percentage
      // off a wall — it just knows a place as well-kept, worn, or
      // falling apart, mirroring the plain-language bands the server's
      // own `_condition_label` uses for the infrastructure report.
      const label = b.stage === "under_construction" ? "being built"
        : b.stage === "ruined" ? "in ruins"
        : pct >= 80 ? "well-kept"
        : pct >= 50 ? "showing its age"
        : pct >= 20 ? "worn and neglected"
        : "falling apart";
      tooltip.innerHTML = `<b>${b.kind.replace(/_/g, " ")}</b><br>` +
        `<span class="muted">${label}</span>` +
        (b.stored_food ? `<br>keeps a store of food` : "");
      return;
    }
    tooltip.innerHTML =
      `<b>${b.kind}</b> (${b.stage})<br>` +
      `condition ${pct}%` +
      (b.stage === "under_construction" ? ` · progress ${Math.round((b.progress || 0) * 100)}%` : "") +
      (b.stored_food ? `<br>stored food ${b.stored_food.toFixed(1)}` : "");
    return;
  }

  if (terrain && gx >= 0 && gy >= 0 && gx < terrain.width && gy < terrain.height) {
    const biome = terrain.biomes[gy][gx];
    const graves = memorialsAt(gx, gy);
    const graveText = graves.length
      ? `<br><span class="muted">✝ ${graves.map((m) => m.name).join(", ")} rest${graves.length === 1 ? "s" : ""} here</span>`
      : "";
    tooltip.classList.remove("hidden");
    if (subjectiveMode) {
      const s = latest && latest.summary ? activeSettlementSummary(latest.summary) : null;
      const folkName = s && s.place_names ? Object.values(s.place_names).find((n) => biome.startsWith("river") || biome.startsWith("lake")) : null;
      tooltip.innerHTML = `<span class="muted">${folkName || biome.replace(/_/g, " ")}</span>${graveText}` +
        `<br><span class="muted">click for details</span>`;
      return;
    }
    tooltip.innerHTML = `<span class="muted">${biome.replace(/_/g, " ")}</span> (${gx}, ${gy})${graveText}` +
      `<br><span class="muted">click for details</span>`;
    return;
  }
  tooltip.classList.add("hidden");
});

function memorialsAt(gx, gy) {
  return ((latest && latest.memorials) || []).filter((m) => m.x === gx && m.y === gy);
}
canvas.addEventListener("mouseleave", () => {
  tooltip.classList.add("hidden");
  canvas.style.cursor = "default";
});

canvas.addEventListener("click", (ev) => {
  if (panState && panState.moved) return; // that was a drag, not a click
  if (ghost.active) return;
  const rect = canvas.getBoundingClientRect();
  const { gx, gy } = screenToGrid(ev.clientX - rect.left, ev.clientY - rect.top);
  const a = findAgentAt(gx, gy);
  if (a) return openNpcInspector(a.id);
  const b = findBuildingAt(gx, gy);
  if (b) return openBuildingInspector(gx, gy);
  if (terrain && gx >= 0 && gy >= 0 && gx < terrain.width && gy < terrain.height) {
    openTileInspector(gx, gy);
  }
});

// --- NPC inspector: "mind before stats" (Observatory UI direction) ---------
// Opened by clicking an agent on the map. Leads with current goal/reason,
// beliefs held about them, relationships (named, not raw IDs), and recent
// memories — the raw hunger/energy numbers are last, in a single small row,
// not the headline. Stays open across ticks (re-rendered from `latest` on
// every payload) so it doubles as a live view of one NPC's unfolding mind.

const npcBackdrop = document.getElementById("npc-inspector-backdrop");
const npcContent = document.getElementById("npc-inspector-content");
const npcClose = document.getElementById("npc-inspector-close");
let inspectedAgentId = null;
let inspectedTarget = null; // {type: "building"|"tile", x, y} — v0.64.0 click-inspector parity

// Durable full-life-history cache (v0.86.3, Constitution §6): the live
// broadcast payload's agent.memories/semantic_memories are only ever the
// small in-RAM tail — GET /agents/{id}/memory_log reaches everything a
// significant memory/self-theory that's ever been logged to disk, past
// those caps. Fetched on demand (button click), not on every broadcast
// tick, and cached here so it survives renderNpcInspector's innerHTML
// rebuilds across ticks without re-fetching.
let npcMemoryLogCache = { agentId: null, entries: [], totalCount: 0, state: "idle" };

function openNpcInspector(agentId) {
  inspectedAgentId = agentId;
  inspectedTarget = null;
  if (npcMemoryLogCache.agentId !== agentId) {
    npcMemoryLogCache = { agentId, entries: [], totalCount: 0, state: "idle" };
  }
  npcBackdrop.classList.remove("hidden");
  renderNpcInspector();
  // §4 "observer attention as a signal into the Town Consciousness"
  // (docs/IDEAS-2026-07-EMERGENCE.md) — a lightweight fire-and-forget
  // beacon, no UI feedback needed; failure is silently non-fatal (the
  // inspector itself doesn't depend on it).
  fetch("/observer/attention", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ agent_id: agentId }),
  }).catch(() => {});
}

async function loadNpcMemoryLog(agentId) {
  npcMemoryLogCache = { agentId, entries: [], totalCount: 0, state: "loading" };
  renderNpcInspector();
  try {
    const data = await fetchJSON(`/agents/${agentId}/memory_log?limit=200`);
    npcMemoryLogCache = { agentId, entries: data.entries || [], totalCount: data.total_count || 0, state: "loaded" };
  } catch (err) {
    npcMemoryLogCache = { agentId, entries: [], totalCount: 0, state: "error" };
  }
  renderNpcInspector();
}

function openBuildingInspector(x, y) {
  inspectedTarget = { type: "building", x, y };
  inspectedAgentId = null;
  npcBackdrop.classList.remove("hidden");
  renderTargetInspector();
}

function openTileInspector(x, y) {
  inspectedTarget = { type: "tile", x, y };
  inspectedAgentId = null;
  npcBackdrop.classList.remove("hidden");
  renderTargetInspector();
}

function closeNpcInspector() {
  inspectedAgentId = null;
  inspectedTarget = null;
  npcBackdrop.classList.add("hidden");
}

// Follow button inside the (innerHTML-rebuilt) inspector: event
// delegation, since direct listeners wouldn't survive re-render.
if (npcContent) {
  npcContent.addEventListener("click", (ev) => {
    const followBtn = ev.target.closest("[data-follow]");
    if (followBtn) window.hmFollowAgent(Number(followBtn.dataset.follow), followBtn.dataset.followName || "them");
    const memoryBtn = ev.target.closest("[data-load-memory-log]");
    if (memoryBtn) loadNpcMemoryLog(Number(memoryBtn.dataset.loadMemoryLog));
  });
}

if (npcClose) {
  npcClose.addEventListener("click", closeNpcInspector);
  npcBackdrop.addEventListener("click", (ev) => {
    if (ev.target === npcBackdrop) closeNpcInspector();
  });
}

function renderNpcInspector() {
  if (inspectedAgentId === null || !latest) return;
  const agent = (latest.agents || []).find((a) => a.id === inspectedAgentId);
  if (!agent) {
    npcContent.innerHTML = `<h3>Gone</h3><div class="npc-subtitle">This person is no longer among the living.</div>`;
    return;
  }
  const byId = new Map((latest.agents || []).map((a) => [a.id, a]));
  const beliefSources = (latest.settlement_summaries && latest.settlement_summaries.length)
    ? latest.settlement_summaries
    : [(latest.summary && latest.summary.settlement) || {}];
  const beliefs = beliefSources.flatMap((s) => s.beliefs || [])
    .filter((b) => b.subject_agent_id === agent.id);
  const relationships = Object.entries(agent.relationships || {})
    .map(([idStr, affinity]) => ({ name: (byId.get(Number(idStr)) || {}).name || `#${idStr}`, affinity }))
    .sort((a, b) => Math.abs(b.affinity) - Math.abs(a.affinity))
    .slice(0, 8);
  const memories = (agent.memories || []).slice(-6).reverse();
  const ownBeliefs = (agent.beliefs || []).slice().reverse();
  const semanticMemories = (agent.semantic_memories || []).slice().reverse();
  const debts = Object.entries(agent.debts || {})
    .map(([idStr, amount]) => ({ name: (byId.get(Number(idStr)) || {}).name || `#${idStr}`, amount }))
    .sort((a, b) => b.amount - a.amount);

  const relHtml = relationships.length
    ? `<ul>${relationships.map((r) => {
        const tone = r.affinity >= 0.3 ? "close to" : r.affinity <= -0.3 ? "at odds with" : "knows";
        return `<li>${tone} <b>${r.name}</b> <span class="muted">(${r.affinity >= 0 ? "+" : ""}${r.affinity.toFixed(2)})</span></li>`;
      }).join("")}</ul>`
    : `<div class="muted">no notable relationships yet</div>`;
  const beliefsHtml = beliefs.length
    ? `<ul>${beliefs.map((b) => `<li>${b.belief}</li>`).join("")}</ul>`
    : `<div class="muted">the village hasn't formed a theory about them yet</div>`;
  const debtsHtml = debts.length
    ? `<ul>${debts.map((d) => `<li>owes <b>${d.name}</b> <span class="muted">(${d.amount.toFixed(2)})</span></li>`).join("")}</ul>`
    : `<div class="muted">owes nobody anything outstanding</div>`;
  const memoriesHtml = memories.length
    ? `<ul>${memories.map((m) => `<li>${m}</li>`).join("")}</ul>`
    : `<div class="muted">nothing memorable yet</div>`;
  // v0.87.16 "deepen long-term historical identity": memories major
  // enough to have graduated out of the ordinary recency window —
  // still remembered years later, not just recently.
  const coreMemories = agent.core_memories || [];
  const coreMemoriesHtml = coreMemories.length
    ? `<ul>${coreMemories.map((m) => `<li>${m}</li>`).join("")}</ul>`
    : `<div class="muted">nothing has marked them for life yet</div>`;
  // Phase J (v0.78.0): their own private theories + distilled semantic
  // memories, distinct from "What the village believes about them"
  // above (settlement-wide theory) — this is what THEY privately think,
  // written by the same Reflect()-extended personal_belief job.
  const lifeDigestHtml = agent.life_digest ? `<div class="muted"><i>"${agent.life_digest}"</i></div>` : "";
  const reflectionsHtml = (ownBeliefs.length || semanticMemories.length || agent.life_digest)
    ? `${lifeDigestHtml}<ul>${semanticMemories.map((m) => `<li>${m}</li>`).join("")}${ownBeliefs.map((b) => `<li><span class="muted">(re: ${b.subject})</span> ${b.belief}</li>`).join("")}</ul>`
    : `<div class="muted">no private theories yet</div>`;
  // Lessons (v0.87.0, "learns like a human"): situation-tagged
  // takeaways from lived experience — see Agent.lessons, written by the
  // same Reflect() job as "Their own reflections" above but distinct
  // from it: a lesson is indexed by WHEN it applies (hunger/conflict/
  // grief/danger/social), surfaced back into this agent's own cognition
  // prompt the next time that situation recurs.
  const lessons = (agent.lessons || []).slice().reverse();
  const lessonsHtml = lessons.length
    ? `<ul>${lessons.map((l) => `<li><span class="muted">(${l.situation})</span> ${l.text}</li>`).join("")}</ul>`
    : `<div class="muted">no lessons learned yet</div>`;
  const traits = agent.traits || {};
  const traitLabel = (value) => {
    const v = value || 0;
    if (Math.abs(v) < 0.15) return "unremarkable";
    return v > 0 ? "notably high" : "notably low";
  };
  const traitsHtml = `<div class="npc-stats-row">
    <span>resilience ${(traits.resilience || 0).toFixed(2)} <span class="muted">(${traitLabel(traits.resilience)})</span></span>
    <span>sociability ${(traits.sociability || 0).toFixed(2)} <span class="muted">(${traitLabel(traits.sociability)})</span></span>
    <span>ambition ${(traits.ambition || 0).toFixed(2)} <span class="muted">(${traitLabel(traits.ambition)})</span></span>
    <span>openness ${(traits.openness || 0).toFixed(2)} <span class="muted">(${traitLabel(traits.openness)})</span></span>
  </div>`;
  const emotions = agent.emotions || {};
  const emotionMeta = {
    fear: { label: "afraid", icon: "😨" },
    joy: { label: "joyful", icon: "😊" },
    grief: { label: "grieving", icon: "😢" },
    anger: { label: "angry", icon: "😠" },
  };
  const emotionEntries = Object.entries(emotions)
    .filter(([, v]) => v >= 0.1)
    .sort((a, b) => b[1] - a[1]);
  const emotionsHtml = emotionEntries.length
    ? `<div class="npc-stats-row">${emotionEntries.map(([name, v]) => {
        const meta = emotionMeta[name] || { label: name, icon: "" };
        return `<span>${meta.icon} ${meta.label} <span class="muted">${v.toFixed(2)}</span></span>`;
      }).join("")}</div>`
    : `<div class="muted">calm, nothing weighing on them right now</div>`;
  const skills = agent.skills || {};
  const skillEntries = Object.entries(skills).filter(([, v]) => v > 0.01);
  const skillsHtml = skillEntries.length
    ? `<div class="npc-stats-row">${skillEntries.map(([name, v]) => `<span>${name} ${v.toFixed(2)}</span>`).join("")}</div>`
    : `<div class="muted">no notable skill yet</div>`;

  const myInstitutions = ((latest.institutions) || []).filter(
    (i) => (i.member_agent_ids || []).includes(agent.id)
  );
  const institutionLabel = (inst) => {
    if (inst.kind === "family") {
      const others = (inst.member_agent_ids || []).filter((id) => id !== agent.id)
        .map((id) => (byId.get(id) || {}).name).filter(Boolean);
      return others.length ? `Family, with ${others.join(", ")}` : "Family";
    }
    if (inst.kind === "council") return "Sits on the council of elders";
    if (inst.kind === "guild") return `Member of the ${inst.name} guild`;
    if (inst.kind === "faction") return `Part of ${inst.name || "a faction"}`;
    return inst.kind;
  };
  // §9 "institutions get their own persistent memory": culture_digest is
  // an independently-authored line distinct from the institution's
  // mirrored beliefs — shown as a quiet sub-line under its membership
  // entry when one has been formed.
  const institutionsHtml = myInstitutions.length
    ? `<ul>${myInstitutions.map((i) => `<li>${institutionLabel(i)}${
        i.culture_digest ? `<div class="npc-goal-reason">"${i.culture_digest}"</div>` : ""
      }</li>`).join("")}</ul>`
    : `<div class="muted">no institution ties yet</div>`;

  npcContent.innerHTML = `
    <h3>${agent.name}${agent.is_core ? ' <span class="core-badge" title="LLM core cast: goals and dialogue are model-authored, not the deterministic fallback">▲ core</span>' : ""}</h3>
    <div class="npc-subtitle">${agent.state}, age ${agent.age_ticks}</div>
    <button class="npc-follow-btn" data-follow="${agent.id}" data-follow-name="${agent.name}">⌖ follow on map</button>
    ${agent.mind ? `<div class="npc-section"><h4>At their core</h4><div class="npc-goal-reason">${agent.mind}</div></div>` : ""}
    <div class="npc-section">
      <h4>Right now</h4>
      <div>Pursuing <b>${agent.goal}</b></div>
      ${agent.goal_reason ? `<div class="npc-goal-reason">"${agent.goal_reason}"</div>` : ""}
    </div>
    ${agent.plan ? `<div class="npc-section">
      <h4>Current plan</h4>
      <div>${agent.plan.intent} <span class="muted">(${agent.plan.days_remaining} days left)</span></div>
      ${agent.plan.progress_note ? `<div class="npc-goal-reason">"${agent.plan.progress_note}"</div>` : ""}
    </div>` : ""}
    ${agent.standing_penalty > 0 ? `<div class="npc-section">
      <h4>Standing</h4>
      <div>🚫 Ostracized <span class="muted">(penalty ${(agent.standing_penalty * 100).toFixed(0)}%, fading over time)</span></div>
    </div>` : ""}
    <div class="npc-section">
      <h4>Feeling</h4>
      ${emotionsHtml}
    </div>
    <div class="npc-section">
      <h4>What the village believes about them</h4>
      ${beliefsHtml}
    </div>
    <div class="npc-section">
      <h4>Relationships</h4>
      ${relHtml}
    </div>
    <div class="npc-section">
      <h4>Debts</h4>
      ${debtsHtml}
    </div>
    <div class="npc-section">
      <h4>Recent memories</h4>
      ${memoriesHtml}
    </div>
    <div class="npc-section">
      <h4>Never forgotten</h4>
      ${coreMemoriesHtml}
    </div>
    <div class="npc-section">
      <h4>Their own reflections</h4>
      ${reflectionsHtml}
    </div>
    <div class="npc-section">
      <h4>Lessons learned</h4>
      ${lessonsHtml}
    </div>
    <div class="npc-section">
      <h4>Full life history</h4>
      ${renderMemoryLogSection(agent.id)}
    </div>
    <div class="npc-section">
      <h4>Personality</h4>
      ${traitsHtml}
    </div>
    <div class="npc-section">
      <h4>Skills</h4>
      ${skillsHtml}
    </div>
    <div class="npc-section">
      <h4>Institutions</h4>
      ${institutionsHtml}
    </div>
    <div class="npc-section">
      <h4>Vitals</h4>
      <div class="npc-stats-row">
        <span>hunger ${agent.hunger.toFixed(2)}</span>
        <span>energy ${agent.energy.toFixed(2)}</span>
        <span>position (${agent.x}, ${agent.y})</span>
        <span>${healthLabel(agent)}</span>
        ${typeof agent.reputation === "number" && agent.reputation !== 0
          ? `<span title="mean village trust toward them">reputation ${agent.reputation >= 0 ? "+" : ""}${agent.reputation.toFixed(2)}</span>`
          : ""}
      </div>
    </div>
  `;
}

function renderMemoryLogSection(agentId) {
  // The durable, disk-backed counterpart to "Recent memories"/"Their
  // own reflections" above (which only ever show the small in-RAM
  // tail) — engineered emergent learning made visible, not hidden
  // behind the dev console (v0.86.3, Constitution §6).
  if (npcMemoryLogCache.agentId !== agentId || npcMemoryLogCache.state === "idle") {
    return `<button class="npc-load-btn" data-load-memory-log="${agentId}">Load full life history from disk</button>`;
  }
  if (npcMemoryLogCache.state === "loading") {
    return `<div class="muted">loading their full history…</div>`;
  }
  if (npcMemoryLogCache.state === "error") {
    return `<div class="muted">couldn't load their history right now</div>`;
  }
  const { entries, totalCount } = npcMemoryLogCache;
  if (!entries.length) {
    return `<div class="muted">nothing preserved on disk yet — a fuller history accumulates as their life goes on</div>`;
  }
  const memoryLogLabels = {
    semantic: "self-theory", belief: "private belief", secret: "secret",
    lesson: "lesson learned", episodic_drifted: "memory, as remembered now",
    plan: "plan formed",
  };
  const items = entries.map((e) => {
    const label = memoryLogLabels[e.kind] || "memory";
    return `<li><span class="muted">[${label}, tick ${e.tick}]</span> ${e.text}</li>`;
  }).join("");
  return `
    <div class="muted">${totalCount} entries preserved from a fuller life (showing ${entries.length})</div>
    <ul class="npc-memory-log">${items}</ul>
  `;
}

function healthLabel(agent) {
  if ((agent.sick_ticks || 0) > 0) return `sick, ${agent.sick_ticks} ticks`;
  if ((agent.immune_ticks || 0) > 0) return `recently immune, ${agent.immune_ticks} ticks`;
  return "healthy";
}

// --- building / bare-tile click inspector (v0.64.0 UI backlog) ---------------
// Parity with the NPC inspector: click anything on the map and get a real
// panel, not just a hover tooltip. Re-rendered per payload like the NPC one.

function renderTargetInspector() {
  if (!inspectedTarget || !latest) return;
  const { x, y } = inspectedTarget;
  if (inspectedTarget.type === "building") {
    const b = (latest.buildings || []).find((bb) => bb.x === x && bb.y === y);
    if (!b) {
      npcContent.innerHTML = `<h3>Gone</h3><div class="npc-subtitle">Nothing stands here any more.</div>`;
      return;
    }
    const byId = new Map((latest.agents || []).map((a) => [a.id, a]));
    const owner = b.owner_agent_id != null
      ? ((byId.get(b.owner_agent_id) || {}).name || "someone no longer living")
      : "the village (commons)";
    const kindSpaced = b.kind.replace(/_/g, " ");
    const label = kindSpaced.charAt(0).toUpperCase() + kindSpaced.slice(1);
    const conditionPct = Math.round((b.condition || 0) * 100);
    const occupants = (latest.agents || []).filter((a) => a.x === x && a.y === y).map((a) => a.name);
    npcContent.innerHTML = `
      <h3>${label}</h3>
      <div class="npc-subtitle">${b.stage.replace(/_/g, " ")} at (${x}, ${y})</div>
      <div class="npc-section"><h4>Condition</h4>
        <div>${conditionPct}%${b.stage === "under_construction" ? ` · progress ${Math.round((b.progress || 0) * 100)}%` : ""}</div>
      </div>
      <div class="npc-section"><h4>Ownership</h4><div>Belongs to ${owner}</div></div>
      ${b.stored_food ? `<div class="npc-section"><h4>Stores</h4><div>${b.stored_food.toFixed(1)} food</div></div>` : ""}
      <div class="npc-section"><h4>Right now</h4>
        <div>${occupants.length ? `Present: ${occupants.join(", ")}` : "Nobody inside"}</div>
      </div>`;
    return;
  }
  // Bare tile: biome, whatever sits on it, and whoever rests beneath it.
  const biome = terrain && terrain.biomes[y] ? terrain.biomes[y][x] : "?";
  const node = (latest.resources || []).find((n) => n.x === x && n.y === y);
  const mineral = (latest.minerals || []).find((m) => m.x === x && m.y === y);
  const farm = (latest.farms || []).find((f) => f.x === x && f.y === y);
  const roadEntry = (latest.roads || []).find(([rx, ry]) => rx === x && ry === y);
  const graves = memorialsAt(x, y);
  const bits = [];
  if (node) bits.push(`<div class="npc-section"><h4>Wild resource</h4><div>${node.kind}, ${Math.round(node.amount * 100) / 100} remaining</div></div>`);
  if (mineral) bits.push(`<div class="npc-section"><h4>Mineral vein</h4><div>${mineral.kind}, ${Math.round(mineral.amount * 100) / 100} remaining</div></div>`);
  if (farm) bits.push(`<div class="npc-section"><h4>Field</h4><div>${farm.stage}${farm.stage === "growing" ? `, ${Math.round(farm.growth * 100)}% grown` : `, ${farm.amount.toFixed(1)} to harvest`}</div></div>`);
  if (roadEntry) {
    const paved = pavingUnlockedFlag() && roadEntry[2] >= 0.85;
    const label = paved ? " — a paved road" : roadEntry[2] >= 0.5 ? " — an established road" : "";
    bits.push(`<div class="npc-section"><h4>Path</h4><div>worn ${Math.round(roadEntry[2] * 100)}%${label}</div></div>`);
  }
  if (graves.length) {
    bits.push(`<div class="npc-section"><h4>Resting here</h4><ul>${graves.map((m) => `<li>✝ ${m.name} — ${m.cause} (tick ${m.tick})</li>`).join("")}</ul></div>`);
  }
  npcContent.innerHTML = `
    <h3>${biome.replace(/_/g, " ")}</h3>
    <div class="npc-subtitle">tile (${x}, ${y})</div>
    ${bits.join("") || '<div class="muted">nothing but the land itself</div>'}`;
}

// --- consequences overlay ("the village is aging," not raw stats) ----------
// Map-as-primary-interface direction (CLAUDE.md, Observatory UI): plain-
// language readouts of what the raw numbers actually mean, layered directly
// on the map rather than another sidebar panel. Thresholds mirror the sim's
// own lifespan constants (agent.py's MIN_LIFESPAN_TICKS=20000) the same way
// daylight.py's UK_DAYLIGHT_HOURS is already mirrored client-side.
const MIN_LIFESPAN_TICKS = 20000;
const consequencesStrip = document.getElementById("consequences-strip");
let lastPredatorTotal = 0;
let wolvesReturnedUntilTick = -1;

function computeConsequences(summary) {
  const out = [];
  const p = summary.population, s = summary.settlement, w = summary.wildlife, d = summary.disasters;
  if (p && p.total > 0 && p.avg_age_ticks / MIN_LIFESPAN_TICKS > 0.55) {
    out.push("The village is aging.");
  }
  if (p && p.total > 0 && p.total <= 3) {
    out.push("The village teeters on the edge of extinction.");
  }
  if (p && p.total > 0 && p.sick_count / p.total > 0.05) {
    out.push("Sickness is spreading through the village.");
  }
  const granaryCap = s && s.granary_capacity;
  if (granaryCap) {
    const frac = s.granary_food / granaryCap;
    if (frac > 0.85) out.push("Granaries are nearly full.");
    else if (frac < 0.1) out.push("Food stores are running dangerously low.");
  }
  if (w) {
    if (w.predator_total > 0 && lastPredatorTotal === 0) wolvesReturnedUntilTick = summary.tick + 200;
    lastPredatorTotal = w.predator_total;
    if (summary.tick <= wolvesReturnedUntilTick) out.push("Wolves have returned.");
  }
  if (d) {
    if (d.heatwave_active) out.push("A heatwave grips the land.");
    if (d.active_flood_tiles > 0) out.push("Floodwater has swallowed part of the village.");
    if (d.active_wildfire_tiles > 0) out.push("Wildfire is spreading through the forest.");
  }
  return out.slice(0, 3);
}

function renderConsequences(summary) {
  const items = computeConsequences(summary);
  consequencesStrip.classList.toggle("hidden", items.length === 0);
  consequencesStrip.innerHTML = items.map((text) => `<li>${text}</li>`).join("");
}

function fmtPct(x) { return `${Math.round(x * 100)}%`; }

// --- settlement switcher (multiple named settlements, v0.65.0) --------------
// The stats/beliefs/culture detail panels show ONE settlement at a time;
// with a single settlement the chips stay hidden and everything reads
// exactly as before.

let activeSettlementId = 0;
const settlementChipsEl = document.getElementById("settlement-chips");

function activeSettlementSummary(summary) {
  const list = (latest && latest.settlement_summaries) || [];
  if (list.length > 1) {
    const found = list.find((s) => s.id === activeSettlementId);
    if (found) return found;
  }
  return summary.settlement;
}

function renderSettlementChips(payload) {
  if (!settlementChipsEl) return;
  const list = payload.settlement_summaries || [];
  if (list.length < 2) {
    settlementChipsEl.classList.add("hidden");
    return;
  }
  settlementChipsEl.classList.remove("hidden");
  settlementChipsEl.innerHTML = list.map((s) =>
    `<button class="settlement-chip${s.id === activeSettlementId ? " active" : ""}" data-sid="${s.id}">` +
    `${s.name || "(unnamed)"} · ${s.members}</button>`
  ).join("");
}

if (settlementChipsEl) {
  settlementChipsEl.addEventListener("click", (ev) => {
    const chip = ev.target.closest(".settlement-chip");
    if (!chip) return;
    activeSettlementId = Number(chip.dataset.sid);
    if (latest) {
      renderSettlementChips(latest);
      renderStats(latest.summary);
    }
  });
}

// --- §3 "subjective map mode" (docs/IDEAS-2026-07-EMERGENCE.md) ------------
// Pure client-side re-presentation of data the server already sends every
// tick (belief_digest/culture_digest/place_names/folklore, plus building
// condition and terrain coordinates already in the payload) — no new
// endpoint, no new LLM call. Toggling re-reads the last-rendered `latest`
// payload rather than waiting for the next tick, so the switch feels
// immediate.
let subjectiveMode = false;
const subjectiveMapToggle = document.getElementById("subjective-map-toggle");

function renderSubjectiveSummary(s) {
  const panel = document.getElementById("subjective-summary-panel");
  panel.style.display = subjectiveMode ? "" : "none";
  if (!subjectiveMode) return;
  document.getElementById("subjective-summary-title").textContent =
    `${s.name || "The village"}'s own view`;
  const beliefEl = document.getElementById("subjective-belief-digest");
  beliefEl.innerHTML = s.belief_digest ? `<i>"${s.belief_digest}"</i>` : "The village hasn't settled on what it believes about itself yet.";
  const cultureEl = document.getElementById("subjective-culture-digest");
  cultureEl.innerHTML = s.culture_digest ? `<i>"${s.culture_digest}"</i>` : "";
  const placesEl = document.getElementById("subjective-place-names");
  const names = Object.values(s.place_names || {});
  placesEl.textContent = names.length ? `Known to the village as: ${names.join(", ")}.` : "";
}

subjectiveMapToggle.addEventListener("click", () => {
  subjectiveMode = !subjectiveMode;
  subjectiveMapToggle.classList.toggle("active", subjectiveMode);
  document.body.classList.toggle("subjective-mode", subjectiveMode);
  if (latest && latest.summary) renderSubjectiveSummary(activeSettlementSummary(latest.summary));
});

function eraInfrastructureSuffix(eraInfrastructure) {
  // §9 "stalled era progression" fix: a plain-language "what's still
  // needed for the next step" line, since the raw counts alone
  // (huts/roads/schools/carts) read as internal accounting otherwise.
  if (!eraInfrastructure) return "";
  const { next_era: nextEra, requirement: req, current: cur } = eraInfrastructure;
  const missing = ["huts", "roads", "schools", "carts"]
    .filter((k) => cur[k] < req[k])
    .map((k) => `${cur[k]}/${req[k]} ${k}`);
  if (!missing.length) return ` — ready to advance to ${nextEra}`;
  return ` — next: ${nextEra} (needs ${missing.join(", ")})`;
}

function renderStats(summary) {
  const p = summary.population, r = summary.resources;
  const s = activeSettlementSummary(summary);
  renderSubjectiveSummary(s);
  const f = summary.farms, llm = summary.llm, w = summary.wildlife, rd = summary.roads;
  const c = summary.climate;
  const tiles = [
    ["__section__", "Time & weather"],
    ["Tick", summary.tick, null],
    ["Date", `${summary.date} (${summary.clock})`, null],
    ["Weather", summary.weather, null],
    [
      "Daylight",
      (() => {
        const [sunrise, sunset] = UK_DAYLIGHT_HOURS[summary.month] || [6, 18];
        const fmt = (h) => `${String(Math.floor(h)).padStart(2, "0")}:${String(Math.round((h % 1) * 60)).padStart(2, "0")}`;
        return `${fmt(sunrise)} - ${fmt(sunset)} (${(sunset - sunrise).toFixed(1)}h)`;
      })(),
      "Approximate real UK sunrise/sunset for the current month, driving the day/night lighting tint on the map.",
    ],
    [
      "Climate trend",
      c ? `warming ${c.warming >= 0 ? "+" : ""}${c.warming.toFixed(2)}, drying ${c.drying >= 0 ? "+" : ""}${c.drying.toFixed(2)}` : "n/a",
      "A slow, bounded random walk nudged once a year (-1..1 each). Positive warming shrinks mountain/snowcap; " +
      "positive drying shrinks water and expands grassland's reach into forest. Drives gradual, map-wide biome drift " +
      "— distinct from the tick-by-tick local deforestation/reclamation you'll see in the event log.",
    ],
    ["__section__", "Population & society"],
    ["Population", `${p.total} (${p.awake} awake, ${p.resting} resting)`, null],
    ["Avg hunger / energy", `${p.avg_hunger.toFixed(2)} / ${p.avg_energy.toFixed(2)}`, null],
    [
      "Deaths", `${p.deaths_starvation} starvation, ${p.deaths_old_age} old age, ${p.deaths_predator || 0} predator`,
      null,
    ],
    [
      "Relationships", `${p.close_bonds} close, ${p.rivalries} rivalries (avg ${p.avg_affinity.toFixed(2)})`,
      "Close: affinity ≥ 0.6 (reproduction-eligible). Rivalries: affinity ≤ -0.4. " +
      "Affinity moves via colocation and NPC dialogue sentiment; ranges -1 (rivalry) to 1 (bonded).",
    ],
    [
      "Carrying capacity", `${p.total} / ${p.carrying_capacity != null ? p.carrying_capacity.toFixed(0) : "?"}`,
      "A dynamic ceiling on population, not a flat cap: composed from housing (huts), granary fill, sickness/predator " +
      "pressure, the fraction of mature/healthy agents, and current weather. Recomputed every tick; growth slows as " +
      "population approaches it. Each hut houses more people once the settlement's era reaches modern (1.3x) or " +
      "digital (1.6x) — denser housing, not just more of it.",
    ],
    [
      "Institutions",
      `${s.institutions ? s.institutions.total : 0} (${s.institutions ? s.institutions.families : 0} families, ` +
      `${s.institutions ? s.institutions.councils || 0 : 0} councils, ` +
      `${s.institutions && s.institutions.factions ? s.institutions.factions.length : 0} factions)`,
      "Persistent entities the population organizes into. Families form automatically at a birth and outlive their " +
      "individual members — beliefs and, on a member's death, land/goods/skill/bias inheritance flow through them. " +
      "A council of elders forms once a named settlement's population is large enough, membership fixed at formation. " +
      "Factions form when a cluster of villagers grows closer to each other than to anyone else — chosen loyalty, " +
      "not blood or trade.",
    ],
    [
      "Skills & tools",
      `farming ${(p.avg_farming_skill || 0).toFixed(2)}, construction ${(p.avg_construction_skill || 0).toFixed(2)}, ` +
      `tools ${(p.avg_tools || 0).toFixed(2)}, medicine ${(p.avg_medicine || 0).toFixed(2)}`,
      "Skills are gained by practice and colocated teaching: farming boosts a harvester's own yield up to 25%, " +
      "construction speeds that worker's own build/repair contribution up to 25%. Tools (crafted by workshops) boost " +
      "gathering yield up to 40%; medicine (crafted by hospitals) roughly halves a sick holder's own death chance.",
    ],
    [
      "Personality (avg)",
      `resilience ${(p.avg_resilience || 0).toFixed(2)}, sociability ${(p.avg_sociability || 0).toFixed(2)}, ` +
      `ambition ${(p.avg_ambition || 0).toFixed(2)}, openness ${(p.avg_openness || 0).toFixed(2)}`,
      "Population-wide average of each personal trait axis (-1..1, 0 = neutral). Resilience is worn down by grief/" +
      "violence/hunger and recovers slowly; sociability rises with positive trade contact; ambition rises when an " +
      "agent founds a building or first masters a skill; openness rises on direct contact with outside news (a " +
      "caravan's rumor). All four drift back toward neutral over time.",
    ],
    ["__section__", "Settlement & infrastructure"],
    ["Buildings", `${s.total} (${s.standing} standing, ${s.under_construction} building, ${s.ruined} ruined)`, null],
    [
      "Civic buildings",
      `${s.workshops} workshop${s.workshops === 1 ? "" : "s"}, ${s.schools} school${s.schools === 1 ? "" : "s"}, ` +
      `${s.hospitals} hospital${s.hospitals === 1 ? "" : "s"}, ${s.universities} universit${s.universities === 1 ? "y" : "ies"}` +
      (s.factories ? `, ${s.factories} factor${s.factories === 1 ? "y" : "ies"}` : "") +
      (s.power_plants ? `, ${s.power_plants} power plant${s.power_plants === 1 ? "" : "s"}` : "") +
      (s.markets ? `, ${s.markets} market${s.markets === 1 ? "" : "s"}` : ""),
      "Workshops generate currency from staffed presence. Schools/universities raise education (shown below), which " +
      "boosts invention chance. Hospitals speed rest recovery on-site and settlement-wide reduce the odds a predator " +
      "attack proves lethal. Factories (era: electrical+) generate currency at double a workshop's rate. Power plants " +
      "(era: electrical+) boost workshop/factory income settlement-wide and add a little carrying-capacity headroom. " +
      "Markets (foundable after the first caravan visit) get better terms on future caravan trades and draw traders " +
      `more often. ${s.caravans_visited || 0} caravan${(s.caravans_visited || 0) === 1 ? " has" : "s have"} visited so far.`,
    ],
    [
      "Era", `${s.era} — ${s.era_description}` + eraInfrastructureSuffix(s.era_infrastructure),
      "Advances with tech level (inventions) AND real infrastructure — see docs/IDEAS-2026-07-EMERGENCE.md §9: " +
      "a settlement can no longer skip straight to a late era on a lucky invention-roll streak with none of that " +
      "era's own huts/roads/schools/carts standing. industrial -> electrical -> modern -> digital, one step at a " +
      "time. Building toward the next era's requirement also raises invention chance directly.",
    ],
    [
      "Education", `${s.education_level.toFixed(2)} / ${s.education_capacity.toFixed(2)}`,
      "Raised by staffed schools/universities (universities contribute 2x). Directly multiplies invention chance: " +
      "1.0 + education_level.",
    ],
    [
      "Vehicles",
      `${s.vehicles.carts_ready} cart${s.vehicles.carts_ready === 1 ? "" : "s"}, ` +
      `${s.vehicles.mounts_ready} mount${s.vehicles.mounts_ready === 1 ? "" : "s"} ` +
      `(${s.vehicles.mounts_claimed} claimed)` +
      (s.vehicles.automobiles_total
        ? `, ${s.vehicles.automobiles_ready} automobile${s.vehicles.automobiles_ready === 1 ? "" : "s"} (${s.vehicles.automobiles_claimed} claimed)`
        : "") +
      (s.vehicles.rafts_total
        ? `, ${s.vehicles.rafts_ready} raft${s.vehicles.rafts_ready === 1 ? "" : "s"}`
        : "") +
      (s.vehicles.boats_total
        ? `, ${s.vehicles.boats_ready} boat${s.vehicles.boats_ready === 1 ? "" : "s"} (${s.vehicles.boats_claimed} claimed)`
        : ""),
      "Carts: each ready cart adds 25% to gathered-material haul yield (up to 3 stacked). " +
      "Mounts: an awake agent standing with an unclaimed ready mount claims it and moves ~1.6x faster " +
      "for as long as it stays repaired. Automobiles (era: modern+) work the same way, faster still (~2.2x). " +
      "Rafts: only built at a waterside site, each adds 30% to a fish catch's hunger relief (up to 2 stacked). " +
      "Boats: claimed like a mount, and let their rider actually cross open water — the real water-crossing " +
      "vehicle, unlike a raft's passive fishing bonus. " +
      "All wear with use and weather, and break down if neglected.",
    ],
    [
      "Granaries", `${s.granaries} (${s.granary_food.toFixed(1)} / ${s.granary_capacity.toFixed(1)} food)`,
      "Communal food buffer: well-fed agents present at a standing granary deposit surplus; hungry agents withdraw from it before resorting to wild foraging.",
    ],
    [
      "Water infrastructure", `${s.docks || 0} dock${(s.docks || 0) === 1 ? "" : "s"}, ${s.oil_rigs || 0} oil rig${(s.oil_rigs || 0) === 1 ? "" : "s"}`,
      "Docks: a water-adjacent trade port, staffed presence generates currency like a workshop, and it's where boats are founded. " +
      "Oil rigs: offshore extraction (era: electrical+), double a dock's income rate — the water-infrastructure batch's industrial-scale building.",
    ],
    [
      "Repairs & upkeep", `${s.buildings_repaired || 0} buildings, ${s.vehicles_repaired || 0} vehicles`,
      "All-time count of buildings worked back to full condition and vehicles worked back to ready — real labor NPCs put into upkeep, not just construction.",
    ],
    [
      "Husbandry", `${s.pastures || 0} pastures (${(s.pasture_food || 0).toFixed(1)}/${(s.pasture_capacity || 0).toFixed(1)}), ${s.hatcheries || 0} hatcheries (${(s.hatchery_food || 0).toFixed(1)}/${(s.hatchery_capacity || 0).toFixed(1)})`,
      "Deliberately raised animals/fish, distinct from wild grazer hunting or opportunistic fishing — a standing pasture/hatchery produces food on its own, faster when tended.",
    ],
    [
      "Crime & justice", `${s.thefts_committed || 0} theft${(s.thefts_committed || 0) === 1 ? "" : "s"} · ${(s.laws || []).length} norm${(s.laws || []).length === 1 ? "" : "s"} codified`,
      "All-time count of desperate theft between colocated villagers (a genuinely physical act, not an LLM decision), and how many laws/customs/taboos the village has settled on in response — see Laws & customs below.",
    ],
    [
      "Village storylines",
      (s.top_topics && s.top_topics.length)
        ? s.top_topics.map(([topic]) => topic).join(", ")
        : "nothing dominant yet",
      "What real NPC-to-NPC conversation has actually been about lately, most-talked-about first — several may run at once rather than one unifying theme, distinct from the quarterly narrative theme below.",
    ],
    ["__section__", "Economy"],
    [
      "Materials", `${s.materials.toFixed(1)} / ${s.materials_capacity.toFixed(1)}`,
      "Settlement-wide wood/stone stockpile, gathered by GATHER-goal agents from forest/hills. Spent on faster construction and tool-boosted farm plots.",
    ],
    [
      "Currency", `${s.currency.toFixed(1)} / ${s.currency_capacity.toFixed(1)}`,
      "Settlement-wide wealth, earned by selling food/materials surplus that would otherwise be wasted at capacity. Spent on emergency rations when a granary runs dry.",
    ],
    [
      "Minerals",
      (s.minerals && Object.keys(s.minerals).length)
        ? Object.entries(s.minerals).map(([k, v]) => `${k} ${v.toFixed(1)}`).join(", ")
        : "none gathered yet",
      "Distinct iron and gold veins on hills terrain (§8 expanded mineral economy), gathered separately from bulk materials. Iron sweetens tool-crafting; both sell for far more than materials once a settlement's stockpile is full.",
    ],
    [
      "Tech level", `${s.tech_level} invention${s.tech_level === 1 ? "" : "s"}`,
      "Each invention permanently boosts construction/repair speed and cultivated-food yield (farm harvest, granary stock/withdraw) by 15% — wild foraging is unaffected. Rare: gated by settlement prosperity, rolled once a year.",
    ],
    ["__section__", "World & environment"],
    ["Farms", `${f.total} (${f.growing} growing, ${f.ready} ready)`, null],
    [
      "Wild resources", `${r.total_nodes} nodes (${r.depleted} depleted, ${r.fish_nodes || 0} fishing spots, ${s.fish_caught || 0} caught)`,
      "Wild forageable nodes (berries, fishing spots along water, ore veins) — the last-resort food source, behind farms, granaries, and hunting. Fishing spots yield a richer catch and replenish faster than a bush. \"Caught\" is the settlement's all-time count of meals relieved from a fishing spot specifically.",
    ],
    [
      "Mining scars",
      (() => {
        const ms = summary.mining_scars || {};
        return ms.scarred_tiles ? `${ms.scarred_tiles} hillsides (avg ${ms.avg_intensity.toFixed(2)})` : "none yet";
      })(),
      "Sustained mining visibly pits and darkens a worked hillside over time (see the map itself for the actual scarring) — weathers back to nothing if abandoned. Cosmetic, not a biome change: a scarred hill stays walkable and re-minable.",
    ],
    [
      "Wildlife", `${w.grazer_total} grazers (${w.grazer_herds} herds), ${w.predator_total} predators (${w.predator_packs} packs)`,
      "Grazer herds roam grassland/forest and can be hunted for food; predator packs roam forest/hills and hunt grazers, starving without a kill.",
    ],
    [
      "Roads", `${rd.established_roads} established (${rd.worn_tiles} worn)` + (rd.paving_unlocked ? `, ${rd.paved_roads} paved` : ""),
      "Tiles worn by sustained foot traffic. An established road (wear ≥ 0.5) gives agents standing on it a 1.4x random-walk move-chance bonus. " +
      "Once any settlement reaches the modern era, sustained heavy traffic (wear ≥ 0.85) can pave a road into a faster, more weather-resistant surface (1.7x dry).",
    ],
    ["__section__", "AI, trade & diplomacy"],
    ["LLM calls", `${llm.calls_total} (${fmtPct(llm.fallback_rate)} fallback)`, null],
    ["NPC dialogue", `${llm.dialogue_total} exchanges, ${llm.rumor_total} rumors`, null],
    [
      "Geography",
      (() => {
        const riverTiles = (summary.biome_counts || {}).river || 0;
        const lakes = summary.lakes || [];
        const namedLakes = lakes.filter((l) => l.name);
        let text = `${riverTiles} river tile${riverTiles === 1 ? "" : "s"}, ${lakes.length} lake${lakes.length === 1 ? "" : "s"}`;
        if (summary.river_name) text += ` · river: ${summary.river_name}`;
        if (namedLakes.length) text += ` · ${namedLakes.map((l) => l.name).join(", ")}`;
        return text;
      })(),
      "Rivers are carved once at world creation. Lakes each have their own slowly-changing water level " +
      "(nudged monthly, biased by the climate trend above) that grows or shrinks the shoreline by a tile at a time. " +
      "Once the settlement is named, its waters gradually earn names of their own.",
    ],
    [
      "Market prices",
      (s.market_prices && Object.keys(s.market_prices).length)
        ? Object.entries(s.market_prices).map(([g, p]) => `${g} ${p.toFixed(2)}x`).join(", ")
        : "no market yet (flat 1.00x)",
      "While a MARKET stands, per-good price multipliers re-derive monthly from real scarcity (empty stores -> " +
      "up to 2.0x, full stores -> down to 0.5x). Overflow sales earn the current price; emergency rations cost it.",
    ],
    [
      "Diplomacy",
      (() => {
        const relations = s.relations || {};
        const ids = Object.keys(relations);
        if (!ids.length) return "no sister settlements yet";
        const byId = {};
        (summary.settlements || []).forEach((other) => { byId[other.id] = other.name; });
        return ids.map((id) => {
          const name = byId[id] || `settlement ${id}`;
          const v = relations[id];
          const tone = v > 0.3 ? "warm" : v < -0.3 ? "cold" : "neutral";
          return `${name}: ${tone} (${v.toFixed(2)})`;
        }).join(", ");
      })(),
      "Standing with sister settlements sharing this map — seeded warm at fission, nudged by cross-settlement " +
      "dialogue and occasional named diplomatic moments (envoys, trade pacts, border disputes). Felt in market prices.",
    ],
    [
      "Disasters",
      (() => {
        const d = summary.disasters || {};
        const bits = [];
        if (d.active_flood_tiles) bits.push(`${d.active_flood_tiles} flooded tile${d.active_flood_tiles === 1 ? "" : "s"}`);
        if (d.active_wildfire_tiles) bits.push(`${d.active_wildfire_tiles} wildfire tile${d.active_wildfire_tiles === 1 ? "" : "s"}`);
        if (!bits.length) bits.push("none active");
        return `${bits.join(", ")} (flood pressure ${(d.flood_pressure || 0).toFixed(2)})`;
      })(),
      "Flood pressure builds during sustained heavy rain; past threshold, low ground near water can flood and damage " +
      "nearby buildings/crops. Dry summer forest can catch fire and spread. Extreme wind can batter structures directly.",
    ],
  ];
  setInnerHTMLIfChanged(document.getElementById("stat-grid"), tiles
    .map(([label, value, title]) =>
      label === "__section__"
        ? `<div class="stat-section-label">${value}</div>`
        // `data-tooltip` (not the native `title` attribute) + the
        // delegated hover handler below (see "stat-grid hover
        // tooltip"): `setInnerHTMLIfChanged` replaces this whole grid's
        // DOM nodes on essentially every broadcast (the tick number
        // alone changes the diffed string every time), which resets a
        // native title tooltip's hover timer before it ever has a
        // chance to show — a real regression a live report caught
        // ("hover interactions over details tiles have gone"). A
        // listener on the stable `#stat-grid` container itself doesn't
        // care that the child nodes underneath it keep getting swapped.
        : `<div class="stat-tile"${title ? ` data-tooltip="${escapeHtmlAttr(title)}"` : ""}><div class="label">${label}</div><div class="value">${value}</div></div>`
    )
    .join(""));

  document.getElementById("settlement-name").textContent = s.name || "Hearthmind (unnamed settlement)";
  document.getElementById("clock-line").textContent = `${summary.date} · ${summary.clock} · ${summary.weather}`;

  const beliefsEl = document.getElementById("beliefs-list");
  if (beliefsEl) {
    setInnerHTMLIfChanged(beliefsEl, s.beliefs && s.beliefs.length
      ? s.beliefs
          .slice()
          .sort((a, b) => b.confidence - a.confidence)
          .map((b) => {
            const revised = b.revision_count > 0 ? ` (revised ${b.revision_count}x)` : "";
            return `<li><b>${b.subject}</b>: ${b.belief} <span class="muted">(confidence ${Math.round(b.confidence * 100)}%${revised})</span></li>`;
          })
          .join("")
      : "<li>none yet — forms and revises over time</li>");
  }

  const traditionsEl = document.getElementById("traditions-list");
  setInnerHTMLIfChanged(traditionsEl, s.traditions.length
    ? s.traditions.map((t) => `<li>${t}</li>`).join("")
    : "<li>none yet</li>");

  const folkloreEl = document.getElementById("folklore-list");
  if (folkloreEl) {
    const folklore = (s.folklore || []).slice().reverse(); // newest first
    setInnerHTMLIfChanged(folkloreEl, folklore.length
      ? folklore.map((f) => `<li>${f.tale}</li>`).join("")
      : "<li>no tales told yet</li>");
  }

  const religionSummaryEl = document.getElementById("religion-summary");
  const ritualsEl = document.getElementById("rituals-list");
  if (religionSummaryEl && ritualsEl) {
    setInnerHTMLIfChanged(religionSummaryEl, s.religion
      ? `<b>${s.religion.name}</b>: ${s.religion.tenets.join("; ")}`
      : "");
    const rituals = s.rituals || [];
    setInnerHTMLIfChanged(ritualsEl, rituals.length
      ? rituals.map((r) => `<li>${r.description}</li>`).join("")
      : "<li>nothing repeats often enough to be a ritual yet</li>");
  }

  const lawsEl = document.getElementById("laws-list");
  if (lawsEl) {
    const laws = (s.laws || []).slice().reverse(); // newest first
    const kindLabel = { law: "⚖️ law", custom: "🤝 custom", taboo: "🚫 taboo" };
    setInnerHTMLIfChanged(lawsEl, laws.length
      ? laws.map((l) => `<li><span class="muted">${kindLabel[l.kind] || l.kind}</span> — ${l.text}</li>`).join("")
      : "<li>none codified yet</li>");
  }

  const narrativeThemeEl = document.getElementById("narrative-theme");
  if (narrativeThemeEl) {
    const themes = s.narrative_themes || [];
    const latest = themes.length ? themes[themes.length - 1] : null;
    narrativeThemeEl.classList.toggle("hidden", !latest);
    if (latest) narrativeThemeEl.textContent = `The recent theme of village life: ${latest.themes.join(", ")}`;
  }

  const lexiconEl = document.getElementById("settlement-lexicon");
  if (lexiconEl) {
    const lexicon = s.lexicon || [];
    lexiconEl.classList.toggle("hidden", !lexicon.length);
    if (lexicon.length) {
      lexiconEl.textContent = "Local terms: " + lexicon.map((e) => `"${e.term}" (${e.meaning})`).join("; ");
    }
  }

  const inventionsEl = document.getElementById("inventions-list");
  if (inventionsEl) {
    // v0.87.15 "knowledge lifecycle": a tracked invention whose last
    // knower died reads as dormant here — still remembered, no longer
    // in effect, until a heir rediscovers it.
    const knowledge = s.invention_knowledge || {};
    setInnerHTMLIfChanged(inventionsEl, s.inventions.length
      ? s.inventions.map((t) => {
          const info = knowledge[t];
          return info && info.dormant
            ? `<li>${t} <span class="muted">💤 dormant — no living knower</span></li>`
            : `<li>${t}</li>`;
        }).join("")
      : "<li>none yet</li>");
  }

  const recordsEl = document.getElementById("records-list");
  if (recordsEl) {
    const records = (s.records || []).slice().reverse(); // newest first
    setInnerHTMLIfChanged(recordsEl, records.length
      ? records.map((r) => `<li>✍️ <b>${r.author}</b> <span class="muted">(tick ${r.tick})</span>: "${r.text}"</li>`).join("")
      : "<li>nothing set down yet — notable villagers leave letters behind</li>");
  }

  const festivalsEl = document.getElementById("festivals-list");
  if (festivalsEl && s.festivals) {
    setInnerHTMLIfChanged(festivalsEl, s.festivals.length
      ? s.festivals.map((t) => `<li>${t}</li>`).join("")
      : "<li>none yet</li>");
  }

  // Digests (v0.85.4/.5): one LLM-authored sentence condensing the
  // village's ENTIRE current belief set / accumulated culture — engineered
  // emergent learning made visible (v0.86.3, Constitution §6). Previously
  // computed and fed into prompts but never actually shown anywhere in
  // the UI, despite being exactly the "the world learns and shows it"
  // signal this project's own design priorities call for.
  const digestEl = document.getElementById("belief-digest");
  if (digestEl) {
    digestEl.classList.toggle("hidden", !s.belief_digest);
    if (s.belief_digest) digestEl.innerHTML = `<i>"${s.belief_digest}"</i>`;
  }
  const cultureDigestEl = document.getElementById("culture-digest");
  if (cultureDigestEl) {
    cultureDigestEl.classList.toggle("hidden", !s.culture_digest);
    if (s.culture_digest) cultureDigestEl.innerHTML = `<i>"${s.culture_digest}"</i>`;
  }

  const brainEl = document.getElementById("town-brain-priority");
  if (brainEl) {
    setInnerHTMLIfChanged(brainEl, s.current_priority
      ? `Current priority: <b>${s.current_priority}</b><br><span class="muted">${s.priority_rationale}</span>`
      : "No decision yet — the town brain decides once a season, once the village is named.");
  }
  const monologueEl = document.getElementById("town-brain-monologue");
  if (monologueEl) {
    // "Occasionally reveal what the town notices, values, or is quietly
    // influencing" (Observatory UI direction) — past rationales read
    // together as fragments of an ongoing internal train of thought, not
    // just a single overwritten "current state" line.
    const history = (s.priority_history || []).slice(0, -1).reverse(); // most-recent-first, excluding the current one (already shown above)
    monologueEl.classList.toggle("hidden", history.length === 0);
    setInnerHTMLIfChanged(monologueEl, history
      .map((h) => `<li><span class="muted">tick ${h.tick}, ${h.priority}:</span> ${h.rationale}</li>`)
      .join(""));
  }

  const pendingWhispersEl = document.getElementById("pending-whispers");
  if (pendingWhispersEl) {
    const whispers = s.pending_player_whispers || [];
    pendingWhispersEl.textContent = whispers.length
      ? `Queued, not yet heard: ${whispers.map((w) => `"${w}"`).join("; ")}`
      : "";
    pendingWhispersEl.classList.toggle("hidden", whispers.length === 0);
  }

  const foundingEl = document.getElementById("founding-scenario");
  if (foundingEl) {
    foundingEl.textContent = s.founding_scenario ? `"${s.founding_scenario}"` : "";
    foundingEl.classList.toggle("hidden", !s.founding_scenario);
  }
}

function renderInfrastructure(rows) {
  const el = document.getElementById("infrastructure-list");
  if (!el) return;
  if (!rows || rows.length === 0) {
    setInnerHTMLIfChanged(el, "<li>nothing built yet</li>");
    return;
  }
  setInnerHTMLIfChanged(el, rows
    .slice(0, 40)
    .map((r) => {
      const label = r.kind.charAt(0).toUpperCase() + r.kind.slice(1);
      const pct = Math.round(r.condition * 100);
      const statusClass = `infra-condition-${r.status.replace(/\s+/g, "-")}`;
      return (
        `<li><span class="${statusClass}">${label} (${r.x}, ${r.y}): ${r.status} (${pct}%)</span></li>`
      );
    })
    .join(""));
}

function renderDevConsole(payload) {
  if (devConsole.classList.contains("hidden")) return;
  renderRecorderStatus(payload.diagnostics && payload.diagnostics.training_recorder);
  // Phase N: the town consciousness's persistent inner state is
  // deliberately absent from the main UI (same ambiguity discipline as
  // temperament/mood/player_standing) but belongs squarely in the
  // developer observatory — "prompt inspection, timing, and internals"
  // is exactly what this panel is for. Reads straight off the existing
  // broadcast payload (World.summary()'s "consciousness" key), no new
  // endpoint needed.
  devConsoleContent.textContent = JSON.stringify(
    { diagnostics: payload.diagnostics, llm: payload.summary.llm, consciousness: payload.summary.consciousness },
    null, 2,
  );
}

function prependEvents(events) {
  // `events` must be oldest-first — each is prepended in that order so
  // the newest one ends up at the top of the log.
  const log = document.getElementById("event-log");
  for (const e of events) {
    const meta = categoryMeta(e.category || "");
    if (meta.skip) continue;
    const li = document.createElement("li");
    li.className = `event-category-${e.category || "unknown"}`;
    li.dataset.group = EVENT_GROUP_OF[e.category] || "town";
    if (activeEventGroup !== "all" && li.dataset.group !== activeEventGroup) {
      li.classList.add("hidden-by-filter");
    }
    const tickPart = e.tick !== undefined ? `<span class="event-tick">[${e.tick}]</span>` : "";
    li.innerHTML = `${tickPart}<span class="event-icon">${meta.icon}</span><span class="event-text">${e.description}</span>`;
    log.prepend(li);
  }
  while (log.children.length > 150) log.removeChild(log.lastChild);
}

// --- event-log filter chips (v0.64.0 UI backlog) ------------------------------

const eventChips = document.querySelectorAll(".event-chip");
eventChips.forEach((chip) => {
  chip.addEventListener("click", () => {
    activeEventGroup = chip.dataset.group;
    eventChips.forEach((c) => c.classList.toggle("active", c === chip));
    for (const li of document.getElementById("event-log").children) {
      li.classList.toggle(
        "hidden-by-filter",
        activeEventGroup !== "all" && li.dataset.group !== activeEventGroup,
      );
    }
  });
});

async function refreshTerrainIfChanged(events) {
  if (!events || !events.some((e) => TERRAIN_CHANGING_CATEGORIES.has(e.category))) return;
  try {
    terrain = await fetchJSON("/terrain");
    drawStaticTerrain();
  } catch (e) {
    // non-fatal — the map just stays one step behind until the next change
  }
}

// --- §5 "Ruins mode / successor worlds" (docs/IDEAS-2026-07-EMERGENCE.md) --

const extinctionBanner = document.getElementById("extinction-banner");
const foundSuccessorBtn = document.getElementById("found-successor-btn");

function renderExtinctionBanner(summary) {
  const total = summary.population ? summary.population.total : 0;
  extinctionBanner.classList.toggle("hidden", total > 0);
}

if (foundSuccessorBtn) {
  foundSuccessorBtn.addEventListener("click", async () => {
    foundSuccessorBtn.disabled = true;
    try {
      await fetch("/world/found-successor", { method: "POST" });
    } finally {
      setTimeout(() => { foundSuccessorBtn.disabled = false; }, 3000);
    }
  });
}

// --- §6 "Ambient audio keyed to hidden state" (docs/IDEAS-2026-07-EMERGENCE.md) --
// Generative WebAudio ambience — off by default, no assets. Two detuned
// oscillators through a lowpass filter stand in for a wind/drone pad;
// parameters are smoothly ramped (never recreated) from real broadcast
// state each payload: night_factor/weather_detail (both already public,
// unlabeled), and settlement temperament (Phase G — read here exactly
// like the map already reads it for small nudges, never surfaced as a
// number or a word; the ear notices the world darkening before the eye
// does, the doc's own framing). Nothing here is a "mood" label — it's
// one more silent consumer of state this project already keeps
// deliberately ambiguous everywhere else.

let ambientAudio = null; // { ctx, osc1, osc2, filter, gain } once started

function ensureAmbientAudio() {
  if (ambientAudio) return ambientAudio;
  const AudioCtx = window.AudioContext || window.webkitAudioContext;
  if (!AudioCtx) return null;
  const ctx = new AudioCtx();
  const osc1 = ctx.createOscillator();
  const osc2 = ctx.createOscillator();
  osc1.type = "sine";
  osc2.type = "sine";
  osc1.frequency.value = 110;
  osc2.frequency.value = 110;
  osc2.detune.value = 6;
  const filter = ctx.createBiquadFilter();
  filter.type = "lowpass";
  filter.frequency.value = 800;
  const gain = ctx.createGain();
  gain.gain.value = 0; // fade in on start, never a hard click
  osc1.connect(filter);
  osc2.connect(filter);
  filter.connect(gain);
  gain.connect(ctx.destination);
  osc1.start();
  osc2.start();
  ambientAudio = { ctx, osc1, osc2, filter, gain };
  return ambientAudio;
}

function updateAmbientAudio(summary) {
  if (!ambientAudio || !summary) return;
  const { ctx, osc1, osc2, filter, gain } = ambientAudio;
  const now = ctx.currentTime;
  const RAMP = 4.0; // seconds — slow drift, not a jump cut on every tick payload
  const w = summary.weather_detail || {};
  const nightFactor = summary.night_factor != null ? summary.night_factor : 0;
  const precipitation = w.precipitation != null ? w.precipitation : 0;
  const wind = w.wind != null ? w.wind : 0;
  const temperament = (summary.settlement && summary.settlement.temperament) || 0;

  // Base pitch drops at night, warms (rises) with positive temperament —
  // a small, never-dominant nudge, same magnitude discipline Phase G
  // applies everywhere else it touches a number.
  const baseFreq = 90 + (1 - nightFactor) * 40 + temperament * 15;
  osc1.frequency.linearRampToValueAtTime(baseFreq, now + RAMP);
  osc2.frequency.linearRampToValueAtTime(baseFreq, now + RAMP);
  osc2.detune.linearRampToValueAtTime(6 + wind * 30, now + RAMP);

  // Rain/overcast muffles the pad (lower filter cutoff); clear skies
  // brighten it. Wind adds a little extra openness on top.
  const cutoff = 300 + (1 - precipitation) * 900 + wind * 200;
  filter.frequency.linearRampToValueAtTime(cutoff, now + RAMP);

  // 0.035 (original) read as "unable to hear anything" in a live
  // report — this is meant to stay a subtle ambient pad, not a loud
  // soundtrack, but 0.035 was quiet enough on typical speakers to be
  // indistinguishable from silence. Raised to 0.07, still clearly
  // ambient-not-foreground.
  const targetGain = ambientAudioEnabled ? 0.07 : 0;
  gain.gain.linearRampToValueAtTime(targetGain, now + RAMP);
}

let ambientAudioEnabled = false;
const ambientAudioToggle = document.getElementById("ambient-audio-toggle");
if (ambientAudioToggle) {
  ambientAudioToggle.addEventListener("click", () => {
    ambientAudioEnabled = !ambientAudioEnabled;
    ambientAudioToggle.classList.toggle("active", ambientAudioEnabled);
    if (ambientAudioEnabled) {
      const a = ensureAmbientAudio();
      if (a && a.ctx.state === "suspended") a.ctx.resume();
      if (a) {
        // The very first enable gets a short, snappy fade-in (not
        // updateAmbientAudio's usual 4s drift) so clicking the toggle
        // has an audible, immediate effect instead of reading as "I
        // clicked it and nothing happened" for several seconds.
        a.gain.gain.linearRampToValueAtTime(0.07, a.ctx.currentTime + 0.6);
      }
      if (latest) updateAmbientAudio(latest.summary);
    } else if (ambientAudio) {
      ambientAudio.gain.gain.linearRampToValueAtTime(0, ambientAudio.ctx.currentTime + 4.0);
    }
  });
}

function applyPayload(payload) {
  latest = payload;
  renderSettlementChips(payload);
  renderStats(payload.summary);
  renderExtinctionBanner(payload.summary);
  if (ambientAudioEnabled) updateAmbientAudio(payload.summary);
  renderConsequences(payload.summary);
  renderInfrastructure(payload.infrastructure);
  if (payload.diagnostics && payload.diagnostics.sim_pacing) renderSimPacing(payload.diagnostics.sim_pacing);
  if (payload.diagnostics) renderConsciousnessIndicator(payload.diagnostics);
  if (payload.diagnostics) renderLlamaRestartIndicator(payload.diagnostics);
  if (inspectedAgentId !== null) renderNpcInspector();
  if (inspectedTarget !== null) renderTargetInspector();
  updateAgentAnimTargets(payload.agents || []);
  if (payload.diagnostics) renderDevConsole(payload);
  if (payload.life_events && payload.life_events.length) {
    prependEvents(payload.life_events.map((e) => ({ ...e, tick: payload.summary.tick })));
    refreshTerrainIfChanged(payload.life_events);
    registerThoughtFlashes(payload.life_events, payload.agents);
    // §5 "Era-styled cartography": an era advance changes the map's
    // rendering style even though the terrain itself hasn't changed —
    // repaint the static layer in place (no /terrain refetch needed).
    if (staticCanvas && payload.life_events.some((e) => e.category === "era_advance")) {
      drawStaticTerrain();
    }
  }
}

// --- sim speed controls -----------------------------------------------------

const pauseToggleBtn = document.getElementById("sim-pause-toggle");
const speedDownBtn = document.getElementById("sim-speed-down");
const speedUpBtn = document.getElementById("sim-speed-up");
const speedResetBtn = document.getElementById("sim-speed-reset");
const speedLabel = document.getElementById("sim-speed-label");
let simPaused = false;

function renderSimPacing(pacing) {
  simPaused = !!pacing.paused;
  pauseToggleBtn.textContent = simPaused ? "▶ resume" : "⏸ pause";
  pauseToggleBtn.classList.toggle("active", simPaused);
  const mult = pacing.speed_multiplier || 1;
  speedLabel.textContent = `${mult % 1 === 0 ? mult : mult.toFixed(2)}x`;
}

// --- town-consciousness pressure indicator ----------------------------
// Surfaces SimulationEngine's LLM-pressure tick pacing (see engine.py's
// LLM_PRESSURE_SLOWDOWN_START_RATIO) — distinct from the user's own
// pause button above: this is the SIMULATION deciding, on its own, to
// slow or stop so the LLM-driven minds get to actually finish reasoning
// instead of having their turn dropped. Read at a glance, matching the
// Observatory UI direction, rather than something you'd only notice by
// opening the dev console.
const consciousnessEl = document.getElementById("consciousness-indicator");
const consciousnessLabelEl = document.getElementById("consciousness-label");

function renderConsciousnessIndicator(diagnostics) {
  if (!consciousnessEl) return;
  const ratio = diagnostics.llm_pressure_ratio || 0;
  const paused = !!diagnostics.llm_pressure_paused;
  if (ratio <= 1.0) {
    consciousnessEl.classList.add("hidden");
    return;
  }
  consciousnessEl.classList.remove("hidden");
  consciousnessEl.classList.toggle("consciousness-paused", paused);
  consciousnessLabelEl.textContent = paused
    ? "the town is deep in thought…"
    : "the town is thinking…";
}

// llama-server restart indicator (LLAMA_RESTART_HOURS, v0.87.3): a
// planned, scripts/run.sh-driven restart pauses the simulation outright
// (see engine.py's llama_server_restarting()) — surfaced the same way
// as the pressure indicator above rather than leaving the town to read
// as an unexplained freeze.
const llamaRestartEl = document.getElementById("llama-restart-indicator");

function renderLlamaRestartIndicator(diagnostics) {
  if (!llamaRestartEl) return;
  llamaRestartEl.classList.toggle("hidden", !diagnostics.llama_server_restarting);
}

async function postSimSpeed(body) {
  try {
    const res = await fetch("/intervene/sim-speed", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`${res.status}`);
    renderSimPacing(await res.json());
  } catch (e) {
    // non-fatal — the next tick's broadcast (once resumed) will resync the display
  }
}

if (pauseToggleBtn) {
  pauseToggleBtn.addEventListener("click", () => postSimSpeed({ action: simPaused ? "resume" : "pause" }));
  speedDownBtn.addEventListener("click", () => postSimSpeed({ action: "speed_down" }));
  speedUpBtn.addEventListener("click", () => postSimSpeed({ action: "speed_up" }));
  speedResetBtn.addEventListener("click", () => postSimSpeed({ action: "reset" }));
}

// --- town brain: player whisper form ---------------------------------------

const whisperForm = document.getElementById("whisper-form");
const whisperInput = document.getElementById("whisper-input");
const whisperStatus = document.getElementById("whisper-status");

if (whisperForm) {
  whisperForm.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const text = whisperInput.value.trim();
    if (!text) return;
    whisperStatus.textContent = "whispering…";
    try {
      const res = await fetch("/intervene/town-brain", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, settlement_id: activeSettlementId }),
      });
      if (!res.ok) throw new Error(`${res.status}`);
      whisperInput.value = "";
      whisperStatus.textContent = "heard — folded into the village's next seasonal decision";
    } catch (e) {
      whisperStatus.textContent = `failed: ${e.message}`;
    }
  });
}

function connectWebSocket() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${proto}//${location.host}/ws`);
  ws.onmessage = (ev) => applyPayload(JSON.parse(ev.data));
  ws.onclose = () => {
    document.getElementById("clock-line").textContent = "disconnected — retrying…";
    setTimeout(connectWebSocket, 2000);
  };
  ws.onerror = () => ws.close();
}

// --- sparklines: a sim-year of curves from GET /metrics ---------------------
// The observatory's missing sense of time (July 2026 review, UI pass):
// the map and stat tiles only ever show "now"; these three small curves
// show where the village has been. Client-side render of the per-sim-day
// metrics table, refetched on a slow timer — one row per sim-day means
// the series only gains a point every ~96 ticks, so polling faster
// would be waste.
const SPARKLINE_REFRESH_MS = 60000;
const SPARK_SERIES = [
  { id: "spark-population", key: "population", fmt: (v) => `${v}` },
  { id: "spark-hunger", key: "avg_hunger", fmt: (v) => v.toFixed(2) },
  { id: "spark-granary", key: "granary_food", fmt: (v) => v.toFixed(1) },
];

function drawSparkline(canvas, values) {
  const ctx = canvas.getContext("2d");
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  if (values.length < 2) return;
  const min = Math.min(...values), max = Math.max(...values);
  const span = max - min || 1;
  ctx.strokeStyle = "#8fb8d8";
  ctx.lineWidth = 1.2;
  ctx.beginPath();
  values.forEach((v, i) => {
    const x = (i / (values.length - 1)) * (w - 2) + 1;
    const y = h - 2 - ((v - min) / span) * (h - 4);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

async function refreshSparklines() {
  let rows;
  try {
    rows = await fetchJSON("/metrics?limit=365");
  } catch (e) {
    return; // metrics table empty or endpoint unavailable — panel just stays blank
  }
  if (!Array.isArray(rows) || rows.length === 0) return;
  for (const series of SPARK_SERIES) {
    const canvas = document.getElementById(series.id);
    const valueEl = document.getElementById(`${series.id}-value`);
    if (!canvas) continue;
    const values = rows.map((r) => r[series.key]).filter((v) => typeof v === "number");
    drawSparkline(canvas, values);
    if (valueEl && values.length) valueEl.textContent = series.fmt(values[values.length - 1]);
  }
}

async function boot() {
  terrain = await fetchJSON("/terrain");
  drawStaticTerrain();
  refreshSparklines();
  setInterval(refreshSparklines, SPARKLINE_REFRESH_MS);
  try {
    const initial = await fetchJSON("/state");
    applyPayload(initial);
  } catch (e) {
    // no tick has completed yet — the WebSocket's own on-connect push will paint it
  }
  try {
    const events = await fetchJSON("/events?limit=30");
    prependEvents(events.slice().reverse());
  } catch (e) {
    // non-fatal — event history is a nice-to-have on first paint
  }
  connectWebSocket();
}

boot();
