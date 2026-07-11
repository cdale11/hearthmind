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
};

const BUILDING_COLORS = { hut: "#c98a3c", granary: "#d9a441" };
const FARM_COLORS = { growing: "#7fae4a", ready: "#e0c34a" };

let terrain = null;
let latest = null; // last full payload: {summary, life_events, agents, buildings, farms}
let staticCanvas = null; // offscreen: biome grid, drawn once

const canvas = document.getElementById("map-canvas");
const ctx = canvas.getContext("2d");
const tooltip = document.getElementById("tooltip");

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
}

function drawFrame() {
  if (!staticCanvas || !latest) return;
  ctx.drawImage(staticCanvas, 0, 0);

  for (const farm of latest.farms) {
    ctx.fillStyle = FARM_COLORS[farm.stage] || "#888";
    ctx.fillRect(farm.x * CELL + 2, farm.y * CELL + 2, CELL - 4, CELL - 4);
  }

  for (const b of latest.buildings) {
    ctx.fillStyle = BUILDING_COLORS[b.kind] || "#aaa";
    ctx.globalAlpha = b.stage === "under_construction" ? 0.4 : b.stage === "ruined" ? 0.3 : 1.0;
    ctx.fillRect(b.x * CELL, b.y * CELL, CELL, CELL);
    ctx.globalAlpha = 1.0;
    ctx.strokeStyle = "#000";
    ctx.strokeRect(b.x * CELL + 0.5, b.y * CELL + 0.5, CELL - 1, CELL - 1);
  }

  for (const a of latest.agents) {
    ctx.beginPath();
    ctx.fillStyle = a.state === "resting" ? "#8894c9" : "#f2f2f2";
    ctx.arc(a.x * CELL + CELL / 2, a.y * CELL + CELL / 2, CELL / 3, 0, Math.PI * 2);
    ctx.fill();
    if (a.starving_ticks > 0) {
      ctx.strokeStyle = "#e0473c";
      ctx.lineWidth = 1;
      ctx.stroke();
    }
  }
}

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
  tooltip.innerHTML =
    `<b>${a.name}</b> (${a.state}, goal=${a.goal})<br>` +
    `hunger ${a.hunger.toFixed(2)} · energy ${a.energy.toFixed(2)} · age ${a.age_ticks}` +
    (a.goal_reason ? `<br><i>"${a.goal_reason}"</i>` : "");
});
canvas.addEventListener("mouseleave", () => tooltip.classList.add("hidden"));

function fmtPct(x) { return `${Math.round(x * 100)}%`; }

function renderStats(summary) {
  const p = summary.population, s = summary.settlement, r = summary.resources;
  const f = summary.farms, llm = summary.llm;
  const tiles = [
    ["Tick", summary.tick],
    ["Date", `${summary.date} (${summary.clock})`],
    ["Weather", summary.weather],
    ["Population", `${p.total} (${p.awake} awake, ${p.resting} resting)`],
    ["Avg hunger / energy", `${p.avg_hunger.toFixed(2)} / ${p.avg_energy.toFixed(2)}`],
    ["Deaths", `${p.deaths_starvation} starvation, ${p.deaths_old_age} old age`],
    ["Buildings", `${s.total} (${s.standing} standing, ${s.under_construction} building, ${s.ruined} ruined)`],
    ["Granaries", `${s.granaries} (${s.granary_food.toFixed(1)} food)`],
    ["Materials / Currency", `${s.materials.toFixed(1)} / ${s.currency.toFixed(1)}`],
    ["Farms", `${f.total} (${f.growing} growing, ${f.ready} ready)`],
    ["Resources", `${r.total_nodes} nodes (${r.depleted} depleted)`],
    ["LLM calls", `${llm.calls_total} (${fmtPct(llm.fallback_rate)} fallback)`],
  ];
  document.getElementById("stat-grid").innerHTML = tiles
    .map(([label, value]) => `<div class="stat-tile"><div class="label">${label}</div><div class="value">${value}</div></div>`)
    .join("");

  document.getElementById("settlement-name").textContent = s.name || "Hearthmind (unnamed settlement)";
  document.getElementById("clock-line").textContent = `${summary.date} · ${summary.clock} · ${summary.weather}`;

  const traditionsEl = document.getElementById("traditions-list");
  traditionsEl.innerHTML = s.traditions.length
    ? s.traditions.map((t) => `<li>${t}</li>`).join("")
    : "<li>none yet</li>";
}

function prependEvents(events) {
  // `events` must be oldest-first — each is prepended in that order so
  // the newest one ends up at the top of the log.
  const log = document.getElementById("event-log");
  for (const e of events) {
    const li = document.createElement("li");
    const tickPart = e.tick !== undefined ? `<span class="event-tick">[${e.tick}]</span>` : "";
    li.innerHTML = `${tickPart}${e.description}`;
    log.prepend(li);
  }
  while (log.children.length > 100) log.removeChild(log.lastChild);
}

function applyPayload(payload) {
  latest = payload;
  renderStats(payload.summary);
  drawFrame();
  if (payload.life_events && payload.life_events.length) {
    prependEvents(payload.life_events.map((e) => ({ ...e, tick: payload.summary.tick })));
  }
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
