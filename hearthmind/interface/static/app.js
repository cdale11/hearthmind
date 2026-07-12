"use strict";

// Hearthmind browser window — read-only, no build step (see docs/DECISIONS.md, F1/F2).
// Terrain is fetched once (it never changes); everything else arrives via
// GET /state (initial paint) and then a WebSocket stream, one message per
// tick, in the exact same shape.

const CELL = 8; // px per terrain tile

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
  hospital: "#e0473c", university: "#2f7fc9", factory: "#5c5c66",
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
  dialogue: { icon: "💬" },
  rumor: { icon: "📣" },
  tradition: { icon: "🎭" },
  invention: { icon: "💡" },
  festival: { icon: "🎉" },
  predator_attack: { icon: "🐺" },
  chronicle: { icon: "📜" },
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
  lake_rose: { icon: "💧" },
  lake_receded: { icon: "🏖️" },
};

// Terrain evolves now (deforestation, reclamation, climate drift), so the
// once-per-boot static canvas can go stale — re-fetch /terrain and redraw
// only on ticks that actually reported a terrain-changing life event,
// rather than polling every tick for a change that's rare by design.
const TERRAIN_CHANGING_CATEGORIES = new Set([
  "terrain_thinned", "terrain_reclaimed", "climate_drift",
  "disaster_flood", "disaster_wildfire", "lake_rose", "lake_receded",
]);
function categoryMeta(category) {
  return CATEGORY_META[category] || (category.endsWith("_migration") ? { icon: "🔧" } : { icon: "•" });
}

let terrain = null;
let latest = null; // last full payload: {summary, life_events, agents, buildings, farms, wildlife, roads, diagnostics}
let staticCanvas = null; // offscreen: biome grid, drawn once

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

async function fetchJSON(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json();
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
  canvas.width = staticCanvas.width;
  canvas.height = staticCanvas.height;
  weatherCanvas.width = staticCanvas.width;
  weatherCanvas.height = staticCanvas.height;
}

function drawFrame() {
  if (!staticCanvas || !latest) return;
  ctx.drawImage(staticCanvas, 0, 0);

  // Roads: worn tiles get a visible dirt-path tint from the very first
  // bit of wear (a 0.35 floor alpha, not scaled from 0), darkening
  // further as they approach "established" — drawn first so farms/
  // buildings/agents sit on top. The old pure `wear * 0.6` scaling made
  // anything below "established" (wear >= 0.5) nearly invisible
  // (alpha ~0.06 at wear 0.1), which read as "roads aren't showing up."
  for (const [x, y, wear] of latest.roads || []) {
    const alpha = wear >= 0.5 ? 0.75 : Math.max(0.35, wear * 1.2);
    ctx.fillStyle = `rgba(196, 148, 58, ${alpha})`;
    ctx.fillRect(x * CELL, y * CELL, CELL, CELL);
  }

  // Wild resource nodes (bushes/mines): small, unobtrusive markers so
  // the map shows what agents are actually foraging/gathering from, not
  // just an aggregate count in a stat tile. Dimmed toward the terrain
  // color as a node depletes, brightening again as it regrows.
  for (const n of latest.resources || []) {
    const cx = n.x * CELL + CELL / 2, cy = n.y * CELL + CELL / 2;
    const fullness = Math.max(0.15, n.amount / (n.kind === "ore" ? 2.0 : 1.0));
    ctx.globalAlpha = 0.4 + fullness * 0.6;
    ctx.beginPath();
    ctx.fillStyle = n.kind === "ore" ? "#9aa0ab" : "#7fbf5a";
    ctx.arc(cx, cy, n.kind === "ore" ? 2.2 : 1.6, 0, Math.PI * 2);
    ctx.fill();
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
  }

  // Vehicles: a small icon-like mark at their build/home tile — carts as
  // an amber square (settlement-wide haul bonus), mounts/automobiles as
  // a diamond (personal, claimed/unclaimed shown via color; automobile
  // gets a distinct steel-blue hue from mount's violet, so era-driven
  // transport progress is visible on the map, not just in stat tiles).
  for (const v of latest.vehicles || []) {
    const cx = v.x * CELL + CELL / 2, cy = v.y * CELL + CELL / 2;
    ctx.globalAlpha = v.stage === "building" ? 0.4 : v.stage === "broken" ? 0.3 : 1.0;
    if (v.kind === "cart") {
      ctx.fillStyle = "#c9863c";
      ctx.fillRect(cx - CELL / 4, cy - CELL / 4, CELL / 2, CELL / 2);
    } else {
      const isAutomobile = v.kind === "automobile";
      const claimedColor = isAutomobile ? "#5b9bd6" : "#a679d6";
      const unclaimedColor = isAutomobile ? "#33546e" : "#6b5580";
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
      ctx.beginPath();
      ctx.fillStyle = "#c94c4c";
      ctx.moveTo(cx, cy - CELL / 2.4);
      ctx.lineTo(cx - CELL / 2.4, cy + CELL / 2.4);
      ctx.lineTo(cx + CELL / 2.4, cy + CELL / 2.4);
      ctx.closePath();
      ctx.fill();
    }
  }

  for (const a of latest.agents) {
    const { px, py } = agentRenderPos(a);
    ctx.beginPath();
    ctx.fillStyle = a.state === "resting" ? "#8894c9" : "#f2f2f2";
    ctx.arc(px, py, CELL / 3, 0, Math.PI * 2);
    ctx.fill();
    if (a.starving_ticks > 0) {
      ctx.strokeStyle = "#e0473c";
      ctx.lineWidth = 1;
      ctx.stroke();
    }
  }
}

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
}

function agentRenderPos(a) {
  const anim = agentAnim.get(a.id);
  if (!anim) return { px: a.x * CELL + CELL / 2, py: a.y * CELL + CELL / 2 };
  const t = Math.min(1, (performance.now() - anim.t0) / anim.dur);
  const gx = anim.fx + (anim.tx - anim.fx) * t;
  const gy = anim.fy + (anim.ty - anim.fy) * t;
  return { px: gx * CELL + CELL / 2, py: gy * CELL + CELL / 2 };
}

function renderLoop() {
  drawFrame();
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

function currentWeatherDetail() {
  return (latest && latest.summary && latest.summary.weather_detail) || null;
}

function spawnWeatherParticles(w) {
  if (!w || weatherCanvas.width === 0) return;
  const target = w.is_snowing
    ? Math.round(w.precipitation * 120)
    : Math.round(w.precipitation * 90);
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

function drawLighting(w) {
  const night = nightFactor(
    latest && latest.summary && latest.summary.clock,
    latest && latest.summary && latest.summary.month,
  );
  const weatherDark = w ? Math.min(1, w.precipitation) * WEATHER_DARKEN_MAX_ALPHA : 0;
  const alpha = Math.min(0.75, night * NIGHT_MAX_ALPHA + weatherDark);
  if (alpha <= 0.01) return;
  weatherCtx.fillStyle = `rgba(4, 6, 16, ${alpha})`;
  weatherCtx.fillRect(0, 0, weatherCanvas.width, weatherCanvas.height);
}

function stepWeatherParticles() {
  const w = currentWeatherDetail();
  weatherCtx.clearRect(0, 0, weatherCanvas.width, weatherCanvas.height);
  drawLighting(w);
  if (!w || (w.precipitation < 0.05 && !w.is_snowing)) {
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

function findAgentAt(px, py) {
  if (!latest) return null;
  const gx = Math.floor(px / CELL), gy = Math.floor(py / CELL);
  for (const a of latest.agents) {
    if (a.x === gx && a.y === gy) return a;
  }
  return null;
}

canvas.addEventListener("mousemove", (ev) => {
  const rect = canvas.getBoundingClientRect();
  const a = findAgentAt(ev.clientX - rect.left, ev.clientY - rect.top);
  if (!a) {
    tooltip.classList.add("hidden");
    return;
  }
  tooltip.classList.remove("hidden");
  tooltip.style.left = `${ev.clientX - rect.left + 12}px`;
  tooltip.style.top = `${ev.clientY - rect.top + 12}px`;
  const lastMemory = a.memories && a.memories.length ? a.memories[a.memories.length - 1] : null;
  tooltip.innerHTML =
    `<b>${a.name}</b> (${a.state}, goal=${a.goal})<br>` +
    `hunger ${a.hunger.toFixed(2)} · energy ${a.energy.toFixed(2)} · age ${a.age_ticks}` +
    (a.goal_reason ? `<br><i>"${a.goal_reason}"</i>` : "") +
    (lastMemory ? `<br><span class="tooltip-memory">${lastMemory}</span>` : "");
});
canvas.addEventListener("mouseleave", () => tooltip.classList.add("hidden"));

function fmtPct(x) { return `${Math.round(x * 100)}%`; }

function renderStats(summary) {
  const p = summary.population, s = summary.settlement, r = summary.resources;
  const f = summary.farms, llm = summary.llm, w = summary.wildlife, rd = summary.roads;
  const c = summary.climate;
  const tiles = [
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
    ["Buildings", `${s.total} (${s.standing} standing, ${s.under_construction} building, ${s.ruined} ruined)`, null],
    [
      "Civic buildings",
      `${s.workshops} workshop${s.workshops === 1 ? "" : "s"}, ${s.schools} school${s.schools === 1 ? "" : "s"}, ` +
      `${s.hospitals} hospital${s.hospitals === 1 ? "" : "s"}, ${s.universities} universit${s.universities === 1 ? "y" : "ies"}` +
      (s.factories ? `, ${s.factories} factor${s.factories === 1 ? "y" : "ies"}` : ""),
      "Workshops generate currency from staffed presence. Schools/universities raise education (shown below), which " +
      "boosts invention chance. Hospitals speed rest recovery on-site and settlement-wide reduce the odds a predator " +
      "attack proves lethal. Factories (era: electrical+) generate currency at double a workshop's rate.",
    ],
    [
      "Era", `${s.era} — ${s.era_description}`,
      "Advances with tech level (inventions): industrial -> electrical -> modern -> digital. Unlocks the FACTORY building kind past 'industrial'.",
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
        : ""),
      "Carts: each ready cart adds 25% to gathered-material haul yield (up to 3 stacked). " +
      "Mounts: an awake agent standing with an unclaimed ready mount claims it and moves ~1.6x faster " +
      "for as long as it stays repaired. Automobiles (era: modern+) work the same way, faster still (~2.2x). " +
      "All wear with use and weather, and break down if neglected.",
    ],
    [
      "Granaries", `${s.granaries} (${s.granary_food.toFixed(1)} / ${s.granary_capacity.toFixed(1)} food)`,
      "Communal food buffer: well-fed agents present at a standing granary deposit surplus; hungry agents withdraw from it before resorting to wild foraging.",
    ],
    [
      "Materials", `${s.materials.toFixed(1)} / ${s.materials_capacity.toFixed(1)}`,
      "Settlement-wide wood/stone stockpile, gathered by GATHER-goal agents from forest/hills. Spent on faster construction and tool-boosted farm plots.",
    ],
    [
      "Currency", `${s.currency.toFixed(1)} / ${s.currency_capacity.toFixed(1)}`,
      "Settlement-wide wealth, earned by selling food/materials surplus that would otherwise be wasted at capacity. Spent on emergency rations when a granary runs dry.",
    ],
    [
      "Tech level", `${s.tech_level} invention${s.tech_level === 1 ? "" : "s"}`,
      "Each invention permanently boosts construction/repair speed and cultivated-food yield (farm harvest, granary stock/withdraw) by 15% — wild foraging is unaffected. Rare: gated by settlement prosperity, rolled once a year.",
    ],
    ["Farms", `${f.total} (${f.growing} growing, ${f.ready} ready)`, null],
    ["Wild resources", `${r.total_nodes} nodes (${r.depleted} depleted)`, "Wild forageable nodes (berries, etc.) — the last-resort food source, behind farms, granaries, and hunting."],
    [
      "Wildlife", `${w.grazer_total} grazers (${w.grazer_herds} herds), ${w.predator_total} predators (${w.predator_packs} packs)`,
      "Grazer herds roam grassland/forest and can be hunted for food; predator packs roam forest/hills and hunt grazers, starving without a kill.",
    ],
    [
      "Roads", `${rd.established_roads} established (${rd.worn_tiles} worn)`,
      "Tiles worn by sustained foot traffic. An established road (wear ≥ 0.5) gives agents standing on it a 1.4x random-walk move-chance bonus.",
    ],
    ["LLM calls", `${llm.calls_total} (${fmtPct(llm.fallback_rate)} fallback)`, null],
    ["NPC dialogue", `${llm.dialogue_total} exchanges, ${llm.rumor_total} rumors`, null],
    [
      "Geography",
      `${(summary.biome_counts || {}).river || 0} river tile${(summary.biome_counts || {}).river === 1 ? "" : "s"}, ` +
      `${(summary.lakes || []).length} lake${(summary.lakes || []).length === 1 ? "" : "s"}`,
      "Rivers are carved once at world creation. Lakes each have their own slowly-changing water level " +
      "(nudged monthly, biased by the climate trend above) that grows or shrinks the shoreline by a tile at a time.",
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
  document.getElementById("stat-grid").innerHTML = tiles
    .map(([label, value, title]) =>
      `<div class="stat-tile"${title ? ` title="${title}"` : ""}><div class="label">${label}</div><div class="value">${value}</div></div>`
    )
    .join("");

  document.getElementById("settlement-name").textContent = s.name || "Hearthmind (unnamed settlement)";
  document.getElementById("clock-line").textContent = `${summary.date} · ${summary.clock} · ${summary.weather}`;

  const beliefsEl = document.getElementById("beliefs-list");
  if (beliefsEl) {
    beliefsEl.innerHTML = s.beliefs && s.beliefs.length
      ? s.beliefs
          .slice()
          .sort((a, b) => b.confidence - a.confidence)
          .map((b) => {
            const revised = b.revision_count > 0 ? ` (revised ${b.revision_count}x)` : "";
            return `<li><b>${b.subject}</b>: ${b.belief} <span class="muted">(confidence ${Math.round(b.confidence * 100)}%${revised})</span></li>`;
          })
          .join("")
      : "<li>none yet — forms and revises over time</li>";
  }

  const traditionsEl = document.getElementById("traditions-list");
  traditionsEl.innerHTML = s.traditions.length
    ? s.traditions.map((t) => `<li>${t}</li>`).join("")
    : "<li>none yet</li>";

  const inventionsEl = document.getElementById("inventions-list");
  if (inventionsEl) {
    inventionsEl.innerHTML = s.inventions.length
      ? s.inventions.map((t) => `<li>${t}</li>`).join("")
      : "<li>none yet</li>";
  }

  const festivalsEl = document.getElementById("festivals-list");
  if (festivalsEl && s.festivals) {
    festivalsEl.innerHTML = s.festivals.length
      ? s.festivals.map((t) => `<li>${t}</li>`).join("")
      : "<li>none yet</li>";
  }

  const brainEl = document.getElementById("town-brain-priority");
  if (brainEl) {
    brainEl.innerHTML = s.current_priority
      ? `Current priority: <b>${s.current_priority}</b><br><span class="muted">${s.priority_rationale}</span>`
      : "No decision yet — the town brain decides once a season, once the village is named.";
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
    el.innerHTML = "<li>nothing built yet</li>";
    return;
  }
  el.innerHTML = rows
    .slice(0, 40)
    .map((r) => {
      const label = r.kind.charAt(0).toUpperCase() + r.kind.slice(1);
      const pct = Math.round(r.condition * 100);
      const statusClass = `infra-condition-${r.status.replace(/\s+/g, "-")}`;
      return (
        `<li><span class="${statusClass}">${label} (${r.x}, ${r.y}): ${r.status} (${pct}%)</span></li>`
      );
    })
    .join("");
}

function renderDevConsole(payload) {
  if (devConsole.classList.contains("hidden")) return;
  devConsoleContent.textContent = JSON.stringify(
    { diagnostics: payload.diagnostics, llm: payload.summary.llm },
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
    const tickPart = e.tick !== undefined ? `<span class="event-tick">[${e.tick}]</span>` : "";
    li.innerHTML = `${tickPart}<span class="event-icon">${meta.icon}</span><span class="event-text">${e.description}</span>`;
    log.prepend(li);
  }
  while (log.children.length > 150) log.removeChild(log.lastChild);
}

async function refreshTerrainIfChanged(events) {
  if (!events || !events.some((e) => TERRAIN_CHANGING_CATEGORIES.has(e.category))) return;
  try {
    terrain = await fetchJSON("/terrain");
    drawStaticTerrain();
  } catch (e) {
    // non-fatal — the map just stays one step behind until the next change
  }
}

function applyPayload(payload) {
  latest = payload;
  renderStats(payload.summary);
  renderInfrastructure(payload.infrastructure);
  updateAgentAnimTargets(payload.agents || []);
  if (payload.diagnostics) renderDevConsole(payload);
  if (payload.life_events && payload.life_events.length) {
    prependEvents(payload.life_events.map((e) => ({ ...e, tick: payload.summary.tick })));
    refreshTerrainIfChanged(payload.life_events);
  }
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
        body: JSON.stringify({ text }),
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

async function boot() {
  terrain = await fetchJSON("/terrain");
  drawStaticTerrain();
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
