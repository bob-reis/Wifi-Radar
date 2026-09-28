"use strict";

const $ = (id) => document.getElementById(id);
const BAND_COLOR = { "2.4": "#39d353", "5": "#58a6ff", "6": "#bc8cff" };

const stateUI = {
  aps: [],
  running: false,
  mode: null,
  selected: null,       // bssid selecionado (tabela/calibração)
  calSamples: [],       // [[dist, rssi], ...]
  nodes: new Map(),     // bssid -> {x, y, r, tr}
  sweep: 0,
};

/* ---------------- WebSocket ---------------- */
function connectWS() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "scan") applyScan(msg.data);
    else if (msg.type === "error") showScanError(msg.message);
  };
  ws.onclose = () => setTimeout(connectWS, 1500);
}

function applyScan(data) {
  stateUI.aps = data.aps || [];
  stateUI.running = !!data.running;
  stateUI.mode = data.mode;
  updateStatus(data);
  renderTable();
  renderCalBssidOptions();
  syncNodes();
}

function showScanError(text) {
  stateUI.running = false;
  const el = $("scan-msg");
  el.textContent = "⚠ " + text;
  el.className = "msg err";
  $("status-dot").className = "dot err";
  $("status-text").textContent = "erro";
  setRunningUI(false);
}

/* ---------------- Status / controles ---------------- */
function updateStatus(data) {
  $("status-dot").className = "dot " + (stateUI.running ? "on" : "off");
  $("status-text").textContent = stateUI.running ? "escaneando" : "parado";
  $("status-mode").textContent = data.mode ? data.mode.toUpperCase() : "";
  $("status-mon").textContent = data.monitor || "";
  setRunningUI(stateUI.running);
  if (data.focus) showFocus(data.focus);
}

function setRunningUI(running) {
  $("btn-start").disabled = running;
  $("btn-stop").disabled = !running;
}

async function loadInterfaces() {
  try {
    const r = await fetch("/api/interfaces");
    const d = await r.json();
    const sel = $("interface");
    sel.innerHTML = "";
    // Só lista adaptadores que suportam monitor mode (os demais não servem
    // para o scan e, se forem o uplink do host, ainda derrubariam o SSH).
    const usable = d.interfaces.filter((i) => i.monitor_capable);
    if (!usable.length) {
      sel.innerHTML =
        "<option value=''>nenhum adaptador com monitor mode — conecte um USB compatível</option>";
    }
    for (const i of usable) {
      const up = i.uplink ? " ⛔ uplink do host" : "";
      const opt = document.createElement("option");
      opt.value = i.iface;
      opt.textContent = `${i.iface} (${i.mode || "?"})${up}`;
      // Mesmo suportando monitor, bloqueia se for a interface de uplink
      if (i.uplink) opt.disabled = true;
      opt.selected = !i.uplink;
      sel.appendChild(opt);
    }
    if (d.regulatory && d.regulatory !== "?") $("country").value = d.regulatory;
  } catch (e) { /* backend ainda subindo */ }
}

$("mode").addEventListener("change", (e) => {
  $("iface-row").style.display = e.target.value === "sim" ? "none" : "block";
});

$("btn-start").addEventListener("click", async () => {
  const msg = $("scan-msg");
  msg.textContent = "iniciando…"; msg.className = "msg";
  const cfg = {
    mode: $("mode").value,
    interface: $("interface").value || null,
    band: $("band").value,
    environment: $("environment").value,
    country: $("country").value || null,
    txpower: $("txpower").value ? Number($("txpower").value) : null,
    bssid: stateUI.focusBssid || null,
  };
  const r = await fetch("/api/scan/start", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cfg),
  });
  const d = await r.json();
  if (d.ok) { msg.textContent = "scan ativo (" + d.mode + ")"; msg.className = "msg ok"; }
  else { msg.textContent = "⚠ " + d.error; msg.className = "msg err"; }
});

$("btn-stop").addEventListener("click", async () => {
  await fetch("/api/scan/stop", { method: "POST" });
  $("scan-msg").textContent = "parado"; $("scan-msg").className = "msg";
});

/* ---------------- Sintonia / regulatório ---------------- */
$("btn-tune").addEventListener("click", async () => {
  const body = {
    interface: $("interface").value || null,
    country: $("country").value || null,
    txpower: $("txpower").value ? Number($("txpower").value) : null,
  };
  const r = await fetch("/api/tune", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  $("tune-out").textContent = JSON.stringify(await r.json(), null, 2);
});

/* ---------------- Tabela de APs ---------------- */
function renderTable() {
  $("ap-count").textContent = stateUI.aps.length;
  const tb = $("ap-tbody");
  tb.innerHTML = "";
  for (const ap of stateUI.aps) {
    const tr = document.createElement("tr");
    if (ap.bssid === stateUI.selected) tr.className = "sel";
    const dist = ap.distance != null ? ap.distance.toFixed(1) + " m" : "—";
    const cal = ap.calibrated ? " ✦" : "";
    tr.innerHTML = `
      <td>${escapeHtml(ap.ssid) || "<i>(oculto)</i>"}</td>
      <td class="mono">${ap.bssid}</td>
      <td><span class="band band-${ap.band}">${ap.band || "?"}</span></td>
      <td>${ap.channel ?? "—"}</td>
      <td>${ap.rssi} dBm</td>
      <td>${dist}${cal}</td>
      <td><button data-b="${ap.bssid}" class="focus-btn">🎯</button></td>`;
    tr.addEventListener("click", () => selectAp(ap.bssid));
    tb.appendChild(tr);
  }
  tb.querySelectorAll(".focus-btn").forEach((b) =>
    b.addEventListener("click", (e) => {
      e.stopPropagation();
      startFocus(b.dataset.b);
    })
  );
}

function selectAp(bssid) {
  stateUI.selected = bssid;
  $("cal-bssid").value = bssid;
  renderTable();
}

function escapeHtml(s) {
  return (s || "").replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

/* ---------------- Focus mode ---------------- */
function startFocus(bssid) {
  stateUI.focusBssid = bssid;
  showFocus(bssid);
  $("btn-start").click();
}
function showFocus(bssid) {
  const ap = stateUI.aps.find((a) => a.bssid === bssid);
  $("focus-name").textContent = (ap && ap.ssid ? ap.ssid + " " : "") + bssid;
  $("focus-bar").classList.remove("hidden");
}
$("focus-clear").addEventListener("click", async () => {
  stateUI.focusBssid = null;
  $("focus-bar").classList.add("hidden");
  await fetch("/api/scan/stop", { method: "POST" });
});

/* ---------------- Calibração ---------------- */
function renderCalBssidOptions() {
  const sel = $("cal-bssid");
  const cur = sel.value;
  const opts = ['<option value="">— selecione um AP —</option>'];
  for (const ap of stateUI.aps) {
    opts.push(`<option value="${ap.bssid}">${escapeHtml(ap.ssid) || "(oculto)"} — ${ap.bssid}</option>`);
  }
  sel.innerHTML = opts.join("");
  sel.value = cur || stateUI.selected || "";
}

$("cal-capture").addEventListener("click", () => {
  const b = $("cal-bssid").value;
  const ap = stateUI.aps.find((a) => a.bssid === b);
  if (ap) $("cal-rssi").value = ap.rssi;
});

$("cal-add").addEventListener("click", () => {
  const d = parseFloat($("cal-dist").value);
  let r = parseFloat($("cal-rssi").value);
  if (isNaN(r)) {
    const ap = stateUI.aps.find((a) => a.bssid === $("cal-bssid").value);
    if (ap) r = ap.rssi;
  }
  if (isNaN(d) || d <= 0 || isNaN(r)) return;
  stateUI.calSamples.push([d, r]);
  $("cal-dist").value = ""; $("cal-rssi").value = "";
  renderSamples();
});

function renderSamples() {
  const ul = $("cal-samples");
  ul.innerHTML = "";
  stateUI.calSamples.forEach((s, i) => {
    const li = document.createElement("li");
    li.innerHTML = `<span>${s[0]} m → ${s[1]} dBm</span><button data-i="${i}">✕</button>`;
    li.querySelector("button").addEventListener("click", () => {
      stateUI.calSamples.splice(i, 1); renderSamples();
    });
    ul.appendChild(li);
  });
  $("cal-fit").disabled = stateUI.calSamples.length < 2;
}

$("cal-fit").addEventListener("click", async () => {
  const bssid = $("cal-bssid").value;
  if (!bssid) return;
  const r = await fetch("/api/calibration", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ bssid, samples: stateUI.calSamples }),
  });
  const d = await r.json();
  if (d.ok) { stateUI.calSamples = []; renderSamples(); loadProfiles(); }
});

async function loadProfiles() {
  const r = await fetch("/api/calibration");
  const profiles = await r.json();
  const box = $("cal-profiles");
  box.innerHTML = "";
  for (const [b, p] of Object.entries(profiles)) {
    const div = document.createElement("div");
    div.className = "p" + (p.r2 >= 0.6 ? " good" : "");
    div.innerHTML = `<b class="mono">${b}</b> — A=${p.a} n=${p.n} R²=${p.r2}
      <span>(${p.samples} amostras)</span>
      <button data-b="${b}">✕</button>
      <div class="note">${p.note || ""}</div>`;
    div.querySelector("button").addEventListener("click", async () => {
      await fetch("/api/calibration/" + encodeURIComponent(b), { method: "DELETE" });
      loadProfiles();
    });
    box.appendChild(div);
  }
}

/* ---------------- Radar (canvas + spring layout) ---------------- */
const canvas = $("radar");
const ctx = canvas.getContext("2d");

function hashAngle(bssid) {
  let h = 0;
  for (let i = 0; i < bssid.length; i++) h = (h * 31 + bssid.charCodeAt(i)) >>> 0;
  return (h % 3600) / 3600 * Math.PI * 2;
}

function syncNodes() {
  const present = new Set();
  for (const ap of stateUI.aps) {
    present.add(ap.bssid);
    let node = stateUI.nodes.get(ap.bssid);
    if (!node) {
      const a = hashAngle(ap.bssid);
      node = { x: Math.cos(a), y: Math.sin(a), r: 1, tr: 1 };
      stateUI.nodes.set(ap.bssid, node);
    }
    node.ap = ap;
    node.dist = ap.distance;
  }
  for (const b of [...stateUI.nodes.keys()]) if (!present.has(b)) stateUI.nodes.delete(b);
}

function resize() {
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}
window.addEventListener("resize", resize);

function draw() {
  const rect = canvas.getBoundingClientRect();
  const W = rect.width, H = rect.height;
  const cx = W / 2, cy = H / 2;
  const R = Math.min(W, H) / 2 - 24;
  ctx.clearRect(0, 0, W, H);

  const dists = stateUI.aps.map((a) => a.distance).filter((d) => d != null);
  const maxDist = Math.max(10, ...dists);
  const scale = (R * 0.92) / maxDist;

  // anéis de distância
  ctx.strokeStyle = "#16261f"; ctx.fillStyle = "#3c5b4d"; ctx.font = "10px monospace";
  const rings = 4;
  for (let i = 1; i <= rings; i++) {
    const rr = (R * 0.92) * i / rings;
    ctx.beginPath(); ctx.arc(cx, cy, rr, 0, Math.PI * 2); ctx.stroke();
    ctx.fillText((maxDist * i / rings).toFixed(0) + "m", cx + 3, cy - rr + 11);
  }
  // eixos
  ctx.beginPath();
  ctx.moveTo(cx - R, cy); ctx.lineTo(cx + R, cy);
  ctx.moveTo(cx, cy - R); ctx.lineTo(cx, cy + R); ctx.stroke();

  // sweep
  if (stateUI.running) {
    stateUI.sweep = (stateUI.sweep + 0.02) % (Math.PI * 2);
    const g = ctx.createConicGradient(stateUI.sweep, cx, cy);
    g.addColorStop(0, "rgba(57,211,83,0.18)");
    g.addColorStop(0.08, "rgba(57,211,83,0)");
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(cx, cy, R * 0.92, 0, Math.PI * 2); ctx.fill();
  }

  // layout spring: repulsão entre nós, raio preso à distância estimada
  const nodes = [...stateUI.nodes.values()];
  for (let iter = 0; iter < 3; iter++) {
    for (let i = 0; i < nodes.length; i++) {
      let fx = 0, fy = 0;
      for (let j = 0; j < nodes.length; j++) {
        if (i === j) continue;
        let dx = nodes[i].x - nodes[j].x, dy = nodes[i].y - nodes[j].y;
        let d2 = dx * dx + dy * dy + 0.01;
        const f = 0.35 / d2;
        fx += dx / Math.sqrt(d2) * f; fy += dy / Math.sqrt(d2) * f;
      }
      nodes[i].x += fx; nodes[i].y += fy;
    }
  }
  // desenha nós
  for (const node of nodes) {
    const ap = node.ap; if (!ap) continue;
    const targetR = ap.distance != null ? Math.min(ap.distance * scale, R * 0.92) : R * 0.97;
    let ang = Math.atan2(node.y, node.x);
    node.r += (targetR - node.r) * 0.15;      // suaviza raio
    node.x = Math.cos(ang) * node.r;
    node.y = Math.sin(ang) * node.r;
    const px = cx + node.x, py = cy + node.y;

    const color = BAND_COLOR[ap.band] || "#8899aa";
    const strength = Math.max(0.25, Math.min(1, (ap.rssi + 90) / 55));
    ctx.beginPath(); ctx.arc(px, py, 4 + strength * 4, 0, Math.PI * 2);
    ctx.fillStyle = color; ctx.shadowColor = color; ctx.shadowBlur = 10;
    ctx.fill(); ctx.shadowBlur = 0;
    if (ap.calibrated) { ctx.strokeStyle = "#ffc132"; ctx.lineWidth = 2; ctx.stroke(); }
    if (ap.bssid === stateUI.selected || ap.bssid === stateUI.focusBssid) {
      ctx.strokeStyle = "#fff"; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.arc(px, py, 12, 0, Math.PI * 2); ctx.stroke();
    }
    // rótulo
    ctx.fillStyle = "#c9f2dd"; ctx.font = "10px monospace";
    const label = (ap.ssid || ap.bssid.slice(-8));
    const dtxt = ap.distance != null ? `  ${ap.distance.toFixed(1)}m` : "";
    ctx.fillText(label + dtxt, px + 8, py + 3);
    node._px = px; node._py = py;
  }

  // centro (scanner)
  ctx.beginPath(); ctx.arc(cx, cy, 5, 0, Math.PI * 2);
  ctx.fillStyle = "#39d353"; ctx.shadowColor = "#39d353"; ctx.shadowBlur = 14;
  ctx.fill(); ctx.shadowBlur = 0;
  ctx.strokeStyle = "#39d35355";
  ctx.beginPath(); ctx.arc(cx, cy, 9 + (Math.sin(Date.now() / 300) + 1) * 3, 0, Math.PI * 2); ctx.stroke();

  requestAnimationFrame(draw);
}

// clique no radar seleciona AP
canvas.addEventListener("click", (e) => {
  const rect = canvas.getBoundingClientRect();
  const mx = e.clientX - rect.left, my = e.clientY - rect.top;
  let best = null, bd = 400;
  for (const node of stateUI.nodes.values()) {
    if (node._px == null) continue;
    const d = (node._px - mx) ** 2 + (node._py - my) ** 2;
    if (d < bd) { bd = d; best = node.ap; }
  }
  if (best) selectAp(best.bssid);
});

/* ---------------- Init ---------------- */
resize();
requestAnimationFrame(draw);
connectWS();
loadInterfaces();
loadProfiles();
