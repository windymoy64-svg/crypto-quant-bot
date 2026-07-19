"use strict";

/**
 * Animated Office renderer.
 *
 * Layout: 3x2 grid of rooms + break room strip at bottom. Setiap agent
 * punya home desk di ruangannya. State working/idle/alert/break/offline
 * datang dari GET /api/office/state, dan animasi jalan-jalan agent
 * dihitung frame-by-frame di canvas 2D. Zero external asset.
 */

const CANVAS_W = 1280;
const CANVAS_H = 720;

const ROOM_LAYOUT = {
  pre_production: { x: 0, y: 0, w: 426, h: 260, label: "Pre-production", accent: "#f472b6" },
  scene_engine:   { x: 426, y: 0, w: 428, h: 260, label: "Scene Engine",  accent: "#60a5fa" },
  art_camera:     { x: 854, y: 0, w: 426, h: 260, label: "Art & Camera",  accent: "#a78bfa" },
  cut_qa:         { x: 0, y: 260, w: 426, h: 260, label: "Cut QA",        accent: "#f97316" },
  devsecops:      { x: 426, y: 260, w: 428, h: 260, label: "DevSecOps",   accent: "#38bdf8" },
  operations:     { x: 854, y: 260, w: 426, h: 260, label: "Operations",  accent: "#22c55e" },
  break_room:     { x: 0, y: 520, w: 1280, h: 200, label: "Break Room",   accent: "#f7c948" },
};

// Home desk (working position) + wander center untuk masing-masing agent
// Pre-production punya 2 desk (Rian kiri, Haru kanan).
const AGENT_HOME = {
  rian:  { room: "pre_production", desk: { x: 90,   y: 150 }, side: "left" },
  haru:  { room: "pre_production", desk: { x: 260,  y: 150 }, side: "right" },
  yuna:  { room: "scene_engine",   desk: { x: 640,  y: 150 }, side: "left" },
  miro:  { room: "art_camera",     desk: { x: 1080, y: 150 }, side: "left" },
  quinn: { room: "cut_qa",         desk: { x: 130,  y: 410 }, side: "left" },
  raven: { room: "devsecops",      desk: { x: 640,  y: 410 }, side: "left" },
  dami:  { room: "operations",     desk: { x: 1080, y: 410 }, side: "left" },
};

const ROOM_DOOR_X = {
  pre_production: 213,
  scene_engine: 640,
  art_camera: 1067,
  cut_qa: 213,
  devsecops: 640,
  operations: 1067,
};

// Break room spots (kalau lebih dari satu agent break, spread horizontal).
const BREAK_SPOTS = [
  { x: 140, y: 620 },
  { x: 320, y: 620 },
  { x: 500, y: 620 },
  { x: 700, y: 620 },
  { x: 900, y: 620 },
  { x: 1080, y: 620 },
  { x: 1220, y: 620 },
];

const STATUS_COLOR = {
  working: "#22c55e",
  idle: "#94a3b8",
  break: "#38bdf8",
  offline: "#475569",
  alert: "#ef4444",
};

const canvas = document.getElementById("office-canvas");
const ctx = canvas.getContext("2d");
ctx.imageSmoothingEnabled = false;

const state = {
  agents: [],           // hydrated agents dengan pos/vel/state
  byId: new Map(),
  breakAssigned: new Map(), // agentId -> break spot index
  lastFetchOk: false,
  lastUpdated: null,
};


// --- Sprite helpers (procedural pixel drawing) -------------------------------

/**
 * Gambar karakter chibi 16x24 pixel. Bob berdasarkan waktu supaya kelihatan
 * hidup saat berjalan.
 */
function drawSprite(x, y, color, facing, walking, tick) {
  const px = Math.round(x - 8);
  const py = Math.round(y - 22);
  const bob = walking ? Math.floor(tick / 6) % 2 : 0;
  // Shadow
  ctx.fillStyle = "rgba(0,0,0,0.35)";
  ctx.beginPath();
  ctx.ellipse(x, y + 2, 8, 3, 0, 0, Math.PI * 2);
  ctx.fill();
  // Body/shirt
  ctx.fillStyle = color;
  ctx.fillRect(px + 4, py + 10, 8, 8);
  // Head (skin)
  ctx.fillStyle = "#f4d1b4";
  ctx.fillRect(px + 5, py + 2, 6, 7);
  // Hair
  ctx.fillStyle = "#2b1d16";
  ctx.fillRect(px + 4, py, 8, 3);
  ctx.fillRect(px + 4, py + 2, 2, 3);
  ctx.fillRect(px + 10, py + 2, 2, 3);
  // Eyes (based on facing)
  ctx.fillStyle = "#12131a";
  if (facing === "left") {
    ctx.fillRect(px + 5, py + 5, 1, 1);
  } else if (facing === "right") {
    ctx.fillRect(px + 10, py + 5, 1, 1);
  } else {
    ctx.fillRect(px + 6, py + 5, 1, 1);
    ctx.fillRect(px + 9, py + 5, 1, 1);
  }
  // Arms
  ctx.fillStyle = shade(color, -20);
  ctx.fillRect(px + 3, py + 10, 1, 6);
  ctx.fillRect(px + 12, py + 10, 1, 6);
  // Legs alternating bob
  ctx.fillStyle = "#2f3346";
  ctx.fillRect(px + 5, py + 18, 2, 4 + bob);
  ctx.fillRect(px + 9, py + 18, 2, 4 + (1 - bob));
}

function shade(hex, delta) {
  const c = hex.replace("#", "");
  const r = Math.max(0, Math.min(255, parseInt(c.slice(0, 2), 16) + delta));
  const g = Math.max(0, Math.min(255, parseInt(c.slice(2, 4), 16) + delta));
  const b = Math.max(0, Math.min(255, parseInt(c.slice(4, 6), 16) + delta));
  return `rgb(${r},${g},${b})`;
}



// --- Room + world drawing ----------------------------------------------------

function drawRoom(room, key) {
  const { x, y, w, h, label, accent } = room;
  ctx.fillStyle = key === "break_room" ? "#2a2419" : "#1a1c26";
  ctx.fillRect(x, y, w, h);
  const tile = 32;
  for (let ty = y; ty < y + h; ty += tile) {
    for (let tx = x; tx < x + w; tx += tile) {
      if (((tx / tile + ty / tile) & 1) === 0) {
        ctx.fillStyle = "rgba(255,255,255,0.02)";
        ctx.fillRect(tx, ty, tile, tile);
      }
    }
  }
  ctx.strokeStyle = "#303346";
  ctx.lineWidth = 2;
  ctx.strokeRect(x + 1, y + 1, w - 2, h - 2);
  // Label ribbon
  ctx.fillStyle = accent;
  const labelW = Math.max(120, label.length * 7 + 20);
  ctx.fillRect(x + w / 2 - labelW / 2, y + 6, labelW, 18);
  ctx.fillStyle = "#12131a";
  ctx.font = "bold 11px monospace";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(label.toUpperCase(), x + w / 2, y + 15);
}

function drawDesk(x, y, accent) {
  ctx.fillStyle = "#8b6f47";
  ctx.fillRect(x - 24, y + 6, 48, 14);
  ctx.fillStyle = "#6b5436";
  ctx.fillRect(x - 24, y + 18, 48, 4);
  // Monitor
  ctx.fillStyle = "#0f172a";
  ctx.fillRect(x - 12, y - 8, 24, 14);
  ctx.fillStyle = accent;
  ctx.fillRect(x - 10, y - 6, 20, 10);
  // Stand
  ctx.fillStyle = "#374151";
  ctx.fillRect(x - 3, y + 6, 6, 3);
}

function drawCouch(x, y) {
  ctx.fillStyle = "#5b4b8a";
  ctx.fillRect(x - 34, y - 4, 68, 22);
  ctx.fillStyle = "#3f356b";
  ctx.fillRect(x - 34, y - 12, 68, 10);
}

function drawDoor(x, y) {
  // Open a visible passage in the horizontal room border.
  ctx.fillStyle = "#151721";
  ctx.fillRect(x - 18, y - 4, 36, 8);
  ctx.fillStyle = "#9a7b4f";
  ctx.fillRect(x - 22, y - 5, 4, 10);
  ctx.fillRect(x + 18, y - 5, 4, 10);
}

function drawWorld() {
  ctx.fillStyle = "#0d0e15";
  ctx.fillRect(0, 0, CANVAS_W, CANVAS_H);
  for (const [key, room] of Object.entries(ROOM_LAYOUT)) {
    drawRoom(room, key);
  }
  for (const x of [213, 640, 1067]) {
    drawDoor(x, 260);
    drawDoor(x, 520);
  }
  for (const home of Object.values(AGENT_HOME)) {
    const room = ROOM_LAYOUT[home.room];
    drawDesk(home.desk.x, home.desk.y, room.accent);
  }
  // Couches in break room
  drawCouch(160, 630);
  drawCouch(1120, 630);
}

// --- Speech bubble -----------------------------------------------------------

function drawBubble(x, y, text) {
  if (!text) return;
  ctx.font = "10px monospace";
  const padX = 6;
  const padY = 4;
  const metrics = ctx.measureText(text);
  const w = Math.min(220, metrics.width + padX * 2);
  const h = 18;
  const bx = Math.round(x - w / 2);
  const by = Math.round(y - 42);
  ctx.fillStyle = "rgba(15,17,25,0.92)";
  ctx.strokeStyle = "#f7c948";
  ctx.lineWidth = 1;
  ctx.fillRect(bx, by, w, h);
  ctx.strokeRect(bx + 0.5, by + 0.5, w - 1, h - 1);
  // Tail
  ctx.beginPath();
  ctx.moveTo(x - 3, by + h);
  ctx.lineTo(x + 3, by + h);
  ctx.lineTo(x, by + h + 4);
  ctx.closePath();
  ctx.fillStyle = "rgba(15,17,25,0.92)";
  ctx.fill();
  // Text
  ctx.fillStyle = "#f7c948";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(truncate(text, 26), bx + w / 2, by + h / 2);
}

function truncate(s, n) {
  return s.length > n ? s.slice(0, n - 3) + "..." : s;
}

function drawAlertMark(x, y) {
  ctx.fillStyle = "#ef4444";
  ctx.fillRect(x - 2, y - 34, 4, 8);
  ctx.fillRect(x - 2, y - 24, 4, 3);
}


// --- Agent state + movement --------------------------------------------------

/**
 * Determine target position for an agent based on status.
 * - working / alert: home desk (sit facing monitor)
 * - break: assigned break spot
 * - idle: wander around home room
 * - offline: hidden (dimmed at desk)
 */
function computeTarget(agent, breakIndex) {
  const home = AGENT_HOME[agent.id];
  const room = ROOM_LAYOUT[home.room];
  if (agent.path && agent.path.length > 0) {
    if (_reached(agent, agent.path[0])) agent.path.shift();
    if (agent.path.length > 0) {
      return { ...agent.path[0], facing: null, sitting: false };
    }
  }
  if (agent.status === "working" || agent.status === "alert" || agent.status === "offline") {
    return { x: home.desk.x, y: home.desk.y + 30, facing: "up", sitting: true };
  }
  if (agent.status === "break") {
    const spot = BREAK_SPOTS[breakIndex % BREAK_SPOTS.length];
    return { x: spot.x, y: spot.y, facing: "down", sitting: true };
  }
  // idle: wander around the room
  const pad = 40;
  if (!agent._wanderTarget || _reached(agent, agent._wanderTarget)) {
    agent._wanderTarget = {
      x: room.x + pad + Math.random() * (room.w - pad * 2),
      y: room.y + pad + 40 + Math.random() * (room.h - pad * 2 - 40),
    };
  }
  return { x: agent._wanderTarget.x, y: agent._wanderTarget.y, facing: null, sitting: false };
}

function routeBetweenHomeAndBreak(agentId, breakIndex, toBreak) {
  const home = AGENT_HOME[agentId];
  const doorX = ROOM_DOOR_X[home.room];
  const breakSpot = BREAK_SPOTS[breakIndex % BREAK_SPOTS.length];
  const topRoom = home.room === "pre_production" ||
    home.room === "scene_engine" || home.room === "art_camera";
  const route = [];

  if (topRoom) {
    route.push(
      { x: doorX, y: 238 },
      { x: doorX, y: 282 },
    );
  }
  route.push(
    { x: doorX, y: 498 },
    { x: doorX, y: 542 },
    { x: breakSpot.x, y: breakSpot.y },
  );

  if (toBreak) return route;
  const returnRoute = route.slice(0, -1).reverse();
  returnRoute.push({ x: home.desk.x, y: home.desk.y + 30 });
  return returnRoute;
}

function _reached(agent, target) {
  const dx = target.x - agent.x;
  const dy = target.y - agent.y;
  return Math.hypot(dx, dy) < 6;
}

function stepAgent(agent, dt, tick) {
  const breakIndex = state.breakAssigned.get(agent.id) ?? 0;
  const target = computeTarget(agent, breakIndex);
  const dx = target.x - agent.x;
  const dy = target.y - agent.y;
  const dist = Math.hypot(dx, dy);
  const speed = agent.status === "working" || agent.status === "break" ? 60 : 45;
  if (dist > 2) {
    const vx = (dx / dist) * speed;
    const vy = (dy / dist) * speed;
    const step = Math.min(dist, speed * dt);
    agent.x += (vx / speed) * step;
    agent.y += (vy / speed) * step;
    agent.walking = true;
    if (Math.abs(dx) > Math.abs(dy)) {
      agent.facing = dx > 0 ? "right" : "left";
    } else {
      agent.facing = dy > 0 ? "down" : "up";
    }
  } else {
    agent.walking = false;
    if (target.facing) agent.facing = target.facing;
  }
  agent.sitting = target.sitting && !agent.walking;
  agent.tick = tick;
}

// --- Rendering agents --------------------------------------------------------

function drawAgent(agent) {
  const dim = agent.status === "offline";
  ctx.save();
  if (dim) ctx.globalAlpha = 0.35;
  drawSprite(agent.x, agent.y, agent.color, agent.facing || "down", agent.walking, agent.tick);
  ctx.restore();
  // Name plate
  ctx.font = "bold 10px monospace";
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  const nameW = agent.name.length * 6 + 10;
  const ny = Math.round(agent.y + 6);
  ctx.fillStyle = "rgba(15,17,25,0.9)";
  ctx.fillRect(Math.round(agent.x - nameW / 2), ny, nameW, 12);
  ctx.strokeStyle = agent.color;
  ctx.lineWidth = 1;
  ctx.strokeRect(Math.round(agent.x - nameW / 2) + 0.5, ny + 0.5, nameW - 1, 11);
  ctx.fillStyle = agent.color;
  ctx.fillText(agent.name, agent.x, ny + 1);
  // Role sub-label
  ctx.fillStyle = "#98a0b4";
  ctx.font = "9px monospace";
  ctx.fillText(agent.role, agent.x, ny + 12);
  // Speech bubble jika lagi working/alert dan sudah sampai desk (sitting)
  if ((agent.status === "working" || agent.status === "alert") && agent.sitting) {
    drawBubble(agent.x, agent.y, agent.task);
  }
  if (agent.has_alert) {
    drawAlertMark(agent.x, agent.y);
  }
}

// --- Data sync ---------------------------------------------------------------

function assignBreakSpots(agents) {
  state.breakAssigned.clear();
  let i = 0;
  for (const agent of agents) {
    if (agent.status === "break") {
      state.breakAssigned.set(agent.id, i++);
    }
  }
}

function hydrate(agents) {
  assignBreakSpots(agents);
  for (const incoming of agents) {
    if (!AGENT_HOME[incoming.id]) continue;
    const existing = state.byId.get(incoming.id);
    if (existing) {
      const previousStatus = existing.status;
      Object.assign(existing, incoming);
      if (incoming.status !== previousStatus) {
        const breakIndex = state.breakAssigned.get(incoming.id) ?? 0;
        if (incoming.status === "break") {
          existing.path = routeBetweenHomeAndBreak(incoming.id, breakIndex, true);
        } else if (previousStatus === "break") {
          existing.path = routeBetweenHomeAndBreak(incoming.id, breakIndex, false);
        } else {
          existing.path = [];
        }
        existing._wanderTarget = null;
      }
    } else {
      const home = AGENT_HOME[incoming.id];
      const spawn = { x: home.desk.x, y: home.desk.y + 30 };
      const agent = {
        ...incoming,
        x: spawn.x,
        y: spawn.y,
        facing: "down",
        walking: false,
        sitting: true,
        tick: 0,
        path: incoming.status === "break"
          ? routeBetweenHomeAndBreak(
              incoming.id,
              state.breakAssigned.get(incoming.id) ?? 0,
              true,
            )
          : [],
      };
      state.byId.set(incoming.id, agent);
      state.agents.push(agent);
    }
  }
}




// --- Legend panel + KPI ------------------------------------------------------

function renderLegend() {
  const list = document.getElementById("agent-list");
  const cards = state.agents.map((agent) => {
    const li = document.createElement("li");
    li.className = "agent-card";
    li.dataset.status = agent.status;
    li.innerHTML = `
      <span class="agent-dot" style="background:${agent.color}"></span>
      <div class="agent-body">
        <strong>${escapeHtml(agent.name)} <small style="color:#98a0b4">${escapeHtml(agent.job)}</small></strong>
        <span>${escapeHtml(agent.task)}</span>
        <span style="color:#64748b">${escapeHtml(agent.detail || "")}</span>
      </div>
      <span class="agent-status">${agent.status}</span>
    `;
    return li;
  });
  list.replaceChildren(...cards);
}

function updateKpi(kpi) {
  for (const key of ["staff", "working", "in_progress", "done"]) {
    const el = document.querySelector(`[data-kpi="${key}"]`);
    if (el) el.textContent = String(kpi[key] ?? "--");
  }
}

function setConnStatus(ok) {
  const el = document.getElementById("conn-status");
  if (!el) return;
  el.dataset.status = ok ? "ok" : "error";
  el.querySelector(".kpi-value").textContent = ok ? "LIVE" : "ERR";
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

// --- Fetch + render loop -----------------------------------------------------

async function pollState() {
  try {
    const res = await fetch("/api/office/state", { credentials: "same-origin" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    hydrate(data.agents || []);
    updateKpi(data.kpi || {});
    renderLegend();
    setConnStatus(true);
    const el = document.getElementById("last-updated");
    if (el && data.generated_at) {
      const t = new Date(data.generated_at);
      el.textContent = `Updated ${t.toLocaleTimeString()}`;
    }
    state.lastFetchOk = true;
  } catch (err) {
    console.warn("office state fetch failed", err);
    setConnStatus(false);
    state.lastFetchOk = false;
  }
}

let lastFrame = performance.now();
let tick = 0;

function loop(now) {
  const dt = Math.min(0.1, (now - lastFrame) / 1000);
  lastFrame = now;
  tick += 1;
  drawWorld();
  for (const agent of state.agents) {
    stepAgent(agent, dt, tick);
  }
  // Sort by y so front agents overlap back agents
  const sorted = [...state.agents].sort((a, b) => a.y - b.y);
  for (const agent of sorted) drawAgent(agent);
  requestAnimationFrame(loop);
}

function resizeCanvasToDisplay() {
  // Keep the internal render at 1280x720 for consistent pixel scale.
  // CSS preserves the display aspect ratio while the canvas stays pixelated.
  canvas.width = CANVAS_W;
  canvas.height = CANVAS_H;
  ctx.imageSmoothingEnabled = false;
}

window.addEventListener("resize", resizeCanvasToDisplay);
resizeCanvasToDisplay();

pollState();
setInterval(pollState, 2000);
requestAnimationFrame(loop);

