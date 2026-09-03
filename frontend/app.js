// AERION-X frontend. Every function here calls a real backend endpoint.
// There is no hardcoded/mock data anywhere in this file.

const API = ""; // same origin (backend serves this file itself)

// ---------- auth ----------
// Token lives in localStorage — per-browser only (see artifact/runtime notes:
// this is a real local desktop-style tool, not a published multi-viewer page,
// so a plain localStorage token is an appropriate, real session mechanism here).

function getToken() { return localStorage.getItem("aerionx_token"); }
function setToken(t) { localStorage.setItem("aerionx_token", t); }
function clearToken() { localStorage.removeItem("aerionx_token"); }

function authFetch(url, opts = {}) {
  const token = getToken();
  const headers = Object.assign({}, opts.headers || {}, token ? { Authorization: "Bearer " + token } : {});
  return fetch(API + url, Object.assign({}, opts, { headers }));
}

async function tryRestoreSession() {
  const token = getToken();
  if (!token) return false;
  try {
    const r = await fetch(API + "/auth/me", { headers: { Authorization: "Bearer " + token } });
    if (!r.ok) { clearToken(); return false; }
    const me = await r.json();
    document.getElementById("txt-user").textContent = `${me.username} (${me.role})`;
    document.getElementById("nav-audit").hidden = me.role !== "ADMIN";
    return true;
  } catch { return false; }
}

function showApp() {
  document.getElementById("login-overlay").hidden = true;
  document.getElementById("app-shell").hidden = false;
  connectWebSocket();
}

function showLogin() {
  document.getElementById("login-overlay").hidden = false;
  document.getElementById("app-shell").hidden = true;
}

document.getElementById("btn-login").addEventListener("click", async () => {
  const username = document.getElementById("login-username").value;
  const password = document.getElementById("login-password").value;
  document.getElementById("login-error").textContent = "";
  const r = await fetch(API + "/auth/login", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }) });
  const data = await r.json();
  if (!r.ok) { document.getElementById("login-error").textContent = data.detail || "Login failed"; return; }
  setToken(data.access_token);
  document.getElementById("txt-user").textContent = `${username} (${data.role})`;
  document.getElementById("nav-audit").hidden = data.role !== "ADMIN";
  showApp();
});

document.getElementById("btn-register").addEventListener("click", async () => {
  const username = document.getElementById("login-username").value;
  const password = document.getElementById("login-password").value;
  document.getElementById("login-error").textContent = "";
  const r = await fetch(API + "/auth/register", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }) });
  const data = await r.json();
  if (!r.ok) { document.getElementById("login-error").textContent = data.detail || "Registration failed"; return; }
  document.getElementById("login-error").textContent = `Account created as ${data.role}. Signing you in...`;
  document.getElementById("btn-login").click();
});

document.getElementById("btn-logout").addEventListener("click", () => {
  clearToken();
  if (ws) ws.close();
  showLogin();
});

(async () => {
  if (await tryRestoreSession()) showApp(); else showLogin();
})();

// ---------- navigation ----------

document.querySelectorAll(".nav-item").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".nav-item").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById("view-" + btn.dataset.view).classList.add("active");
    onViewShown(btn.dataset.view);
  });
});

function onViewShown(view) {
  if (view === "events") loadEvents();
  if (view === "sensors") loadSensorStreams();
  if (view === "inspection") loadInspectionHistory();
  if (view === "assets") loadAssets();
  if (view === "models") loadModels();
  if (view === "audit") loadAuditLog();
}

async function loadAuditLog() {
  const r = await authFetch("/audit-log?limit=200");
  const tbody = document.querySelector("#audit-table tbody");
  tbody.innerHTML = "";
  if (!r.ok) { tbody.innerHTML = `<tr><td colspan="5" class="empty-state">ADMIN role required</td></tr>`; return; }
  const rows = await r.json();
  if (rows.length === 0) { tbody.innerHTML = `<tr><td colspan="5" class="empty-state">No audit entries yet</td></tr>`; return; }
  rows.forEach(row => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${new Date(row.timestamp * 1000).toLocaleString()}</td><td>${row.username || "--"}</td>
      <td>${row.action}</td><td>${row.object_type || ""} ${row.object_id || ""}</td>
      <td><span class="sev-pill ${row.result === 'SUCCESS' ? 'INFO' : 'CRITICAL'}">${row.result}</span></td>`;
    tbody.appendChild(tr);
  });
}

// ---------- connection status ----------

async function pollHealth() {
  try {
    const r = await fetch(API + "/health");
    const ok = r.ok;
    document.getElementById("dot-api").className = "dot " + (ok ? "ok" : "bad");
    document.getElementById("txt-api").textContent = ok ? "CONNECTED" : "DOWN";
  } catch {
    document.getElementById("dot-api").className = "dot bad";
    document.getElementById("txt-api").textContent = "DOWN";
  }
}
setInterval(pollHealth, 4000);
pollHealth();

let ws = null;
function connectWebSocket() {
  const token = getToken();
  if (!token) return;
  ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws/pipeline?token=" + encodeURIComponent(token));
  ws.onopen = () => { document.getElementById("dot-ws").className = "dot ok"; document.getElementById("txt-ws").textContent = "LIVE"; };
  ws.onclose = () => {
    document.getElementById("dot-ws").className = "dot bad";
    document.getElementById("txt-ws").textContent = "OFFLINE";
    setTimeout(connectWebSocket, 3000);
  };
  ws.onerror = () => ws.close();
  ws.onmessage = (msg) => {
    const data = JSON.parse(msg.data);
    if (data.type === "status") updateTelemetry(data);
    if (data.type === "event") pushLiveEvent(data);
  };
}
// connectWebSocket() is called from showApp() once a session is confirmed —
// connecting before login would fail auth and busy-loop reconnecting.

// ---------- command center ----------

let liveEventCount = 0;

function updateTelemetry(data) {
  document.getElementById("m-fps").textContent = data.fps.toFixed(1);
  document.getElementById("m-latency").textContent = data.latency_ms.toFixed(0) + " ms";
  document.getElementById("m-tracks").textContent = data.active_tracks;
  document.getElementById("m-frames").textContent = data.frames_processed;
}

function pushLiveEvent(ev) {
  const feed = document.getElementById("live-feed");
  if (liveEventCount === 0) feed.innerHTML = "";
  liveEventCount++;
  document.getElementById("live-count").textContent = liveEventCount;
  const row = document.createElement("div");
  row.className = "event-row sev-" + (ev.severity || "INFO");
  row.innerHTML = `<span class="ev-time">t=${ev.timestamp.toFixed(2)}s</span><span class="ev-type">${ev.event_type}</span><span>tracks=${JSON.stringify(ev.track_ids)}</span>${ev.zone_id ? `<span>zone=${ev.zone_id}</span>` : ""}`;
  feed.prepend(row);
  while (feed.children.length > 50) feed.removeChild(feed.lastChild);
}

async function pollPipelineStatus() {
  try {
    const r = await fetch(API + "/pipeline/status");
    const s = await r.json();
    document.getElementById("m-status").textContent = s.status;
    document.getElementById("m-source").textContent = s.source_id || "--";
    if (s.status !== "RUNNING") {
      document.getElementById("btn-start").disabled = false;
      document.getElementById("btn-stop").disabled = true;
    }
  } catch {}
}
setInterval(pollPipelineStatus, 1500);
pollPipelineStatus();

document.getElementById("btn-start").addEventListener("click", async () => {
  const body = {
    source_type: document.getElementById("pipe-source").value,
    path: document.getElementById("pipe-path").value || null,
    max_frames: parseInt(document.getElementById("pipe-maxframes").value) || null,
    zone: document.getElementById("pipe-zone").checked,
  };
  document.getElementById("pipe-error").textContent = "";
  liveEventCount = 0;
  document.getElementById("live-feed").innerHTML = '<div class="empty-state">Waiting for events...</div>';
  document.getElementById("live-count").textContent = "0";
  try {
    const r = await authFetch("/pipeline/start", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await r.json();
    if (!r.ok) { document.getElementById("pipe-error").textContent = data.detail || "Failed to start"; return; }
    document.getElementById("btn-start").disabled = true;
    document.getElementById("btn-stop").disabled = false;
  } catch (e) {
    document.getElementById("pipe-error").textContent = "Request failed: " + e;
  }
});

document.getElementById("btn-stop").addEventListener("click", async () => {
  await authFetch("/pipeline/stop", { method: "POST" });
});

// ---------- events ----------

const KNOWN_EVENT_TYPES = [
  "OBJECT_APPEARED", "OBJECT_DISAPPEARED", "ZONE_ENTER", "ZONE_EXIT", "STATE_CHANGE",
  "PROLONGED_STATIONARY", "PERSON_VEHICLE_PROXIMITY", "CROWDING", "PERSON_RESTRICTED_ZONE_ENTRY",
  "VEHICLE_RESTRICTED_ZONE_ENTRY", "PROLONGED_IMMOBILITY", "FALL_LIKE_MOTION", "AREA_OCCUPANCY",
  "UNEXPECTED_OBJECT", "CONGESTION", "ANOMALY",
];
const filterSelect = document.getElementById("ev-filter");
KNOWN_EVENT_TYPES.forEach(t => { const o = document.createElement("option"); o.value = t; o.textContent = t; filterSelect.appendChild(o); });

async function loadEvents() {
  const type = document.getElementById("ev-filter").value;
  const limit = document.getElementById("ev-limit").value || 100;
  const url = API + "/events?limit=" + limit + (type ? "&event_type=" + type : "");
  const r = await fetch(url);
  const page = await r.json();
  const events = page.items;
  const tbody = document.querySelector("#events-table tbody");
  tbody.innerHTML = "";
  const countEl = document.getElementById("ev-count");
  if (countEl) countEl.textContent = `showing ${events.length} of ${page.total}`;
  if (events.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" class="empty-state">NO EVENTS — run a pipeline from Command Center first</td></tr>`;
    return;
  }
  for (const e of events) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${e.timestamp.toFixed(2)}s</td><td>${e.event_type}</td>
      <td><span class="sev-pill ${e.severity}">${e.severity}</span></td>
      <td>${JSON.stringify(e.track_ids)}</td><td>${e.zone_id || "--"}</td>
      <td><span class="prov-pill ${e.provenance}">${e.provenance}</span></td><td>${e.source_id}</td>`;
    tbody.appendChild(tr);
  }
}
document.getElementById("ev-refresh").addEventListener("click", loadEvents);
document.getElementById("ev-filter").addEventListener("change", loadEvents);

async function downloadPdf(path, filenameHint) {
  const r = await authFetch(path);
  if (!r.ok) { alert("Report generation failed (" + r.status + ")"); return; }
  const blob = await r.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filenameHint;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

document.getElementById("ev-report").addEventListener("click", () => {
  const type = document.getElementById("ev-filter").value;
  downloadPdf("/reports/events" + (type ? "?event_type=" + type : ""), "aerionx_event_report.pdf");
});

// ---------- sensors ----------

document.getElementById("btn-gen-sensor").addEventListener("click", async () => {
  const seed = Math.floor(Math.random() * 100000);
  await authFetch("/sensors/generate-synthetic", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ seed }) });
  loadSensorStreams();
});

async function loadSensorStreams() {
  const r = await fetch(API + "/sensors/streams");
  const streams = await r.json();
  const list = document.getElementById("sensor-stream-list");
  list.innerHTML = "";
  if (streams.length === 0) {
    list.innerHTML = '<div class="empty-state">No streams yet — click generate above</div>';
    return;
  }
  streams.forEach(s => {
    const item = document.createElement("div");
    item.className = "list-item";
    item.innerHTML = `<span>${s.stream_id}</span><span class="prov-pill ${s.provenance}">${s.provenance}</span>`;
    item.addEventListener("click", () => selectStream(s.stream_id, item));
    list.appendChild(item);
  });
  selectStream(streams[0].stream_id, list.firstChild);
}

async function selectStream(streamId, el) {
  document.querySelectorAll("#sensor-stream-list .list-item").forEach(i => i.classList.remove("selected"));
  if (el) el.classList.add("selected");
  const [readingsRes, anomaliesRes] = await Promise.all([
    fetch(API + "/sensors/streams/" + streamId + "/readings"),
    fetch(API + "/sensors/anomalies?stream_id=" + streamId),
  ]);
  const readings = await readingsRes.json();
  const anomalies = await anomaliesRes.json();
  drawSensorChart(readings, anomalies);
  document.getElementById("sensor-stats").innerHTML =
    `<span>samples: <b>${readings.length}</b></span><span>anomalies: <b>${anomalies.length}</b></span>
     <button class="btn btn-secondary" onclick="downloadPdf('/reports/sensor/${streamId}', 'sensor_${streamId.replace(':','_')}.pdf')">DOWNLOAD PDF REPORT</button>`;
}

function drawSensorChart(readings, anomalies) {
  const svg = document.getElementById("sensor-chart");
  svg.innerHTML = "";
  if (readings.length === 0) return;
  const W = 800, H = 260, PAD = 20;
  const values = readings.map(r => r.value);
  const min = Math.min(...values), max = Math.max(...values);
  const range = (max - min) || 1;
  const xStep = (W - 2 * PAD) / (readings.length - 1 || 1);
  const yOf = v => H - PAD - ((v - min) / range) * (H - 2 * PAD);

  let path = "M ";
  readings.forEach((r, i) => { path += `${PAD + i * xStep},${yOf(r.value)} `; if (i < readings.length - 1) path += "L "; });
  const pathEl = document.createElementNS("http://www.w3.org/2000/svg", "path");
  pathEl.setAttribute("d", path);
  pathEl.setAttribute("stroke", "#4fd1c5");
  pathEl.setAttribute("fill", "none");
  pathEl.setAttribute("stroke-width", "1.5");
  svg.appendChild(pathEl);

  const anomalyTimestamps = new Set(anomalies.map(a => a.timestamp));
  readings.forEach((r, i) => {
    if (anomalyTimestamps.has(r.timestamp)) {
      const c = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      c.setAttribute("cx", PAD + i * xStep);
      c.setAttribute("cy", yOf(r.value));
      c.setAttribute("r", 3.5);
      c.setAttribute("fill", "#e0522d");
      svg.appendChild(c);
    }
  });
}

// ---------- inspection ----------

async function ensureAsset(id) {
  await authFetch("/assets", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ asset_id: id, asset_type: "AIRCRAFT", name: id }) });
}

document.getElementById("btn-create-asset").addEventListener("click", () => ensureAsset(document.getElementById("insp-asset").value));

document.getElementById("btn-run-inspection").addEventListener("click", async () => {
  const body = {
    asset_id: document.getElementById("insp-asset").value,
    video_path: document.getElementById("insp-video").value,
    reference_frame: parseInt(document.getElementById("insp-ref").value),
    current_frame: parseInt(document.getElementById("insp-cur").value),
  };
  document.getElementById("insp-error").textContent = "";
  const r = await authFetch("/inspections/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await r.json();
  if (!r.ok) { document.getElementById("insp-error").textContent = data.detail || "Failed"; return; }
  document.getElementById("insp-result").innerHTML = `
    <dl class="kv-grid">
      <dt>Inspection ID</dt><dd>${data.inspection_id}</dd>
      <dt>Change score</dt><dd>${data.change_score.toFixed(4)}</dd>
      <dt>Mean SSIM</dt><dd>${data.mean_ssim.toFixed(4)}</dd>
      <dt>Regions found</dt><dd>${data.anomaly_regions.length}</dd>
    </dl>
    <div style="margin-top:10px">${data.anomaly_regions.map(r => `<span class="region-chip">${r.label} (${r.area_px}px)</span>`).join("") || "none"}</div>
    <div class="panel-note">${data.notes}</div>
    <button class="btn btn-secondary" style="margin-top:10px" onclick="downloadPdf('/reports/inspection/${data.inspection_id}', 'inspection_${data.inspection_id}.pdf')">DOWNLOAD PDF REPORT</button>`;
  loadInspectionHistory();
});

async function loadInspectionHistory() {
  const r = await fetch(API + "/inspections");
  const rows = await r.json();
  const tbody = document.querySelector("#insp-history-table tbody");
  tbody.innerHTML = "";
  if (rows.length === 0) { tbody.innerHTML = `<tr><td colspan="5" class="empty-state">No inspections run yet</td></tr>`; return; }
  rows.forEach(insp => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${new Date(insp.created_at * 1000).toLocaleTimeString()}</td><td>${insp.asset_id}</td>
      <td>${insp.change_score.toFixed(4)}</td><td>${insp.mean_ssim.toFixed(4)}</td><td>${insp.anomaly_regions.length}</td>`;
    tbody.appendChild(tr);
  });
}

// ---------- motion analysis ----------

document.getElementById("btn-run-flow").addEventListener("click", async () => {
  const body = {
    video_path: document.getElementById("flow-video").value,
    frame_a: parseInt(document.getElementById("flow-a").value),
    frame_b: parseInt(document.getElementById("flow-b").value),
  };
  const r = await authFetch("/flow/demo", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await r.json();
  const el = document.getElementById("flow-result");
  if (!r.ok) { el.textContent = data.detail || "Failed"; return; }
  el.innerHTML = `<dl class="kv-grid">
    <dt>Method</dt><dd>${data.method}</dd>
    <dt>Mean magnitude</dt><dd>${data.magnitude_mean.toFixed(3)} px/frame</dd>
    <dt>Max magnitude</dt><dd>${data.magnitude_max.toFixed(3)} px/frame</dd>
    <dt>Mean direction</dt><dd>${data.direction_mean_deg.toFixed(1)}°</dd>
  </dl>`;
});

// ---------- assets ----------

document.getElementById("btn-create-asset2").addEventListener("click", async () => {
  const body = {
    asset_id: document.getElementById("asset-id").value,
    asset_type: document.getElementById("asset-type").value,
    name: document.getElementById("asset-name").value,
  };
  await authFetch("/assets", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  loadAssets();
});

async function loadAssets() {
  const r = await fetch(API + "/assets");
  const assets = await r.json();
  const list = document.getElementById("asset-list");
  list.innerHTML = "";
  if (assets.length === 0) { list.innerHTML = '<div class="empty-state">No assets yet</div>'; return; }
  assets.forEach(a => {
    const item = document.createElement("div");
    item.className = "list-item";
    item.innerHTML = `<span>${a.asset_id}</span><span>${a.asset_type}</span>`;
    item.addEventListener("click", () => selectAsset(a.asset_id, item));
    list.appendChild(item);
  });
}

async function selectAsset(assetId, el) {
  document.querySelectorAll("#asset-list .list-item").forEach(i => i.classList.remove("selected"));
  if (el) el.classList.add("selected");
  const r = await fetch(API + "/assets/" + assetId + "/graph");
  const graph = await r.json();
  document.getElementById("asset-graph").innerHTML = `
    <dl class="kv-grid">
      <dt>Asset</dt><dd>${graph.asset.name} (${graph.asset.asset_type})</dd>
      <dt>Sensor streams</dt><dd>${graph.sensor_streams.length}</dd>
      <dt>Inspections</dt><dd>${graph.inspections.length}</dd>
      <dt>Events</dt><dd>${graph.events.length}</dd>
      <dt>Anomalies</dt><dd>${graph.anomalies.length}</dd>
    </dl>
    <button class="btn btn-secondary" style="margin-top:10px" onclick="downloadPdf('/reports/asset/${assetId}', 'asset_${assetId}.pdf')">DOWNLOAD PDF REPORT</button>`;
}

// ---------- field capture (works from a phone browser too) ----------

let captureStream = null;

document.getElementById("btn-camera-start").addEventListener("click", async () => {
  const errEl = document.getElementById("capture-error");
  errEl.textContent = "";
  try {
    // getUserMedia requires a "secure context": https, or localhost/127.0.0.1.
    // Over plain http from another device on the network, the browser will
    // refuse this — that's a real browser security rule, not a bug here.
    captureStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
    const video = document.getElementById("capture-video");
    video.srcObject = captureStream;
    document.getElementById("btn-camera-shoot").disabled = false;
  } catch (e) {
    errEl.textContent = "Camera unavailable: " + e.message +
      " (getUserMedia needs HTTPS or localhost — see the note in MOBILE_ARCHITECTURE.md if accessing from another device)";
  }
});

document.getElementById("btn-camera-shoot").addEventListener("click", async () => {
  const video = document.getElementById("capture-video");
  const canvas = document.getElementById("capture-canvas");
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  canvas.getContext("2d").drawImage(video, 0, 0);
  canvas.toBlob(blob => analyzeCaptureBlob(blob), "image/jpeg", 0.9);
});

document.getElementById("capture-file-input").addEventListener("change", (e) => {
  const file = e.target.files[0];
  if (file) analyzeCaptureBlob(file);
});

async function analyzeCaptureBlob(blob) {
  const preview = document.getElementById("capture-preview");
  preview.src = URL.createObjectURL(blob);
  preview.style.display = "block";
  document.getElementById("capture-result").innerHTML = '<div class="empty-state">Analyzing...</div>';

  const formData = new FormData();
  formData.append("file", blob, "capture.jpg");

  const token = getToken();
  const r = await fetch(API + "/capture/analyze", {
    method: "POST",
    headers: token ? { Authorization: "Bearer " + token } : {},
    body: formData,
  });
  const data = await r.json();
  const resultEl = document.getElementById("capture-result");
  if (!r.ok) { resultEl.innerHTML = `<div class="error-text">${data.detail || "Analysis failed"}</div>`; return; }

  resultEl.innerHTML = `
    <dl class="kv-grid">
      <dt>Image size</dt><dd>${data.image_width}x${data.image_height}</dd>
      <dt>Inference time</dt><dd>${data.inference_ms.toFixed(0)} ms</dd>
      <dt>Detections</dt><dd>${data.detections.length}</dd>
    </dl>
    <div style="margin-top:10px">${data.detections.map(d =>
      `<span class="region-chip">${d.class_name} ${(d.confidence * 100).toFixed(0)}%</span>`).join("") || "none found"}</div>`;
}

// ---------- model lab ----------

document.getElementById("btn-register-model").addEventListener("click", async () => {
  await authFetch("/models/register-yolo", { method: "POST" });
  loadModels();
});

async function loadModels() {
  const r = await fetch(API + "/models");
  const models = await r.json();
  const tbody = document.querySelector("#models-table tbody");
  tbody.innerHTML = "";
  if (models.length === 0) { tbody.innerHTML = `<tr><td colspan="7" class="empty-state">No models registered yet</td></tr>`; return; }
  models.forEach(m => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${m.name}</td><td>${m.version}</td><td>${m.framework}</td>
      <td>${m.num_parameters ? m.num_parameters.toLocaleString() : "--"}</td>
      <td>${m.classes.length}</td><td>${m.hardware}</td><td>${m.license}</td>`;
    tbody.appendChild(tr);
  });
}
