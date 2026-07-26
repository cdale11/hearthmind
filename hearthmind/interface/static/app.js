"use strict";

// Hearthmind browser window — read-only, no build step (see docs/DECISIONS.md, F1/F2).
// Terrain is fetched once (it never changes); everything else arrives via
// GET /state (initial paint) and then a WebSocket stream, one message per
// tick, in the exact same shape.

const CELL = 12; // px per terrain tile
// M10 "The Living Map" (docs/ROADMAP-2026-07-REMAINING.md, Tier 1.5):
// direct-look finding — at the old CELL=8, the default 64x64 map's
// canvas element was a fixed 512x512px, a small corner of a typical
// browser window with no responsive resize; CLAUDE.md's own standing
// Observatory UI direction says "the map is the primary interface,
// read at a glance" but the base map (every overlay off) didn't read
// that way. Raising CELL is the single safe, self-contained lever
// available without touching the zoom/pan coordinate system (`view.
// scale`, screenToGrid) or adding real responsive-resize handling —
// every draw call and every mouse-position calculation already derives
// from this one constant, so a real fix and a real risk-free change.
// A full responsive canvas (resize-to-viewport) is the rest of M6/M7's
// larger, still-open UI redesign — this is the smallest coherent step
// toward the same direction, not a substitute for it.

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
  wetland: "#4d6e4a",
};

const BUILDING_COLORS = {
  hut: "#c98a3c", granary: "#d9a441", workshop: "#8a7fd6", school: "#4fa3c9",
  hospital: "#e0473c", university: "#2f7fc9", factory: "#5c5c66", shrine: "#c9a3e0",
  power_plant: "#e0c93c", market: "#3ccf9e", bridge: "#b08968",
  pasture: "#8fbf5e", hatchery: "#4ab5cf", dock: "#5c9ead", oil_rig: "#3c3c46",
  forge: "#b5651d", library: "#7a5c3e",
};
const FARM_COLORS = { growing: "#7fae4a", ready: "#e0c34a" };

// Phase 3.C (docs/VISION-2026-07-21-SELFEVOLVING.md) "architecture
// visibly changing on the map per established Innovation concept": a
// settlement whose `architecture_styles` entry names a concept gets its
// buildings outlined in a color deterministically derived from that
// concept's id, instead of the plain default border — a new dominant
// concept (see `ontology.dominant_architecture_concept`'s "most recent
// wins" rule) genuinely changes the outline's hue.
function architectureStyleColor(conceptId) {
  const hue = (conceptId * 137) % 360;
  return `hsl(${hue}, 62%, 58%)`;
}

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
  era_branch: { icon: "🧭" },
  settlement_named: { icon: "🏘️" },
  construction_started: { icon: "🔨" },
  building_completed: { icon: "🏠" },
  building_ruined: { icon: "🏚️" },
  building_reclaimed: { icon: "🌿" },
  farm_planted: { icon: "🌱" },
  birth: { icon: "👶" },
  death: { icon: "💀" },
  dialogue: { skip: true }, // routine crowd background chatter (deterministic fallback, never LLM-authored) — recorded internally (/events, dev console) but not the main feed
  voice_dialogue: { icon: "💬" }, // v1.4.4: the town's one LLM-dialogue voice pair's ordinary lines — was wrongly bucketed under skip:true `dialogue` before this fix, making the pair's whole conversation invisible
  dialogue_surfaced: { icon: "💬✨" }, // a voice-pair line that also changed a belief/relationship/rumor — see population.py's apply_dialogue `surfaced` flag
  voice_pair_change: { icon: "🗣" }, // the town's one LLM-dialogue pair changed (death/rotation)
  rumor: { icon: "📣" },
  tradition: { icon: "🎭" },
  legend: { icon: "🐉" },
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
  pillar_answer: { icon: "🗣" },
  mining_scarred: { icon: "⛏️" },
  disaster_scarred: { icon: "🌋" },
  terrain_eroded: { icon: "🏞️" },
  river_recarved: { icon: "🌊" },
  road_scarred: { icon: "🛤️" },
  wetland_formed: { icon: "🪷" },
  wetland_dried: { icon: "🪷" },
  composite_reaction: { icon: "💥" },
  // P2.3 (docs/AUDIT-2026-07-20.md): 296/16k events (18%) in a live run —
  // routine background texture already surfaced via the Exploration stat
  // tile (v0.87.45), same "recorded internally, not the main feed"
  // treatment as routine `dialogue` above.
  surveyor_finding: { skip: true },
};

// Event-log filter chips (v0.64.0 UI backlog): coarse groups, display-only —
// everything is still stored and still reaches /events untouched.
const EVENT_GROUP_OF = {
  birth: "people", death: "people", dialogue_surfaced: "people", voice_dialogue: "people", voice_pair_change: "people", rumor: "people",
  migrant_arrived: "people", migrant_departed: "people", inheritance: "people", dispute: "people",
  record_written: "people", illness: "people", recovery: "people", predator_attack: "people",
  family_feud: "people", knowledge_lost: "people", theft: "people", composite_reaction: "people",
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
  place_named: "nature", mining_scarred: "nature", disaster_scarred: "nature", terrain_eroded: "nature",
  river_recarved: "nature", road_scarred: "nature", wetland_formed: "nature", wetland_dried: "nature",
  chronicle: "mind", documentary: "mind", sim_summary: "mind", tradition: "mind", invention: "mind",
  festival: "mind", belief_formed: "mind", belief_revised: "mind", omen: "mind",
  institution_belief: "mind", ritual_formed: "mind", religion_formed: "mind",
  narrative_direction: "mind", consciousness_intervention: "mind", dialect_coined: "mind",
  prophecy_formed: "mind", prophecy_confirmed: "mind", prophecy_forgotten: "mind", chronicler_answer: "mind",
  pillar_answer: "mind",
};
let activeEventGroup = "all";

// Terrain evolves now (deforestation, reclamation, climate drift), so the
// once-per-boot static canvas can go stale — re-fetch /terrain and redraw
// only on ticks that actually reported a terrain-changing life event,
// rather than polling every tick for a change that's rare by design.
const TERRAIN_CHANGING_CATEGORIES = new Set([
  "terrain_thinned", "terrain_reclaimed", "climate_drift",
  "disaster_flood", "disaster_wildfire", "lake_rose", "lake_receded",
  "mining_scarred", "disaster_scarred", "building_reclaimed", "terrain_eroded",
  "river_recarved", "road_scarred",
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

// M6/M7 "The Living Map," the responsive-canvas redesign (docs/
// ROADMAP-2026-07-REMAINING.md, Tier 1.5) — the last open item after
// legends/gradients/hotspots/thresholds all shipped. `canvas.width`/
// `.height` (the drawing BUFFER, in world pixels = tiles * CELL) stay
// the map's one true coordinate system; every draw call and the zoom/
// pan `view` transform already key off it and are untouched. Only the
// element's CSS DISPLAY size changes here, via `resizeCanvasDisplay`,
// so the map fills the actual viewport instead of rendering at a fixed
// buffer-pixel size regardless of window size (M10's `CELL` bump was
// the smallest safe lever toward this; this is the rest of it).
// Mouse-event math needs a matching buffer/display scale factor
// whenever the two sizes diverge — same pattern `relCanvas`'s hover
// handler already established (`scale = relCanvas.width / rect.width`).
function canvasEventPoint(ev) {
  const rect = canvas.getBoundingClientRect();
  const cssX = ev.clientX - rect.left, cssY = ev.clientY - rect.top;
  const scale = rect.width > 0 ? canvas.width / rect.width : 1;
  return { cssX, cssY, bufX: cssX * scale, bufY: cssY * scale, scale };
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
    renderPillarCognitionStatus(report.pillar_cognition_status);
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

// C3 "Player <-> Pillar chat" (roadmap Stage III step 10): same on-demand
// request/poll shape as the chronicler above, generalized to any of the
// five cognitive pillars via a select dropdown.

const pillarChatPanel = document.getElementById("pillar-chat-panel");
const pillarChatToggle = document.getElementById("pillar-chat-toggle");
const pillarChatForm = document.getElementById("pillar-chat-form");
const pillarChatSelect = document.getElementById("pillar-chat-select");
const pillarChatInput = document.getElementById("pillar-chat-input");
const pillarChatStatus = document.getElementById("pillar-chat-status");
const pillarChatQuestionEcho = document.getElementById("pillar-chat-question-echo");
const pillarChatAnswer = document.getElementById("pillar-chat-answer");
let pillarChatPollTimer = null;

function renderPillarChat(pillar, data) {
  if (data.pending) {
    pillarChatStatus.textContent = `${pillar} is thinking…`;
  } else {
    pillarChatStatus.textContent = data.tick >= 0 ? `as of tick ${data.tick}` : "";
    pillarChatForm.querySelector("button").disabled = false;
  }
  if (data.question) {
    pillarChatQuestionEcho.textContent = `"${data.question}"`;
    pillarChatQuestionEcho.classList.remove("hidden");
  }
  if (data.answer) pillarChatAnswer.textContent = data.answer;
}

async function loadPillarChat() {
  const pillar = pillarChatSelect.value;
  try {
    renderPillarChat(pillar, await fetchJSON(`/pillar/${pillar}`));
  } catch (e) {
    pillarChatStatus.textContent = `failed to load: ${e.message}`;
  }
}

function pollPillarChatUntilDone(pillar) {
  if (pillarChatPollTimer) clearInterval(pillarChatPollTimer);
  pillarChatPollTimer = setInterval(async () => {
    try {
      const data = await fetchJSON(`/pillar/${pillar}`);
      renderPillarChat(pillar, data);
      if (!data.pending) clearInterval(pillarChatPollTimer);
    } catch (e) {
      clearInterval(pillarChatPollTimer);
    }
  }, 2000);
}

pillarChatToggle.addEventListener("click", () => {
  pillarChatPanel.classList.toggle("hidden");
  pillarChatToggle.classList.toggle("active");
  if (!pillarChatPanel.classList.contains("hidden")) loadPillarChat();
});

pillarChatSelect.addEventListener("change", () => {
  pillarChatQuestionEcho.classList.add("hidden");
  pillarChatAnswer.textContent = "no question asked yet";
  loadPillarChat();
});

pillarChatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = pillarChatInput.value.trim();
  if (!question) return;
  const pillar = pillarChatSelect.value;
  pillarChatForm.querySelector("button").disabled = true;
  pillarChatStatus.textContent = `${pillar} is thinking…`;
  try {
    await fetch(`/ask/${pillar}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question }),
    });
    pillarChatInput.value = "";
    pollPillarChatUntilDone(pillar);
  } catch (e2) {
    pillarChatStatus.textContent = `failed: ${e2.message}`;
    pillarChatForm.querySelector("button").disabled = false;
  }
});

// --- shared "what the world originated" entry renderer, used by both the
// digest's front-page section (below) and the knowledge tree panel (further
// down) — vision doc items 3.1/3.2, docs/VISION-2026-07-22-LIVINGTERRARIUM.md

const KNOWLEDGE_TREE_ICONS = {
  concept: "💡", law: "⚖", custom: "⚖", taboo: "⚖", hypothesis: "🔬",
  nature_belief: "🌲", rule: "⚙", self_tuning: "🎛", composite_entity: "🔗",
  species_variant: "🐾", conclusion: "✅", question: "❓",
};

function renderKnowledgeTreeEntry(row) {
  const icon = KNOWLEDGE_TREE_ICONS[row.type] || "•";
  const lineageBits = [];
  if (row.lineage && row.lineage.evolved_from != null) lineageBits.push(`evolved from #${row.lineage.evolved_from}`);
  if (row.lineage && row.lineage.merged_from) lineageBits.push(`merged from ${row.lineage.merged_from.map((id) => `#${id}`).join(" + ")}`);
  if (row.lineage && row.lineage.supersedes != null) lineageBits.push(`from hypothesis #${row.lineage.supersedes}`);
  if (row.lineage && row.lineage.herd_id != null) lineageBits.push(`herd #${row.lineage.herd_id}`);
  // A8 "Evolutionary Innovation" (roadmap Stage IV step 21): a real
  // generation marker on a descendant concept, same lineage-bits slot.
  if (row.generation) lineageBits.push(`generation ${row.generation}`);
  const lineageText = lineageBits.length ? ` <span class="muted">(${lineageBits.join(", ")})</span>` : "";
  const confText = typeof row.confidence === "number" ? ` <span class="muted">(confidence ${row.confidence.toFixed(2)})</span>` : "";
  // 5.4 "provenance for everything": who/what originated this entry, next
  // to the existing when (tick)/why (text)/lineage fields.
  const whoText = row.who ? ` <span class="muted">— ${row.who}</span>` : "";
  return `<li>${icon} <span class="muted">tick ${row.tick} · ${row.status}</span> <strong>${row.name}</strong>${confText}${whoText} — ${row.text}${lineageText}</li>`;
}

// --- §5 "While you were away" digest (docs/IDEAS-2026-07-EMERGENCE.md) -----
// Same on-demand request/poll shape as the simulation summary above.

const digestPanel = document.getElementById("digest-panel");
const digestToggle = document.getElementById("digest-toggle");
const digestGenerateBtn = document.getElementById("digest-generate");
const digestStatus = document.getElementById("digest-status");
const digestText = document.getElementById("digest-text");
const digestHighlights = document.getElementById("digest-highlights");
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
  // Vision doc item 3.1 ("the morning paper"): the structured front-page
  // section beneath the prose headline — what the world originated for
  // itself during the away window.
  const rows = data.highlights || [];
  digestHighlights.classList.toggle("hidden", rows.length === 0);
  if (rows.length) digestHighlights.innerHTML = rows.map(renderKnowledgeTreeEntry).join("");
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

// --- vision doc item 3.2, docs/VISION-2026-07-22-LIVINGTERRARIUM.md
// ("What the world learned" ledger) ------------------------------------------

const knowledgeTreePanel = document.getElementById("knowledge-tree-panel");
const knowledgeTreeToggle = document.getElementById("knowledge-tree-toggle");
const knowledgeTreeList = document.getElementById("knowledge-tree-list");

// KNOWLEDGE_TREE_ICONS/renderKnowledgeTreeEntry are defined once, above the
// digest section, since item 3.1's front-page section reuses them too.

async function loadKnowledgeTree() {
  knowledgeTreeList.innerHTML = "<li>loading…</li>";
  try {
    const rows = await fetchJSON("/knowledge-tree");
    knowledgeTreeList.innerHTML = rows.length
      ? rows.map(renderKnowledgeTreeEntry).join("")
      : "<li>nothing originated yet</li>";
  } catch (e) {
    knowledgeTreeList.innerHTML = `<li>failed to load: ${e.message}</li>`;
  }
}

knowledgeTreeToggle.addEventListener("click", () => {
  knowledgeTreePanel.classList.toggle("hidden");
  knowledgeTreeToggle.classList.toggle("active");
  if (!knowledgeTreePanel.classList.contains("hidden")) loadKnowledgeTree();
});

// --- vision doc item 1.5 ("A visible law of nature ontology") --------------
// Same knowledge-tree data, filtered to the entry types that read as a
// "rule of this world" (trigger rules, laws/customs/taboos), reformatted
// to foreground trigger->effect and whether it's ever actually fired.

const lawsPanel = document.getElementById("laws-panel");
const lawsToggle = document.getElementById("laws-toggle");
const lawsList = document.getElementById("laws-list");
const LAW_ENTRY_TYPES = new Set(["rule", "law", "custom", "taboo"]);

function renderLawEntry(row) {
  const icon = KNOWLEDGE_TREE_ICONS[row.type] || "⚖";
  if (row.type === "rule") {
    const badge = row.validated
      ? `<span class="muted">(validated${row.fire_count ? `, fired ${row.fire_count}×` : ""})</span>`
      : `<span class="muted">(untested)</span>`;
    const effect = row.hook_type ? ` <span class="muted">→ ${row.hook_type}</span>` : "";
    const secondary = row.secondary_trigger ? ` <span class="muted">(also bound to ${row.secondary_trigger})</span>` : "";
    return `<li>${icon} <strong>if ${row.kind}</strong>${effect}${secondary} ${badge} — ${row.text}</li>`;
  }
  return `<li>${icon} <span class="muted">${row.kind}</span> — ${row.text}</li>`;
}

async function loadLaws() {
  lawsList.innerHTML = "<li>loading…</li>";
  try {
    const rows = (await fetchJSON("/knowledge-tree")).filter((r) => LAW_ENTRY_TYPES.has(r.type));
    lawsList.innerHTML = rows.length ? rows.map(renderLawEntry).join("") : "<li>no laws discovered yet</li>";
  } catch (e) {
    lawsList.innerHTML = `<li>failed to load: ${e.message}</li>`;
  }
}

lawsToggle.addEventListener("click", () => {
  lawsPanel.classList.toggle("hidden");
  lawsToggle.classList.toggle("active");
  if (!lawsPanel.classList.contains("hidden")) loadLaws();
});

// --- vision doc item 3.3 ("Legible causal threads") -------------------------

const causalThreadsPanel = document.getElementById("causal-threads-panel");
const causalThreadsToggle = document.getElementById("causal-threads-toggle");
const causalThreadsList = document.getElementById("causal-threads-list");

function renderCausalThread(thread) {
  const chainText = thread.chain.map((step, i) => (i === 0 ? step : `→ ${step}`)).join(" ");
  return `<li><strong>${thread.subject}</strong> <span class="muted">(tick ${thread.tick})</span><div class="muted" style="margin-top:2px;">${chainText}</div></li>`;
}

async function loadCausalThreads() {
  causalThreadsList.innerHTML = "<li>loading…</li>";
  try {
    const rows = await fetchJSON("/causal-threads");
    causalThreadsList.innerHTML = rows.length
      ? rows.map(renderCausalThread).join("")
      : "<li>nothing traced yet</li>";
  } catch (e) {
    causalThreadsList.innerHTML = `<li>failed to load: ${e.message}</li>`;
  }
}

causalThreadsToggle.addEventListener("click", () => {
  causalThreadsPanel.classList.toggle("hidden");
  causalThreadsToggle.classList.toggle("active");
  if (!causalThreadsPanel.classList.contains("hidden")) loadCausalThreads();
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

// Vision doc item 3.5 ("Time-lapse and the returning eye" — "watch the
// law-book thicken"): knowledge-tree entries are permanent and only ever
// grow (capped-registry eviction aside), so "how many things were known as
// of tick X" is honestly reconstructable from the CURRENT full tree by
// counting entries whose own origination tick is <= X — no per-tick
// history snapshot of the tree itself needed. Fetched once per timeline
// session, not per scrub step.
let timelineKnowledgeTicks = null;

async function loadTimelineKnowledge() {
  try {
    const rows = await fetchJSON("/knowledge-tree");
    timelineKnowledgeTicks = rows.map((r) => r.tick).sort((a, b) => a - b);
  } catch (e) {
    timelineKnowledgeTicks = null;
  }
}

function knowledgeCountAsOf(tick) {
  if (!timelineKnowledgeTicks) return null;
  let lo = 0, hi = timelineKnowledgeTicks.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (timelineKnowledgeTicks[mid] <= tick) lo = mid + 1; else hi = mid;
  }
  return lo;
}

async function loadTimelineIndex() {
  loadTimelineKnowledge(); // fire-and-forget, best-effort
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
    const knowledgeCount = knowledgeCountAsOf(snap.tick);
    timelineSummary.innerHTML = [
      `<li>${s.name || "(unnamed)"} — era: ${s.era}</li>`,
      `<li>population: ${p.total} (avg hunger ${p.avg_hunger.toFixed(2)})</li>`,
      `<li>buildings: ${s.standing} standing, ${s.under_construction} building, ${s.ruined} ruined</li>`,
      `<li>currency ${s.currency.toFixed(1)}, materials ${s.materials.toFixed(1)}</li>`,
      `<li>priority: ${s.current_priority || "(none yet)"}</li>`,
      knowledgeCount != null ? `<li>🌳 ${knowledgeCount} things known so far</li>` : "",
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

// --- live field overlays (explicit user request: "the map should change
// and evolve with the simulation — implement Part A items to be visible
// on the map itself") -------------------------------------------------------
// Four real continuous fields that had backend state but no map
// representation: A11 hydrology (World.hydrology_field.moisture, full
// per-tile grid), soil fertility (FarmGrid.soil_fertility, sparse
// farmed-tiles dict), A1/A20 population density (World.fields,
// coarse 3x3 region grid — the same field `_maybe_favor_uncrowded_
// fission_site` already reads), and A1/A2 disease pressure (World.
// fields, same coarse grid, diffused via ca_operators.diffuse —
// `Population._maybe_outbreak` reads it to weight where the next
// spontaneous case is more likely to appear). A cycling toggle rather
// than four separate always-on overlays: all four are DENSE (every
// tile/region has a value, unlike the sparse scar overlays which are
// naturally faint/rare) — showing them all at once would fight the
// map's own readability, the same reasoning the Observatory UI
// direction already applies to the details panel.
const FIELD_OVERLAY_MODES = ["off", "moisture", "soil_fertility", "population_density", "disease_pressure", "pollution", "traffic", "scarcity"];
const FIELD_OVERLAY_LABELS = {
  off: "off", moisture: "soil moisture", soil_fertility: "soil fertility",
  population_density: "population density", disease_pressure: "disease pressure",
  pollution: "pollution", traffic: "traffic", scarcity: "economic scarcity",
};
let fieldOverlayMode = "off";
const fieldCanvas = document.getElementById("field-canvas");
const fieldCtx = fieldCanvas.getContext("2d");
const fieldOverlayToggle = document.getElementById("field-overlay-toggle");

// M6/M7 "The Living Map": each mode's legend mirrors its own real color
// mapping in `renderFieldOverlay` below exactly — the gradient bar is
// generated live from the SAME `FIELD_COLOR_STOPS` array the overlay
// itself paints from (see `stopsToCssGradient`, defined further down),
// so the two can never silently drift apart. Only the plain-language
// low/high labels a player would actually ask ("where can I farm?" ->
// fertility; "where should I irrigate?" -> moisture) live here.
const FIELD_LEGEND_LABELS = {
  moisture: { min: "dry", max: "saturated" },
  soil_fertility: { min: "depleted", max: "rich" },
  population_density: { min: "empty", max: "crowded" },
  disease_pressure: { min: "low risk", max: "high risk" },
  pollution: { min: "clean", max: "fouled" },
  traffic: { min: "quiet", max: "busy" },
  scarcity: { min: "abundant", max: "struggling" },
};
const fieldLegend = document.getElementById("field-legend");
const fieldLegendTitle = document.getElementById("field-legend-title");
const fieldLegendBar = document.getElementById("field-legend-bar");
const fieldLegendMin = document.getElementById("field-legend-min");
const fieldLegendMax = document.getElementById("field-legend-max");
const fieldLegendPeak = document.getElementById("field-legend-peak");
const fieldLegendThreshold = document.getElementById("field-legend-threshold");

function updateFieldLegend() {
  const labels = FIELD_LEGEND_LABELS[fieldOverlayMode];
  fieldLegend.classList.toggle("hidden", !labels);
  if (!labels) return;
  fieldLegendTitle.textContent = FIELD_OVERLAY_LABELS[fieldOverlayMode];
  fieldLegendBar.style.background = stopsToCssGradient(FIELD_COLOR_STOPS[fieldOverlayMode]);
  fieldLegendMin.textContent = labels.min;
  fieldLegendMax.textContent = labels.max;
  if (fieldHotspotReading) {
    fieldLegendPeak.textContent = `hotspot at (${fieldHotspotReading.x}, ${fieldHotspotReading.y})`;
    fieldLegendPeak.classList.remove("hidden");
  } else {
    fieldLegendPeak.classList.add("hidden");
  }
  // "Thresholds" — only moisture has a real backend-consumed cutoff
  // worth a contour line (see `drawFieldContour`'s own docstring for
  // why the other three modes deliberately don't get one).
  if (fieldOverlayMode === "moisture") {
    fieldLegendThreshold.textContent = `⎯ line: wetland-forming threshold (${MOISTURE_WETLAND_THRESHOLD})`;
    fieldLegendThreshold.classList.remove("hidden");
  } else {
    fieldLegendThreshold.classList.add("hidden");
  }
}

fieldOverlayToggle.addEventListener("click", () => {
  const idx = FIELD_OVERLAY_MODES.indexOf(fieldOverlayMode);
  fieldOverlayMode = FIELD_OVERLAY_MODES[(idx + 1) % FIELD_OVERLAY_MODES.length];
  fieldOverlayToggle.textContent = `🗺️ fields: ${FIELD_OVERLAY_LABELS[fieldOverlayMode]}`;
  fieldOverlayToggle.classList.toggle("active", fieldOverlayMode !== "off");
  updateFieldLegend();
  renderFieldOverlay();
});

// M6/M7 "The Living Map," second slice: true multi-stop gradients (not
// flat single-hue alpha) plus a hotspot marker on the field canvas.
// Each mode's stops are RGB triples at evenly-spaced positions across
// the real 0..1 value range — `FIELD_LEGEND`'s CSS gradients below are
// generated from these SAME arrays (`stopsToCssGradient`), so the
// legend can never silently drift out of sync with what's actually
// painted, the discipline the v1.34.30 legend slice already
// established for the flat-alpha version.
const FIELD_COLOR_STOPS = {
  // Dry ground reads warm/parched (tan), a well-watered tile shifts
  // through green toward a saturated blue — the same low-to-high
  // story a real soil-moisture map tells.
  moisture: [[150, 120, 70], [110, 150, 95], [50, 110, 190]],
  // Bidirectional around the real midpoint (0.5): depleted reads as a
  // tired red-amber, healthy midground a neutral tan, thriving a rich
  // green — three real stops instead of two independent single-hue
  // alpha ramps meeting at a hard edge.
  soil_fertility: [[190, 80, 60], [150, 140, 110], [70, 170, 80]],
  // A conventional "heat" ramp (pale -> orange -> red) — crowded reads
  // as visually hot, matching every reference convention this item
  // names (Cities: Skylines/Timberborn density overlays).
  population_density: [[255, 225, 140], [230, 120, 60], [200, 40, 55]],
  // Pale sickly yellow-green through orange to a danger red — distinct
  // hue family from population density's pink-to-red ramp so the two
  // coarse-region overlays never read as the same signal.
  disease_pressure: [[210, 220, 130], [225, 140, 60], [200, 45, 45]],
  // Clean reads as a neutral pale grey-green, fouled shifts through a
  // sickly olive toward a dark industrial smog purple-grey — distinct
  // from every other mode's hue family (no red/orange), since this is
  // the one field whose story is "man-made," not organic/biological.
  pollution: [[210, 215, 200], [150, 150, 90], [70, 60, 75]],
  // A cool, energetic blue-to-cyan-to-white ramp — reads as "activity/
  // motion" rather than any of the danger/organic hue families the
  // other modes use, since traffic is neutral (neither good nor bad
  // on its own, unlike pollution/disease).
  traffic: [[60, 70, 120], [70, 150, 200], [190, 230, 240]],
  // A4 "economy -> resource/price fields that flow" (Tier 1). Abundant
  // reads as a calm, prosperous green; struggling shifts through a
  // dull amber toward a stark warning red — a "want" ramp, deliberately
  // distinct from disease_pressure's pink-orange-red hue family since
  // this is economic want, not biological/danger risk.
  scarcity: [[80, 170, 110], [200, 175, 90], [190, 60, 50]],
};

function lerpColorStops(stops, t) {
  const clamped = Math.max(0, Math.min(1, t));
  const segments = stops.length - 1;
  const pos = clamped * segments;
  const i = Math.min(segments - 1, Math.floor(pos));
  const frac = pos - i;
  const a = stops[i], b = stops[i + 1];
  return [
    Math.round(a[0] + (b[0] - a[0]) * frac),
    Math.round(a[1] + (b[1] - a[1]) * frac),
    Math.round(a[2] + (b[2] - a[2]) * frac),
  ];
}

function stopsToCssGradient(stops) {
  const n = stops.length - 1;
  const parts = stops.map((s, i) => `rgb(${s[0]},${s[1]},${s[2]}) ${Math.round((i / n) * 100)}%`);
  return `linear-gradient(90deg, ${parts.join(", ")})`;
}

// Below this value a field-mode's peak is treated as "nothing notable
// yet" (an all-zero disease_pressure field shouldn't get a hotspot
// marker just because SOME cell is technically the maximum of a flat
// zero array).
const FIELD_HOTSPOT_MIN_VALUE = 0.12;

function paintFieldCell(mode, x, y, w, h, v, alphaFn) {
  const [r, g, b] = lerpColorStops(FIELD_COLOR_STOPS[mode], v);
  fieldCtx.fillStyle = `rgba(${r},${g},${b},${alphaFn(v).toFixed(3)})`;
  fieldCtx.fillRect(x, y, w, h);
}

function paintFieldHotspot(mode, hotspot) {
  if (!hotspot || hotspot.value < FIELD_HOTSPOT_MIN_VALUE) {
    fieldHotspotReading = null;
    return;
  }
  fieldHotspotReading = hotspot;
  const cx = hotspot.x * CELL + hotspot.w / 2, cy = hotspot.y * CELL + hotspot.h / 2;
  const r = Math.max(CELL * 0.8, 8);
  fieldCtx.save();
  fieldCtx.strokeStyle = "rgba(255,255,255,0.9)";
  fieldCtx.lineWidth = 2;
  fieldCtx.beginPath();
  fieldCtx.arc(cx, cy, r, 0, Math.PI * 2);
  fieldCtx.stroke();
  fieldCtx.beginPath();
  fieldCtx.arc(cx, cy, 2, 0, Math.PI * 2);
  fieldCtx.fillStyle = "rgba(255,255,255,0.95)";
  fieldCtx.fill();
  fieldCtx.restore();
}

let fieldHotspotReading = null;

// M6/M7 "The Living Map," "thresholds" — deliberately NOT built for
// every mode. Audited each field for a real backend-CONSUMED cutoff
// (not an arbitrary aesthetic line) before drawing anything:
// `MIGRANT_DENSITY_DAMPENING`/`OUTBREAK_DISEASE_PRESSURE_WEIGHT` are
// both continuous multipliers with no qualitative value-domain
// boundary; `SOIL_FERTILITY_MIN` is an asymptotic floor, not a
// decision line. Moisture is the one mode with a genuine two-sided
// mechanical threshold — `hydrology.WETLAND_FORM_MOISTURE_THRESHOLD`
// — a tile sustained above this line can turn into a real different
// biome (M4, already shipped). Drawing a contour anywhere else would
// be exactly the "raw tint a player has to guess the meaning of" this
// vision doc's own worked examples warn against.
const MOISTURE_WETLAND_THRESHOLD = 0.75;

function drawFieldContour(grid, threshold, color) {
  fieldCtx.save();
  fieldCtx.strokeStyle = color;
  fieldCtx.lineWidth = Math.max(1.5, CELL * 0.12);
  fieldCtx.beginPath();
  const h = grid.length, w = grid[0] ? grid[0].length : 0;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const v = grid[y][x];
      // A right or bottom neighbor crossing the threshold means the
      // real isoline passes through the shared edge — draw it there,
      // which naturally traces the field's own contour without a full
      // marching-squares implementation (one segment per crossing is
      // enough at this map resolution to read as a clean boundary).
      if (x + 1 < w) {
        const vr = grid[y][x + 1];
        if ((v >= threshold) !== (vr >= threshold)) {
          const ex = (x + 1) * CELL;
          fieldCtx.moveTo(ex, y * CELL);
          fieldCtx.lineTo(ex, (y + 1) * CELL);
        }
      }
      if (y + 1 < h) {
        const vb = grid[y + 1][x];
        if ((v >= threshold) !== (vb >= threshold)) {
          const ey = (y + 1) * CELL;
          fieldCtx.moveTo(x * CELL, ey);
          fieldCtx.lineTo((x + 1) * CELL, ey);
        }
      }
    }
  }
  fieldCtx.stroke();
  fieldCtx.restore();
}

function renderFieldOverlay() {
  if (!terrain || fieldCanvas.width === 0) return;
  fieldCtx.clearRect(0, 0, fieldCanvas.width, fieldCanvas.height);
  fieldHotspotReading = null;
  if (fieldOverlayMode === "off") { updateFieldLegend(); return; }
  let peak = null;
  if (fieldOverlayMode === "moisture") {
    const grid = terrain.moisture;
    if (!grid || !grid.length) return;
    for (let y = 0; y < grid.length; y++) {
      for (let x = 0; x < grid[y].length; x++) {
        const v = grid[y][x];
        paintFieldCell("moisture", x * CELL, y * CELL, CELL, CELL, v, (v) => v * 0.4);
        if (!peak || v > peak.value) peak = { x, y, w: CELL, h: CELL, value: v };
      }
    }
    drawFieldContour(grid, MOISTURE_WETLAND_THRESHOLD, "rgba(255,255,255,0.55)");
  } else if (fieldOverlayMode === "soil_fertility") {
    const sf = terrain.soil_fertility;
    if (!sf) return;
    for (const key in sf) {
      const v = sf[key];
      const [xs, ys] = key.split(":");
      const x = parseInt(xs, 10), y = parseInt(ys, 10);
      // Distance from the neutral midpoint (0.5) drives alpha in both
      // directions — a tile can be a notable LOW just as easily as a
      // notable high, so the hotspot below tracks whichever extreme is
      // furthest from neutral, not just the raw maximum.
      paintFieldCell("soil_fertility", x * CELL, y * CELL, CELL, CELL, v, (v) => Math.abs(v - 0.5) * 1.3);
      const extremity = Math.abs(v - 0.5);
      if (!peak || extremity > peak.value) peak = { x, y, w: CELL, h: CELL, value: extremity };
    }
  } else if (fieldOverlayMode === "population_density") {
    const grid = terrain.population_density;
    if (!grid || !grid.length) return;
    const regionW = Math.ceil(terrain.width / grid[0].length);
    const regionH = Math.ceil(terrain.height / grid.length);
    for (let ry = 0; ry < grid.length; ry++) {
      for (let rx = 0; rx < grid[ry].length; rx++) {
        const v = grid[ry][rx];
        if (!(v > 0)) continue;
        paintFieldCell(
          "population_density", rx * regionW * CELL, ry * regionH * CELL, regionW * CELL, regionH * CELL,
          v, (v) => v * 0.35,
        );
        if (!peak || v > peak.value) peak = { x: rx, y: ry, w: regionW * CELL, h: regionH * CELL, value: v };
      }
    }
  } else if (fieldOverlayMode === "disease_pressure") {
    const grid = terrain.disease_pressure;
    if (!grid || !grid.length) return;
    const regionW = Math.ceil(terrain.width / grid[0].length);
    const regionH = Math.ceil(terrain.height / grid.length);
    for (let ry = 0; ry < grid.length; ry++) {
      for (let rx = 0; rx < grid[ry].length; rx++) {
        const v = grid[ry][rx];
        if (!(v > 0)) continue;
        paintFieldCell(
          "disease_pressure", rx * regionW * CELL, ry * regionH * CELL, regionW * CELL, regionH * CELL,
          v, (v) => v * 0.5,
        );
        if (!peak || v > peak.value) peak = { x: rx, y: ry, w: regionW * CELL, h: regionH * CELL, value: v };
      }
    }
  } else if (fieldOverlayMode === "pollution") {
    const grid = terrain.pollution;
    if (!grid || !grid.length) return;
    const regionW = Math.ceil(terrain.width / grid[0].length);
    const regionH = Math.ceil(terrain.height / grid.length);
    for (let ry = 0; ry < grid.length; ry++) {
      for (let rx = 0; rx < grid[ry].length; rx++) {
        const v = grid[ry][rx];
        if (!(v > 0)) continue;
        paintFieldCell(
          "pollution", rx * regionW * CELL, ry * regionH * CELL, regionW * CELL, regionH * CELL,
          v, (v) => v * 0.45,
        );
        if (!peak || v > peak.value) peak = { x: rx, y: ry, w: regionW * CELL, h: regionH * CELL, value: v };
      }
    }
  } else if (fieldOverlayMode === "traffic") {
    const grid = terrain.traffic;
    if (!grid || !grid.length) return;
    const regionW = Math.ceil(terrain.width / grid[0].length);
    const regionH = Math.ceil(terrain.height / grid.length);
    for (let ry = 0; ry < grid.length; ry++) {
      for (let rx = 0; rx < grid[ry].length; rx++) {
        const v = grid[ry][rx];
        if (!(v > 0)) continue;
        paintFieldCell(
          "traffic", rx * regionW * CELL, ry * regionH * CELL, regionW * CELL, regionH * CELL,
          v, (v) => v * 0.4,
        );
        if (!peak || v > peak.value) peak = { x: rx, y: ry, w: regionW * CELL, h: regionH * CELL, value: v };
      }
    }
  } else if (fieldOverlayMode === "scarcity") {
    const grid = terrain.scarcity;
    if (!grid || !grid.length) return;
    const regionW = Math.ceil(terrain.width / grid[0].length);
    const regionH = Math.ceil(terrain.height / grid.length);
    for (let ry = 0; ry < grid.length; ry++) {
      for (let rx = 0; rx < grid[ry].length; rx++) {
        const v = grid[ry][rx];
        if (!(v > 0)) continue;
        paintFieldCell(
          "scarcity", rx * regionW * CELL, ry * regionH * CELL, regionW * CELL, regionH * CELL,
          v, (v) => v * 0.4,
        );
        if (!peak || v > peak.value) peak = { x: rx, y: ry, w: regionW * CELL, h: regionH * CELL, value: v };
      }
    }
  }
  paintFieldHotspot(fieldOverlayMode, peak);
  updateFieldLegend();
}

// Moisture/soil_fertility/population_density resync weekly server-side
// (see `SimulationEngine._maybe_broadcast`'s docstring) but that
// happens on no life-event category the existing `refreshTerrainIfChanged`
// watches for — a plain periodic re-fetch here is simpler than teaching
// the frontend about calendar boundaries, and terrain is a single cheap
// GET. Every 20s regardless of overlay mode, so mining/disaster/ritual/
// ruin scars also stay fresher as a side effect.
let fieldRefreshInFlight = false;
setInterval(async () => {
  if (fieldRefreshInFlight || !terrain) return;
  fieldRefreshInFlight = true;
  try {
    terrain = await fetchJSON("/terrain");
    drawStaticTerrain();
  } catch (e) {
    // non-fatal — retried on the next interval tick
  } finally {
    fieldRefreshInFlight = false;
  }
}, 20000);

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

// Phase 3.D "permanent landscape scars from disasters" (docs/VISION-2026-07-21-
// SELFEVOLVING.md): same overlay shape as paintMiningScars — an ashen/scoured tint
// distinct from mining's dark pit color, so the two read as different phenomena.
function paintDisasterScars(sctx, scars) {
  if (!scars) return;
  for (const key in scars) {
    const intensity = scars[key];
    if (!(intensity > 0)) continue;
    const [xs, ys] = key.split(":");
    const x = parseInt(xs, 10), y = parseInt(ys, 10);
    sctx.fillStyle = `rgba(60,50,45,${(0.15 + intensity * 0.4).toFixed(3)})`;
    sctx.fillRect(x * CELL, y * CELL, CELL, CELL);
    sctx.strokeStyle = `rgba(20,15,10,${(0.2 + intensity * 0.3).toFixed(3)})`;
    sctx.lineWidth = Math.max(1, CELL * 0.06);
    sctx.strokeRect(x * CELL + 1, y * CELL + 1, CELL - 2, CELL - 2);
  }
}

// A19 "Persistent spatial memory," first slice: a warm golden glow on a
// tile that has accumulated ritual significance — distinct from the two
// scar overlays above (this is a place gaining character FOR something,
// not a mark of damage).
function paintRitualActivity(sctx, activity) {
  if (!activity) return;
  for (const key in activity) {
    const intensity = activity[key];
    if (!(intensity > 0)) continue;
    const [xs, ys] = key.split(":");
    const x = parseInt(xs, 10), y = parseInt(ys, 10);
    sctx.fillStyle = `rgba(220,180,80,${(0.12 + intensity * 0.3).toFixed(3)})`;
    sctx.fillRect(x * CELL, y * CELL, CELL, CELL);
  }
}

// A3 "Procedural generation as continuous runtime," first slice: a pale,
// crumbled-stone tint left at a fully-reclaimed building's former site —
// distinct from every other overlay, a mark of what the land WAS, not
// current damage (mining/disaster) or current significance (ritual).
function paintRuinScars(sctx, scars) {
  if (!scars) return;
  for (const key in scars) {
    const intensity = scars[key];
    if (!(intensity > 0)) continue;
    const [xs, ys] = key.split(":");
    const x = parseInt(xs, 10), y = parseInt(ys, 10);
    sctx.fillStyle = `rgba(160,155,145,${(0.15 + intensity * 0.35).toFixed(3)})`;
    sctx.fillRect(x * CELL, y * CELL, CELL, CELL);
    sctx.strokeStyle = `rgba(110,105,95,${(0.2 + intensity * 0.25).toFixed(3)})`;
    sctx.lineWidth = Math.max(1, CELL * 0.05);
    sctx.strokeRect(x * CELL + 1, y * CELL + 1, CELL - 2, CELL - 2);
  }
}

// M1/M9 "The Living Map": a faint worn-earth streak left where an
// established road once ran before travel moved elsewhere — distinct
// from a currently-standing road's own drawn line (see the "Path"
// click-inspector section) and from `paintRuinScars`' stone tint.
function paintRoadScars(sctx, scars) {
  if (!scars) return;
  for (const key in scars) {
    const intensity = scars[key];
    if (!(intensity > 0)) continue;
    const [xs, ys] = key.split(":");
    const x = parseInt(xs, 10), y = parseInt(ys, 10);
    sctx.fillStyle = `rgba(150,130,95,${(0.1 + intensity * 0.25).toFixed(3)})`;
    sctx.fillRect(x * CELL, y * CELL, CELL, CELL);
  }
}

// M4 "The Living Map": a faint worn path where grazer herds have
// repeatedly reused the same crossing — distinct color from a road
// bed (`paintRoadScars`, human-worn/straighter) since this is animal
// traffic, not civilization's footprint.
function paintMigrationTrails(sctx, trails) {
  if (!trails) return;
  for (const key in trails) {
    const intensity = trails[key];
    if (!(intensity > 0)) continue;
    const [xs, ys] = key.split(":");
    const x = parseInt(xs, 10), y = parseInt(ys, 10);
    sctx.fillStyle = `rgba(120,140,80,${(0.08 + intensity * 0.22).toFixed(3)})`;
    sctx.fillRect(x * CELL, y * CELL, CELL, CELL);
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
  paintDisasterScars(sctx, terrain.disaster_scars);
  paintRitualActivity(sctx, terrain.ritual_activity);
  paintRuinScars(sctx, terrain.ruin_scars);
  paintRoadScars(sctx, terrain.road_scars);
  paintMigrationTrails(sctx, terrain.migration_trails);
  canvas.width = staticCanvas.width;
  canvas.height = staticCanvas.height;
  weatherCanvas.width = staticCanvas.width;
  weatherCanvas.height = staticCanvas.height;
  fieldCanvas.width = staticCanvas.width;
  fieldCanvas.height = staticCanvas.height;
  renderFieldOverlay();
  resizeCanvasDisplay();
}

// Responsive-canvas redesign: shrinks (rarely grows) the map's CSS
// display size to fit the actual viewport, independent of the drawing
// buffer set above — a large map no longer forces the page to scroll,
// a small map no longer sits as a tiny fixed block regardless of
// window size. Bounded both directions: MIN keeps a huge map from
// shrinking past readability, MAX keeps a small map from blowing up
// into blurry/oversized tiles (`image-rendering: pixelated` keeps
// whichever scale it lands on crisp, not smeared).
const MAP_DISPLAY_MIN_SCALE = 0.3;
const MAP_DISPLAY_MAX_SCALE = 1.5;

function resizeCanvasDisplay() {
  if (!staticCanvas) return;
  const panel = document.getElementById("map-panel");
  if (!panel) return;
  const bufferW = staticCanvas.width, bufferH = staticCanvas.height;
  if (!bufferW || !bufferH) return;
  const rect = panel.getBoundingClientRect();
  const availW = Math.max(240, window.innerWidth - rect.left - 24);
  const availH = Math.max(240, window.innerHeight - rect.top - 24);
  let scale = Math.min(availW / bufferW, availH / bufferH);
  scale = Math.max(MAP_DISPLAY_MIN_SCALE, Math.min(MAP_DISPLAY_MAX_SCALE, scale));
  const displayW = Math.round(bufferW * scale);
  const displayH = Math.round(bufferH * scale);
  for (const el of [canvas, weatherCanvas, fieldCanvas]) {
    el.style.width = `${displayW}px`;
    el.style.height = `${displayH}px`;
  }
}

let mapResizeRAF = null;
window.addEventListener("resize", () => {
  if (mapResizeRAF) cancelAnimationFrame(mapResizeRAF);
  mapResizeRAF = requestAnimationFrame(resizeCanvasDisplay);
});

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

  const architectureStyles = latest.architecture_styles || {};
  for (const b of latest.buildings) {
    ctx.fillStyle = BUILDING_COLORS[b.kind] || "#aaa";
    ctx.globalAlpha = b.stage === "under_construction" ? 0.45 : b.stage === "ruined" ? 0.35 : 1.0;
    ctx.fillRect(b.x * CELL - 1, b.y * CELL - 1, CELL + 2, CELL + 2);
    ctx.globalAlpha = 1.0;
    const style = architectureStyles[String(b.settlement_id)];
    ctx.strokeStyle = style ? architectureStyleColor(style.concept_id) : "#f5f5f5";
    ctx.lineWidth = style ? 1.6 : 1;
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
    } else if ((a.immune_strength ?? 0.5) < 0.35) {
      // A14 "Layered organism biology" (roadmap Stage IV step 23): a
      // real reading of the continuous immune_strength state — not
      // currently sick/recently-immune, but genuinely run down (low
      // nutrition/rest over time) and visibly more vulnerable. A faint
      // amber ring, distinct from the starving/sick/immune colors
      // above, so this doesn't collide with any of them.
      ctx.beginPath();
      ctx.strokeStyle = "rgba(224, 168, 60, 0.55)";
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
// WHERE it happened). Only fires for `voice_dialogue`/`dialogue_surfaced`
// events, which are logged only for the voice pair's genuine LLM-authored
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
    if (e.category !== "voice_dialogue" && e.category !== "dialogue_surfaced") continue;
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
  const { bufX: px, bufY: py } = canvasEventPoint(ev);
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
  const { cssX: px, cssY: py, bufX, bufY, scale } = canvasEventPoint(ev);
  if (panState) {
    const dx = ev.clientX - panState.startX, dy = ev.clientY - panState.startY;
    if (panState.moved || Math.hypot(dx, dy) > 4) {
      panState.moved = true;
      stopFollowing(); // a manual pan takes the camera back
      // dx/dy are CSS pixels; view.x/y live in buffer-pixel space, so a
      // drag must scale up by the same factor a shrunk/enlarged display
      // size introduced (responsive-canvas redesign) to keep the point
      // under the cursor pinned while dragging.
      view.x = panState.viewX + dx * scale;
      view.y = panState.viewY + dy * scale;
      clampView();
      tooltip.classList.add("hidden");
      return;
    }
  }
  const { gx, gy } = screenToGrid(bufX, bufY);
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
    const style = latest.architecture_styles && latest.architecture_styles[String(b.settlement_id)];
    const styleText = style ? `<br><span class="muted">built in the "${style.name}" style</span>` : "";
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
        (b.stored_food ? `<br>keeps a store of food` : "") +
        styleText;
      return;
    }
    tooltip.innerHTML =
      `<b>${b.kind}</b> (${b.stage})<br>` +
      `condition ${pct}%` +
      (b.stage === "under_construction" ? ` · progress ${Math.round((b.progress || 0) * 100)}%` : "") +
      (b.stored_food ? `<br>stored food ${b.stored_food.toFixed(1)}` : "") +
      styleText;
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
  const { bufX, bufY } = canvasEventPoint(ev);
  const { gx, gy } = screenToGrid(bufX, bufY);
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
  // A15 "Genetic inheritance" (roadmap Stage IV step 22): a real,
  // plain-language reading of the heritable genome behind those traits
  // — mixed heritage (two notably different alleles) reads as a
  // recognizable "takes after both sides" fact, not raw allele numbers.
  const genome = agent.genome || {};
  const mixedTraits = Object.entries(genome)
    .filter(([, pair]) => Array.isArray(pair) && Math.abs(pair[0] - pair[1]) >= 0.4)
    .map(([trait]) => trait);
  const genomeHtml = mixedTraits.length
    ? `<div class="muted">carries a mixed inheritance in ${mixedTraits.join(", ")}</div>`
    : "";
  // A14 "Layered organism biology" (roadmap Stage IV step 23): a
  // plain-language reading of the continuous immune_strength state —
  // rises with good nutrition/rest, falls under hardship or while
  // actively fighting an infection.
  const immuneStrength = agent.immune_strength ?? 0.5;
  const immuneLabel = immuneStrength >= 0.65 ? "robust" : immuneStrength <= 0.35 ? "run down" : "steady";
  const immuneHtml = `<div class="muted">immune constitution: ${immuneLabel} (${immuneStrength.toFixed(2)})</div>`;
  // A14 "Layered organism biology," second slice: a plain-language
  // reading of the continuous stress state — rises with fear/grief,
  // hunger crisis, sickness, or a hardened feud; eases as those pass.
  const stress = agent.stress ?? 0.0;
  const stressLabel = stress >= 0.6 ? "under real strain" : stress >= 0.25 ? "on edge" : "at ease";
  const stressHtml = `<div class="muted">stress: ${stressLabel} (${stress.toFixed(2)})</div>`;
  // A14 "Layered organism biology," third slice: a plain-language
  // reading of the continuous injury state — set by surviving a
  // predator attack, heals gradually with rest and food.
  const injury = agent.injury ?? 0.0;
  const injuryHtml = injury > 0.02
    ? `<div class="muted">injury: ${injury >= 0.5 ? "badly hurt" : "healing"} (${injury.toFixed(2)})</div>`
    : "";
  // A14 "Layered organism biology," fourth slice: a plain-language
  // reading of the continuous development accumulator — grows from
  // birth toward 1.0, faster when well-fed, slower under chronic
  // hunger. Only shown while still growing; a fully-grown adult
  // (>= 1.0) shows nothing, same "don't clutter with a settled fact"
  // treatment injury's healthy-agent case gets.
  const development = agent.development ?? 1.0;
  const developmentHtml = development < 1.0
    ? `<div class="muted">still growing (development ${development.toFixed(2)})</div>`
    : "";
  // A14 "Layered organism biology," fifth slice: a plain-language
  // reading of the derived fertility curve — rises after maturity,
  // plateaus, then gradually declines with age. Shown only once
  // mature (fertility is a real 0 before that, same "not yet
  // relevant" treatment as injury/development's conditionals).
  const fertility = agent.fertility ?? 0.0;
  const fertilityLabel = fertility >= 0.75 ? "in their prime years" : fertility >= 0.3 ? "past their prime" : "well past childbearing years";
  const fertilityHtml = fertility > 0.0
    ? `<div class="muted">${fertilityLabel} (fertility ${fertility.toFixed(2)})</div>`
    : "";
  // A14 "Layered organism biology," sixth and final slice: a plain-
  // language reading of the chronic sleep_debt state — distinct from
  // momentary energy, this only rises under sustained rest deprivation.
  // Shown only once it's actually accumulated (same "don't clutter
  // with a settled fact" treatment injury/development's conditionals
  // use).
  const sleepDebt = agent.sleep_debt ?? 0.0;
  const sleepDebtLabel = sleepDebt >= 0.5 ? "chronically sleep-deprived" : "under-rested";
  const sleepDebtHtml = sleepDebt > 0.05
    ? `<div class="muted">${sleepDebtLabel} (sleep debt ${sleepDebt.toFixed(2)})</div>`
    : "";
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
    <div class="npc-subtitle">${agent.state}, age ${agent.age_ticks}${agent.occupation ? ` · ${agent.occupation.charAt(0).toUpperCase() + agent.occupation.slice(1)}` : ""}</div>
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
      ${genomeHtml}
      ${immuneHtml}
      ${stressHtml}
      ${injuryHtml}
      ${developmentHtml}
      ${fertilityHtml}
      ${sleepDebtHtml}
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
  if ((agent.immune_strength ?? 0.5) < 0.35) return "healthy, but run down";
  return "healthy";
}

// --- building / bare-tile click inspector (v0.64.0 UI backlog) ---------------
// Parity with the NPC inspector: click anything on the map and get a real
// panel, not just a hover tooltip. Re-rendered per payload like the NPC one.

// A12 "Material science" (roadmap Stage IV step 19): mirrors
// hearthmind/world/materials.py's BUILDING_MATERIALS — same "small
// constant mirrored client-side" precedent as daylight.py's UK_
// DAYLIGHT_HOURS. A kind absent here (SCHOOL/UNIVERSITY/MARKET/
// LIBRARY) has no assigned material there either.
const BUILDING_MATERIAL = {
  hut: "wood", granary: "wood", workshop: "wood", hospital: "stone",
  factory: "metal", shrine: "clay", power_plant: "metal", pasture: "fiber",
  hatchery: "fiber", dock: "wood", oil_rig: "metal", bridge: "stone", forge: "stone",
};

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
    // Vision item 4.1/4.3: a composite entity is a real named place
    // bound to this specific building — show its name/origin story/
    // generated sigil above the ordinary building facts when present.
    const entity = (latest.composite_entities || []).find((e) => e.building_id === b.id);
    const entityHtml = entity
      ? `<div class="npc-section composite-entity-section">
          <div class="composite-entity-sigil">${entity.sigil_svg}</div>
          <h4>${entity.name}</h4>
          <div>${entity.origin_story}</div>
        </div>`
      : "";
    npcContent.innerHTML = `
      <h3>${entity ? entity.name : label}</h3>
      <div class="npc-subtitle">${entity ? `${label.toLowerCase()} — ` : ""}${b.stage.replace(/_/g, " ")} at (${x}, ${y})</div>
      ${entityHtml}
      <div class="npc-section"><h4>Condition</h4>
        <div>${conditionPct}%${b.stage === "under_construction" ? ` · progress ${Math.round((b.progress || 0) * 100)}%` : ""}</div>
      </div>
      ${BUILDING_MATERIAL[b.kind] ? `<div class="npc-section"><h4>Built of</h4><div>${BUILDING_MATERIAL[b.kind]}</div></div>` : ""}
      ${b.descriptor ? `<div class="npc-section"><h4>Character</h4><div>${b.descriptor}</div></div>` : ""}
      ${(() => {
        if (b.kind !== "shrine") return "";
        const activity = (terrain && terrain.ritual_activity && terrain.ritual_activity[`${x}:${y}`]) || 0;
        if (!(activity > 0)) return "";
        const label = activity >= 0.6 ? "a place of deep significance" : activity >= 0.25 ? "a well-worn site of ritual" : "beginning to feel sacred";
        return `<div class="npc-section"><h4>Ritual significance</h4><div>${label} (${activity.toFixed(2)})</div></div>`;
      })()}
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
  const ruin = (terrain && terrain.ruin_scars && terrain.ruin_scars[`${x}:${y}`]) || 0;
  if (ruin > 0) {
    bits.push(`<div class="npc-section"><h4>Ruins</h4><div>a settlement once stood here (${Math.round(ruin * 100)}% still visible)</div></div>`);
  }
  const roadScar = (terrain && terrain.road_scars && terrain.road_scars[`${x}:${y}`]) || 0;
  if (roadScar > 0) {
    bits.push(`<div class="npc-section"><h4>Old road bed</h4><div>a well-worn road once passed here (${Math.round(roadScar * 100)}% still visible)</div></div>`);
  }
  const trail = (terrain && terrain.migration_trails && terrain.migration_trails[`${x}:${y}`]) || 0;
  if (trail > 0) {
    bits.push(`<div class="npc-section"><h4>Migration trail</h4><div>a well-worn wildlife crossing (${Math.round(trail * 100)}% still visible)</div></div>`);
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
      "Occupations",
      (() => {
        const oc = p.occupation_counts || {};
        const entries = Object.entries(oc).sort((a, b) => b[1] - a[1]);
        return entries.length
          ? entries.map(([occ, n]) => `${n} ${occ}${n === 1 ? "" : "s"}`).join(", ")
          : "none assigned yet";
      })(),
      "Real professions (baker/builder/banker/teacher/priest/mayor/fisherman/farmer/shopkeeper/businessman) — a mature, " +
      "healthy villager without one is assigned whichever the settlement currently has fewest of (mayor capped at one). " +
      "Each gates a real mechanical bonus at their matching building (staffing weight, extra income, or a direct yield boost).",
    ],
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
      "Districts",
      (() => {
        const d = s.districts;
        if (!d || !d.count) return "(none yet)";
        return `${d.collectivized_population} in ${d.count} ward${d.count === 1 ? "" : "s"}: ${d.names.join(", ")}`;
      })(),
      "D6 'social scaling': once a settlement's individually-simulated population outgrows what any one villager " +
      "could know, the excess is folded into a district — a collective population figure with its own births/deaths " +
      "and a small materials contribution, no longer a named individual with relationships of their own. New wards " +
      "form once an existing one fills up, so a very large settlement reads as several named quarters, not one " +
      "undifferentiated mass.",
    ],
    [
      "Social hub",
      (() => {
        if (!s.social_hub_agent_id) return "(none yet)";
        const hub = (latest && latest.agents ? latest.agents : []).find((a) => a.id === s.social_hub_agent_id);
        return hub ? hub.name : "(unknown)";
      })(),
      "Who the village's own relationship network actually centers on — the agent with the highest weighted-degree " +
      "centrality in the settlement's relationship graph, recomputed each season. A structural fact, not a title: " +
      "changes when someone else becomes more connected than they are.",
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
      "Layout", s.layout_style ? s.layout_style.charAt(0).toUpperCase() + s.layout_style.slice(1) : "—",
      "A7 (deterministic procedural generation): stable for this settlement's whole lifetime, not LLM-authored — radial settlements grow in rings around their center, linear ones follow an axis, clustered ones huddle tight around whatever's already standing. New buildings' construction sites are scored toward this pattern alongside the existing road/resource adjacency scoring.",
    ],
    [
      "Era", `${s.era} — ${s.era_description}` + (s.era_branch ? ` (leaning ${s.era_branch})` : "") + eraInfrastructureSuffix(s.era_infrastructure),
      "Advances with tech level (inventions) AND real infrastructure — see docs/IDEAS-2026-07-EMERGENCE.md §9: " +
      "a settlement can no longer skip straight to a late era on a lucky invention-roll streak with none of that " +
      "era's own huts/roads/schools/carts standing. Ten-era ladder: stone_age -> bronze_age -> iron_age -> " +
      "classical -> medieval -> renaissance -> industrial -> electrical -> modern -> digital, one step at a time. " +
      "Building toward the next era's requirement also raises invention chance directly. Each era advance, an LLM " +
      "job leans the settlement toward one of a few named branches (industrious, scholarly, devout, mercantile, " +
      "agrarian) that nudges future building odds — two settlements on the same tech path can end up visibly " +
      "different depending on which branch each settled into.",
    ],
    [
      "Education", `${s.education_level.toFixed(2)} / ${s.education_capacity.toFixed(2)}`,
      "Raised by staffed schools/universities (universities contribute 2x). Directly multiplies invention chance: " +
      "1.0 + education_level.",
    ],
    [
      "Exploration",
      `${s.explored_tile_count || 0} tiles charted` + (
        (s.exploration_findings && s.exploration_findings.length)
          ? ` · latest: ${s.exploration_findings[s.exploration_findings.length - 1].description}`
          : ""
      ),
      "Surveyors reveal ground around themselves as they roam beyond the settlement's already-known territory, " +
      "logging notable finds (mineral veins, rich wild-food sites, other settlements) — fed back into where the " +
      "town chooses to expand when it fissions.",
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
      "Historical infrastructure", `${s.forges || 0} forge${(s.forges || 0) === 1 ? "" : "s"}, ${s.libraries || 0} librar${(s.libraries || 0) === 1 ? "y" : "ies"}`,
      "Forges: the bronze_age+ economic building, this era's business before workshop/factory exist. " +
      "Libraries: the classical+ knowledge building, boosts settlement education exactly like a school.",
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
    [
      "Discoverable",
      (() => {
        const settlements = summary.settlements || [];
        const combos = new Set();
        const reactions = new Set();
        settlements.forEach((stl) => {
          const d = stl.discoverable || {};
          (d.combinations || []).forEach((c) => combos.add(c));
          (d.reactions || []).forEach((r) => reactions.add(r));
        });
        const items = [...combos, ...reactions].map((s) => s.replace(/_/g, " "));
        return items.length ? items.join(", ") : "nothing yet";
      })(),
      "What could physically be combined or produced right now, from the affordances and materials of whatever's actually standing (A5/A6/A12/A13) — a real, deterministic reading of the same layer Innovation's own proposals draw on, not a hint at what WILL be invented.",
    ],
    ["Farms", `${f.total} (${f.growing} growing, ${f.ready} ready)`, null],
    [
      "Soil fertility",
      `${((f.avg_soil_fertility ?? 1.0) * 100).toFixed(0)}% average`,
      "Continuous cultivation wears a plot down; resting it (leave it fallow) recovers fertility over time. Sustained wildlife activity near a farmed tile also enriches it — grazing herds and their leavings feed nutrients back into nearby soil, a real (small, capped) bonus on top of ordinary fallow recovery.",
    ],
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
      "Disaster scars",
      (() => {
        const ds = summary.disaster_scars || {};
        return ds.scarred_tiles ? `${ds.scarred_tiles} tiles (avg ${ds.avg_intensity.toFixed(2)})` : "none yet";
      })(),
      "A tile repeatedly caught in a flood or wildfire bears a lasting visible mark (see the map itself) instead of always fully healing — weathers back to nothing if left undisturbed. Cosmetic, not a biome change.",
    ],
    [
      "Ritual sites",
      (() => {
        const ra = summary.ritual_activity || {};
        return ra.sites ? `${ra.sites} site${ra.sites === 1 ? "" : "s"} (avg ${ra.avg_intensity.toFixed(2)})` : "none yet";
      })(),
      "A shrine that has hosted festival gatherings before amplifies the boost of the NEXT one held there — a place's accumulated significance, not just a flat bonus. Fades slowly if left unused.",
    ],
    [
      "Ruins",
      (() => {
        const rs = summary.ruin_scars || {};
        return rs.sites ? `${rs.sites} site${rs.sites === 1 ? "" : "s"} (avg ${rs.avg_intensity.toFixed(2)})` : "none yet";
      })(),
      "A fully-abandoned, fully-decayed building leaves a real mark on the land long after it's gone — by far the slowest of these marks to fade. A new building staked out nearby leans toward a spot with old ruins, \"the village rebuilds on old foundations.\"",
    ],
    [
      "Old roads",
      (() => {
        const rds = summary.road_scars || {};
        return rds.sites ? `${rds.sites} bed${rds.sites === 1 ? "" : "s"} (avg ${rds.avg_intensity.toFixed(2)})` : "none yet";
      })(),
      "A road worn in by real traffic, then abandoned as travel moved elsewhere, leaves a faint old road bed behind instead of vanishing without a trace — fades over about a year if never retraveled. A new building staked out nearby leans toward old travel corridors, a smaller pull than a ruin's.",
    ],
    [
      "Migration trails",
      (() => {
        const mt = summary.migration_trails || {};
        return mt.sites ? `${mt.sites} crossing${mt.sites === 1 ? "" : "s"} (avg ${mt.avg_intensity.toFixed(2)})` : "none yet";
      })(),
      "A grazer herd reusing the same crossing wears a faint trail into the land — and a real trail then draws more herds to reuse it, a genuine feedback loop, not just a cosmetic record. Fades over a couple of months if left unused.",
    ],
    [
      "Wetlands",
      (() => {
        const w = (summary.biome_counts && summary.biome_counts.wetland) || 0;
        return w ? `${w} tile${w === 1 ? "" : "s"}` : "none yet";
      })(),
      "Low ground that stays near-saturated — both surface moisture and groundwater — for months at a stretch genuinely turns to wetland, a real biome (unfarmable, unwalkable, see the map) rather than just a wetter reading. Dries back to open ground if the water table drops.",
    ],
    [
      "Soil moisture",
      (() => {
        const h = summary.hydrology || {};
        const pct = ((h.avg_moisture ?? 0.35) * 100).toFixed(0);
        const gwPct = ((h.avg_groundwater ?? 0.3) * 100).toFixed(0);
        return `${pct}% surface, ${gwPct}% groundwater`;
      })(),
      "A real per-tile water field — rain soaks in, then flows downhill toward low ground, then evaporates, updated weekly. A planted field's yield depends on how wet its own tile actually is, not just soil fertility. " +
      "Groundwater is a separate, slower subsurface reservoir: sustained wet weather infiltrates into it, and it seeps back out during a dry stretch — land that was recently wet resists drying out faster than land that never was, even at the same surface reading right now.",
    ],
    [
      "Erosion",
      (() => {
        const h = summary.hydrology || {};
        const parts = [];
        parts.push(h.tiles_eroded_recorded ? `${h.tiles_eroded_recorded} tiles reshaped` : "no reshaping yet");
        if (h.river_tiles_shifted_recorded) parts.push(`${h.river_tiles_shifted_recorded} riverbed tiles shifted`);
        return parts.join(", ");
      })(),
      "Genuinely wet, flow-carrying land slowly moves a small fraction of its elevation downhill each week — mass-conserving, capped, and gradual, the same \"history becomes physically visible over the long run\" pace as the map's other scar-shaped marks. Occasionally a tile erodes far enough to cross into a different kind of land entirely. Monthly, a river re-walks its own course against the CURRENT (eroded) elevation from its original source — its bed can genuinely migrate over the long run, leaving dry former riverbed behind where it moves away.",
    ],
    [
      "Wildlife",
      `${w.grazer_total} grazers (${w.grazer_herds} herds), ${w.predator_total} predators (${w.predator_packs} packs)`
      + (w.prey_scarce ? " — prey scarce" : w.predator_pressure_ratio > 0.25 ? " — heavy predation" : ""),
      "Grazer herds roam grassland/forest and can be hunted for food; predator packs roam forest/hills and hunt grazers, starving without a kill. A real trophic loop: heavy predation pressure suppresses grazer breeding map-wide, and scarce prey suppresses predator breeding/survival in turn — not just direct per-tile kills.",
    ],
    [
      "The land's own sense",
      (summary.nature_beliefs && summary.nature_beliefs.length)
        ? summary.nature_beliefs.map((b) => b.subject).join(", ")
        : "not yet formed",
      "Nature's Mind (Body/Mind framing): the wilderness's own running, revisable theories about its condition — formed from wildlife pressure, disaster/mining scars, succession, and climate drift, never from what the village believes. Grounded, sometimes wrong, same discipline as any other belief in this world. May also give rise to new ecological concepts (migration routes, symbioses, landscape identities) in the shared ontology.",
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

  const legendsEl = document.getElementById("legends-list");
  if (legendsEl) {
    const legendsList = (s.legends || []).slice().reverse(); // newest first
    setInnerHTMLIfChanged(legendsEl, legendsList.length
      ? legendsList.map((l) => `<li><span class="muted">${(l.subsystem || "").replace(/_/g, " ")}</span> — ${l.legend}</li>`).join("")
      : "<li>no legends yet</li>");
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

  const specializationsEl = document.getElementById("invention-specializations");
  if (specializationsEl) {
    // Post-v1 follow-up: each invention's LLM-chosen category (agricultural/
    // structural/mercantile/general) nudges a small, capped settlement-wide
    // lean toward that category's yield/work-rate/income — this is what makes
    // a specific invention do something specific, not just bump a counter.
    const specs = s.invention_specializations || {};
    const entries = Object.entries(specs).filter(([, v]) => v > 0);
    specializationsEl.title = "Each invention's category (agricultural/structural/mercantile) nudges a small, " +
      "capped settlement-wide bonus to matching yield/work-rate/income — a specific invention now does " +
      "something specific, on top of the flat tech-level bonus every invention already gives.";
    setInnerHTMLIfChanged(specializationsEl, entries.length
      ? entries.map(([cat, v]) => `<li>${cat}: +${Math.round(v * 100)}%</li>`).join("")
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

function renderPillarCognitionStatus(status) {
  const el = document.getElementById("pillar-cognition-content");
  if (!el) return;
  if (!status) {
    el.textContent = "no data yet";
    return;
  }
  const n = status.nature, r = status.reflection;
  el.textContent =
`Nature
--------
Stage: ${n.stage}
Season boundaries observed: ${n.boundaries_observed} / ${n.boundaries_needed_for_first_belief}
Belief formation: ${n.belief_formation}

Reflection
------------
Stage: ${r.stage}
Years observed: ${r.years_observed} / ${r.years_needed_for_first_hypothesis}
Pattern detector: ${r.pattern_detector}
Hypothesis: ${r.hypothesis}`;
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
  // Item 3.6 ("ambient generative presence"): Nature's Mind's own
  // confidence in its strongest current belief adds a little extra
  // "certainty" to the pad's resonance — the land's hidden state, same
  // never-dominant magnitude as every other input here.
  const natureConfidence = (summary.nature_beliefs && summary.nature_beliefs.length)
    ? Math.max(...summary.nature_beliefs.map((b) => b.confidence || 0))
    : 0;

  // Base pitch drops at night, warms (rises) with positive temperament —
  // a small, never-dominant nudge, same magnitude discipline Phase G
  // applies everywhere else it touches a number.
  const baseFreq = 90 + (1 - nightFactor) * 40 + temperament * 15;
  osc1.frequency.linearRampToValueAtTime(baseFreq, now + RAMP);
  osc2.frequency.linearRampToValueAtTime(baseFreq, now + RAMP);
  osc2.detune.linearRampToValueAtTime(6 + wind * 30, now + RAMP);

  // Rain/overcast muffles the pad (lower filter cutoff); clear skies
  // brighten it. Wind adds a little extra openness on top.
  const cutoff = 300 + (1 - precipitation) * 900 + wind * 200 + natureConfidence * 80;
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
// Vision doc item 3.6 ("Ambient generative presence"): a faint seasonal
// color-grade over the map — "feel it darken before winter" without any
// text telling you. Keyed to the same `summary.season` the header
// already surfaces, plus night_factor for a little extra depth at night.
// Deliberately not tied to Phase G's temperament/mood — those stay
// dev-console-only per the ambiguity discipline; season is already
// plainly visible everywhere else, so tinting by it isn't a new leak.
const SEASON_VIGNETTE = {
  winter: "radial-gradient(ellipse at center, transparent 40%, rgba(90,110,140,0.35) 100%)",
  autumn: "radial-gradient(ellipse at center, transparent 45%, rgba(150,100,50,0.28) 100%)",
  spring: "radial-gradient(ellipse at center, transparent 50%, rgba(90,150,90,0.16) 100%)",
  summer: "radial-gradient(ellipse at center, transparent 55%, rgba(200,170,80,0.14) 100%)",
};
const SEASON_VIGNETTE_OPACITY = { winter: 0.35, autumn: 0.25, spring: 0.12, summer: 0.1 };
const seasonVignetteEl = document.getElementById("season-vignette");
let lastVignetteSeason = null;

function updateSeasonVignette(summary) {
  if (!seasonVignetteEl || !summary || !summary.season) return;
  const season = summary.season;
  if (season === lastVignetteSeason) return; // avoid retriggering the CSS transition every tick
  lastVignetteSeason = season;
  const gradient = SEASON_VIGNETTE[season];
  if (!gradient) return;
  seasonVignetteEl.style.background = gradient;
  const nightFactor = summary.night_factor != null ? summary.night_factor : 0;
  const opacity = (SEASON_VIGNETTE_OPACITY[season] || 0.15) * (1 + nightFactor * 0.4);
  seasonVignetteEl.style.opacity = String(Math.min(1, opacity));
}

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

// Vision item 3.4, "the world talks to you" — the front-page counterpart
// to the away-digest: a once-a-day line in Reflection's own voice, read
// straight off the live broadcast (payload.summary.latest_musing), same
// shape as the consciousness indicator below. Only re-renders on a new
// tick so it doesn't visually flicker every broadcast.
const musingLineEl = document.getElementById("musing-line");
const musingTextEl = document.getElementById("musing-text");
let lastMusingTick = null;

function renderMusing(summary) {
  if (!musingLineEl) return;
  const musing = summary.latest_musing;
  if (!musing || !musing.text) {
    musingLineEl.classList.add("hidden");
    return;
  }
  if (musing.tick !== lastMusingTick) {
    lastMusingTick = musing.tick;
    musingTextEl.textContent = musing.text;
  }
  musingLineEl.classList.remove("hidden");
}

function applyPayload(payload) {
  latest = payload;
  renderSettlementChips(payload);
  renderStats(payload.summary);
  renderMusing(payload.summary);
  renderExtinctionBanner(payload.summary);
  if (ambientAudioEnabled) updateAmbientAudio(payload.summary);
  updateSeasonVignette(payload.summary);
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
