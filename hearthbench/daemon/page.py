"""A12.1's real page — a small, self-contained, vanilla-JS single page
served BY the bench daemon itself (never by `hearthmind.interface`),
clearly marked as not part of the live simulation per the item's own
literal text. Kept as a plain Python string (not a `.html` file under
`hearthbench/daemon/`) so it ships correctly via `hearthbench*` package
discovery with zero extra packaging config."""
from __future__ import annotations

INDEX_HTML = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>HearthBench Daemon</title>
<style>
  body { font-family: -apple-system, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; color: #222; }
  .banner { background: #3a2a00; color: #ffd280; padding: 0.6rem 1rem; border-radius: 6px; font-weight: 600; margin-bottom: 1.5rem; }
  fieldset { border: 1px solid #ccc; border-radius: 6px; margin-bottom: 1.5rem; }
  label { display: block; margin: 0.4rem 0 0.15rem; font-size: 0.85rem; color: #555; }
  input, select { width: 100%; box-sizing: border-box; padding: 0.35rem; }
  button { margin-top: 0.8rem; padding: 0.45rem 1rem; cursor: pointer; }
  table { width: 100%; border-collapse: collapse; }
  th, td { text-align: left; padding: 0.4rem 0.5rem; border-bottom: 1px solid #eee; font-size: 0.9rem; }
  .status-running { color: #b5860a; }
  .status-crashed { color: #b00020; }
  .status-complete { color: #1a7a1a; }
  .status-unknown { color: #777; }
  #msg { font-size: 0.85rem; min-height: 1.2em; }
  .case-row { cursor: pointer; }
  .case-row:hover { background: #f6f6f6; }
  #case-detail { background: #f6f6f6; border-radius: 6px; padding: 0.8rem; margin-top: 0.6rem; }
  #case-detail pre { white-space: pre-wrap; word-break: break-word; background: #fff; padding: 0.5rem; border: 1px solid #ddd; border-radius: 4px; }
  #compare-result table { margin-top: 0.6rem; }
  .sig-true { color: #b00020; font-weight: 600; }
  .sig-false { color: #777; }
</style>
</head>
<body>
<div class="banner">⚠ HearthBench Daemon — a model benchmark tool. This is NOT the live town simulation.</div>

<fieldset>
  <legend>Start a run</legend>
  <form id="start-form">
    <label>Category</label>
    <select id="category"><option value="grounding">grounding</option></select>
    <label>Adapter endpoint (e.g. http://127.0.0.1:8080/v1)</label>
    <input id="adapter_endpoint" required>
    <label>Adapter model</label>
    <input id="adapter_model" required>
    <label>API key (optional)</label>
    <input id="adapter_api_key">
    <label>Quantization (optional)</label>
    <input id="adapter_quantization">
    <label>Context size (optional)</label>
    <input id="adapter_context" type="number">
    <button type="submit">Start run</button>
  </form>
  <div id="msg"></div>
</fieldset>

<fieldset>
  <legend>Runs</legend>
  <table>
    <thead><tr><th></th><th>Run</th><th>Category</th><th>Model</th><th>Progress</th><th>Status</th><th>Actions</th></tr></thead>
    <tbody id="runs-body"><tr><td colspan="7">loading…</td></tr></tbody>
  </table>
  <button onclick="compareSelected()">Compare selected</button>
  <div id="compare-result"></div>
</fieldset>

<fieldset id="cases-panel" style="display:none">
  <legend>Cases — <span id="cases-run-id"></span></legend>
  <table>
    <thead><tr><th>Case</th><th>Category</th><th>Fallback?</th><th>Error</th><th>Latency (ms)</th></tr></thead>
    <tbody id="cases-body"></tbody>
  </table>
  <div id="case-detail"></div>
</fieldset>

<fieldset>
  <legend>Human rating (A4.3 / A12.9) — blind pairwise</legend>
  <label>Run A</label><select id="rate-run-a"></select>
  <label>Run B</label><select id="rate-run-b"></select>
  <label>Rater id</label><input id="rater-id" value="anonymous">
  <button onclick="loadRatingTasks()">Load tasks</button>
  <button onclick="showAgreement()">Show agreement report</button>
  <div id="rating-status"></div>
  <div id="rating-task"></div>
  <label>Note (optional)</label>
  <textarea id="rater-note" rows="2" style="width:100%"></textarea>
  <div id="agreement-result"></div>
</fieldset>

<script>
function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

function statusOf(run) {
  if (run.crashed) return ["crashed", "crashed"];
  if (run.is_running) return ["running", "running"];
  if (run.n_expected != null && run.n_completed >= run.n_expected) return ["complete", "complete"];
  return ["unknown", "not tracked by this daemon"];
}

async function refreshRuns() {
  const res = await fetch("/api/runs");
  const data = await res.json();
  const body = document.getElementById("runs-body");
  if (!data.runs.length) {
    body.innerHTML = "<tr><td colspan=\\"7\\">no runs yet</td></tr>";
    return;
  }
  body.innerHTML = data.runs.map((run) => {
    const [cls, label] = statusOf(run);
    const progress = run.n_expected != null ? `${run.n_completed}/${run.n_expected}` : `${run.n_completed}/?`;
    const cancelBtn = run.is_running ? `<button onclick="cancelRun('${run.run_id}')">Cancel</button>` : "";
    return `<tr>
      <td><input type="checkbox" class="compare-check" value="${esc(run.run_id)}"></td>
      <td>${esc(run.run_id)}</td><td>${esc(run.category || "")}</td><td>${esc(run.model || "")}</td>
      <td>${progress}</td><td class="status-${cls}">${label}</td>
      <td><a href="/api/runs/${run.run_id}/report" target="_blank">Report</a>
        · <a href="#" onclick="showCases('${run.run_id}'); return false;">Cases</a>
        · <a href="/api/runs/${run.run_id}/export.json">JSON</a>
        · <a href="/api/runs/${run.run_id}/export.csv">CSV</a>
        ${cancelBtn}</td>
    </tr>`;
  }).join("");

  const selA = document.getElementById("rate-run-a");
  const selB = document.getElementById("rate-run-b");
  if (selA && selB) {
    const prevA = selA.value, prevB = selB.value;
    const optionsHtml = data.runs.map((r) => `<option value="${esc(r.run_id)}">${esc(r.run_id)}</option>`).join("");
    selA.innerHTML = optionsHtml;
    selB.innerHTML = optionsHtml;
    if (data.runs.some((r) => r.run_id === prevA)) selA.value = prevA;
    if (data.runs.some((r) => r.run_id === prevB)) selB.value = prevB;
  }
}

async function cancelRun(runId) {
  await fetch(`/api/runs/${runId}/cancel`, { method: "POST" });
  refreshRuns();
}

async function compareSelected() {
  // A12.6: real reuse of GET /api/runs/compare -- this is presentation
  // only, all comparison math (deltas, significance) happens server-side.
  const ids = Array.from(document.querySelectorAll(".compare-check:checked")).map((el) => el.value);
  const result = document.getElementById("compare-result");
  if (ids.length < 2) {
    result.innerHTML = "<p>Select at least 2 runs to compare (the first checked becomes the baseline).</p>";
    return;
  }
  const res = await fetch(`/api/runs/compare?run_ids=${encodeURIComponent(ids.join(","))}`);
  if (!res.ok) {
    result.innerHTML = "<p>Compare failed: " + esc(await res.text()) + "</p>";
    return;
  }
  const data = await res.json();
  const baseline = data.labels[0];
  let html = `<table><thead><tr><th>Category</th>${data.labels.map((l) => `<th>${esc(l)}</th>`).join("")}</tr></thead><tbody>`;
  for (const [catId, comp] of Object.entries(data.categories)) {
    html += `<tr><td>${esc(catId)}</td>`;
    for (const label of data.labels) {
      const score = comp.scores[label];
      if (label === baseline) {
        html += `<td>${score == null ? "—" : score.toFixed(1)} (baseline)</td>`;
        continue;
      }
      const delta = comp.delta_from_baseline[label];
      const sig = comp.significant_change[label];
      const sigClass = sig === true ? "sig-true" : sig === false ? "sig-false" : "";
      const sigLabel = sig === true ? " (significant)" : sig === false ? " (not significant)" : " (can't tell)";
      html += `<td class="${sigClass}">${score == null ? "—" : score.toFixed(1)}`
            + `${delta == null ? "" : ` (Δ${delta >= 0 ? "+" : ""}${delta.toFixed(1)}${sigLabel})`}</td>`;
    }
    html += "</tr>";
  }
  html += `</tbody></table><p>Totals: ${data.labels.map((l) => `${esc(l)}=${data.totals[l] == null ? "—" : data.totals[l].toFixed(1)}`).join(", ")}</p>`;
  result.innerHTML = html;
}

async function showCases(runId) {
  // A12.7: list every real committed case for this run.
  document.getElementById("cases-panel").style.display = "";
  document.getElementById("cases-run-id").textContent = runId;
  document.getElementById("case-detail").innerHTML = "";
  const res = await fetch(`/api/runs/${runId}/cases`);
  const data = await res.json();
  const body = document.getElementById("cases-body");
  if (!data.cases.length) {
    body.innerHTML = "<tr><td colspan=\\"5\\">no cases committed yet</td></tr>";
    return;
  }
  body.innerHTML = data.cases.map((c) => `
    <tr class="case-row" onclick="showCaseDetail('${runId}', '${esc(c.case_id).replace(/'/g, "\\\\'")}')">
      <td>${esc(c.case_id)}</td><td>${esc(c.category)}</td>
      <td>${c.fallback_used ? "yes" : "no"}</td><td>${esc(c.error || "")}</td>
      <td>${c.latency_ms == null ? "—" : c.latency_ms.toFixed(0)}</td>
    </tr>`).join("");
}

async function showCaseDetail(runId, caseId) {
  // A12.7: drill in -- prompt/completion/parsed output/scores/timing.
  const res = await fetch(`/api/runs/${runId}/cases/${encodeURIComponent(caseId)}`);
  const detail = document.getElementById("case-detail");
  if (!res.ok) {
    detail.innerHTML = "<p>Failed to load case: " + esc(await res.text()) + "</p>";
    return;
  }
  const c = await res.json();
  const scoreRows = Object.entries(c.scores || {}).map(([sid, sd]) =>
    `<tr><td>${esc(sid)}</td><td>${sd.value == null ? "—" : sd.value.toFixed(2)}</td>`
    + `<td>${sd.passed == null ? "—" : sd.passed}</td></tr>`).join("");
  detail.innerHTML = `
    <p><b>${esc(c.case_id)}</b> (${esc(c.category)}) — latency ${c.latency_ms == null ? "—" : c.latency_ms.toFixed(0) + "ms"},
    fallback_used=${c.fallback_used}, retries=${c.retries}</p>
    <pre><b>Prompt:</b>\n${esc(c.prompt)}</pre>
    <pre><b>Completion:</b>\n${esc(c.completion)}</pre>
    <table><thead><tr><th>Scorer</th><th>Value</th><th>Passed</th></tr></thead><tbody>${scoreRows}</tbody></table>`;
}

let ratingQueue = [];
let ratingIndex = 0;

async function loadRatingTasks() {
  // A12.9: fetch the real blind-pairwise queue for the chosen pair.
  const runA = document.getElementById("rate-run-a").value;
  const runB = document.getElementById("rate-run-b").value;
  const status = document.getElementById("rating-status");
  if (!runA || !runB || runA === runB) {
    status.textContent = "Pick two different runs.";
    return;
  }
  const res = await fetch(`/api/rating/tasks?run_a=${encodeURIComponent(runA)}&run_b=${encodeURIComponent(runB)}`);
  if (!res.ok) {
    status.textContent = "Failed to load tasks: " + esc(await res.text());
    return;
  }
  const data = await res.json();
  ratingQueue = data.tasks;
  ratingIndex = 0;
  status.textContent = `${data.n_pending} of ${data.n_total} pending.`;
  renderRatingTask();
}

function renderRatingTask() {
  const area = document.getElementById("rating-task");
  if (ratingIndex >= ratingQueue.length) {
    area.innerHTML = "<p>No more pending tasks for this pair.</p>";
    return;
  }
  const t = ratingQueue[ratingIndex];
  area.innerHTML = `
    <pre><b>Prompt:</b>\n${esc(t.prompt_text)}</pre>
    <div style="display:flex; gap:1rem;">
      <pre style="flex:1"><b>Candidate A:</b>\n${esc(t.candidate_a_text)}</pre>
      <pre style="flex:1"><b>Candidate B:</b>\n${esc(t.candidate_b_text)}</pre>
    </div>
    <button onclick="submitRating('a')">A is better</button>
    <button onclick="submitRating('tie')">Tie</button>
    <button onclick="submitRating('b')">B is better</button>`;
}

async function submitRating(choice) {
  const t = ratingQueue[ratingIndex];
  if (!t) return;
  const raterId = document.getElementById("rater-id").value || "anonymous";
  const noteEl = document.getElementById("rater-note");
  const note = noteEl && noteEl.value ? noteEl.value : null;
  const res = await fetch("/api/rating/submit", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task_id: t.task_id, rater_id: raterId, choice: choice, note: note }),
  });
  if (!res.ok) {
    document.getElementById("rating-status").textContent = "Failed to submit: " + esc(await res.text());
    return;
  }
  if (noteEl) noteEl.value = "";
  ratingIndex += 1;
  document.getElementById("rating-status").textContent = `${ratingQueue.length - ratingIndex} of ${ratingQueue.length} pending.`;
  renderRatingTask();
}

async function showAgreement() {
  // A4.3: real reuse of judge_human_agreement over this pair's tasks.
  const runA = document.getElementById("rate-run-a").value;
  const runB = document.getElementById("rate-run-b").value;
  const result = document.getElementById("agreement-result");
  if (!runA || !runB) {
    result.innerHTML = "<p>Pick two runs first.</p>";
    return;
  }
  const res = await fetch(`/api/rating/agreement?run_a=${encodeURIComponent(runA)}&run_b=${encodeURIComponent(runB)}`);
  if (!res.ok) {
    result.innerHTML = "<p>Failed: " + esc(await res.text()) + "</p>";
    return;
  }
  const data = await res.json();
  const rate = data.agreement_rate == null ? "n/a" : (data.agreement_rate * 100).toFixed(1) + "%";
  result.innerHTML = `<p>Compared: ${data.n_compared}, agreed: ${data.n_agree}, `
    + `agreement rate: ${rate}, no judge score yet: ${data.n_no_judge_score}</p>`;
}

document.getElementById("start-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const msg = document.getElementById("msg");
  const body = {
    category: document.getElementById("category").value,
    adapter_endpoint: document.getElementById("adapter_endpoint").value,
    adapter_model: document.getElementById("adapter_model").value,
    adapter_api_key: document.getElementById("adapter_api_key").value || null,
    adapter_quantization: document.getElementById("adapter_quantization").value || null,
    adapter_context: document.getElementById("adapter_context").value ? Number(document.getElementById("adapter_context").value) : null,
  };
  const res = await fetch("/api/runs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (res.ok) {
    const data = await res.json();
    msg.textContent = `Started ${data.run_id}`;
    refreshRuns();
  } else {
    msg.textContent = "Failed to start run: " + (await res.text());
  }
});

refreshRuns();
setInterval(refreshRuns, 2000);
</script>
</body>
</html>
"""
