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
    <thead><tr><th>Run</th><th>Category</th><th>Model</th><th>Progress</th><th>Status</th><th>Actions</th></tr></thead>
    <tbody id="runs-body"><tr><td colspan="6">loading…</td></tr></tbody>
  </table>
</fieldset>

<script>
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
    body.innerHTML = "<tr><td colspan=\\"6\\">no runs yet</td></tr>";
    return;
  }
  body.innerHTML = data.runs.map((run) => {
    const [cls, label] = statusOf(run);
    const progress = run.n_expected != null ? `${run.n_completed}/${run.n_expected}` : `${run.n_completed}/?`;
    const cancelBtn = run.is_running ? `<button onclick="cancelRun('${run.run_id}')">Cancel</button>` : "";
    return `<tr>
      <td>${run.run_id}</td><td>${run.category || ""}</td><td>${run.model || ""}</td>
      <td>${progress}</td><td class="status-${cls}">${label}</td>
      <td><a href="/api/runs/${run.run_id}/report" target="_blank">Report</a> ${cancelBtn}</td>
    </tr>`;
  }).join("");
}

async function cancelRun(runId) {
  await fetch(`/api/runs/${runId}/cancel`, { method: "POST" });
  refreshRuns();
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
