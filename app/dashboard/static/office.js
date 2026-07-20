"use strict";

/**
 * Animated Office renderer — Harvest Moon PS1 style.
 *
 * Kantor digambar sebagai tile grid 32px (top-down, pixelated, tanpa smoothing)
 * lengkap dengan tembok, pintu, meja + komputer, dan dekorasi. Karakter chibi
 * berjalan mengikuti ALUR KERJA 4 CORE AGENTS yang sebenarnya:
 *
 *   Chart (Yuna)     -> Learning (Nara)  : kirim chart reading/observation
 *   Chart (Yuna)     -> Decision (Miro)  : kirim reading untuk diputus
 *   Learning (Nara)  -> Decision (Miro)  : kirim insight journal
 *   Decision (Miro)  -> Executor (Dami)  : kirim keputusan eksekusi
 *   Executor (Dami)  -> Learning (Nara)  : kirim feedback eksekusi
 *
 * Setiap kunjungan = berjalan ke meja target + typing + bubble singkat.
 * State datang dari GET /api/office/state. Visual memakai asset MIT dari pixel-agents.
 */

const CANVAS_W = 1280;
const CANVAS_H = 720;
const TILE = 32;
const OFFICIAL_TILE = 16;
const OFFICIAL_ZOOM = 2;
const OFFICIAL_LAYOUT_URL = "/static/pixel-agents-assets/default-layout-1.json";
const FRAME_MS = window.matchMedia("(prefers-reduced-motion: reduce)").matches
  ? 1000 / 12
  : 1000 / 30;
const POLL_MS = 2000;

// --- Tile map ----------------------------------------------------------------
// F = floor room, C = corridor, W = wall, D = door, B = break room floor.
// Dibangun secara programatik supaya lebar baris dijamin konsisten (40 tile).
function _roomRow(doors) {
  // Ruangan: segmen 12 + gap 2 + segmen 12 + gap 2 + segmen 10 = 38; +2 dinding = 40.
  const segs = ["F".repeat(12), "F".repeat(12), "F".repeat(10)];
  const gaps = ["WW", "WW"];
  if (doors) {
    gaps[0] = "DW";
    gaps[1] = "DW";
  }
  return "W" + segs[0] + gaps[0] + segs[1] + gaps[1] + segs[2] + "W";
}

function _openRow(fill) {
  // Koridor/break room: 12 + 2(pintu) + 12 + 2(pintu) + 10 = 38; +2 dinding = 40.
  return "W" + fill.repeat(12) + "DD" + fill.repeat(12) + "DD" + fill.repeat(10) + "W";
}

const MAP = [
  "W".repeat(40),
  _roomRow(false),
  _roomRow(false),
  _roomRow(false),
  _roomRow(false),
  _roomRow(true),
  _roomRow(false),
  _roomRow(false),
  _roomRow(false),
  _openRow("C"),
  _openRow("C"),
  _roomRow(false),
  _roomRow(false),
  _roomRow(false),
  _roomRow(false),
  _roomRow(true),
  _roomRow(false),
  _roomRow(false),
  _roomRow(false),
  _openRow("B"),
  "W" + "B".repeat(38) + "W",
  "W".repeat(40),
];

const ROOM_INFO = {
  chart_room:    { label: "CHART",    accent: "#a78bfa", x: 145, y: 0,   w: 528, h: 300 },
  learning_room: { label: "LEARNING", accent: "#34d399", x: 145, y: 300, w: 528, h: 212 },
  executor_room: { label: "EXECUTOR", accent: "#6ee7b7", x: 673, y: 0,   w: 433, h: 208 },
  decision_room: { label: "DECISION", accent: "#fbbf24", x: 718, y: 230, w: 388, h: 282 },
};

const TOP_ROOMS = new Set(["chart_room", "executor_room"]);
const DOOR_X = {
  chart_room: 672,
  learning_room: 672,
  executor_room: 672,
  decision_room: 718,
};

// 4 core agents only: Chart, Learning, Decision, Executor.
const AGENT_HOME = {
  yuna: { room: "chart_room",    desk: { x: 400, y: 400 }, chair: { x: 416, y: 472 }, facing: "up", official: true },
  nara: { room: "learning_room", desk: { x: 528, y: 400 }, chair: { x: 544, y: 472 }, facing: "up", official: true },
  dami: { room: "executor_room", desk: { x: 448, y: 536 }, chair: { x: 416, y: 536 }, facing: "right", official: true },
  miro: { room: "decision_room", desk: { x: 448, y: 600 }, chair: { x: 512, y: 600 }, facing: "left", official: true },
};

const AGENT_SHORT_NAME = {
  yuna: "Yuna",
  nara: "Nara",
  miro: "Miro",
  dami: "Dami",
};

const BREAK_SPOTS = [
  { x: 784, y: 488 }, { x: 816, y: 488 },
];

const STATUS_COLOR = {
  working: "#22c55e",
  idle: "#94a3b8",
  break: "#38bdf8",
  offline: "#475569",
  alert: "#ef4444",
};

const canvas = document.getElementById("office-canvas");
// Every frame paints an opaque background, so an alpha backing buffer only
// consumes memory/bandwidth without contributing to the final image.
const ctx = canvas.getContext("2d", { alpha: false, desynchronized: true });
ctx.imageSmoothingEnabled = false;

const state = {
  agents: [],
  byId: new Map(),
  breakAssigned: new Map(),
  lastFetchOk: false,
  workflowIndex: 0,
  nextWorkflowAt: 0,
  pollInFlight: false,
  pollTimerId: 0,
  rafId: 0,
  pageVisible: true,
  renderOrder: [],
  sceneOrder: [],
  officialLayout: null,
};


// --- Pixel Agents open-source assets (MIT) -----------------------------------

const PA_ASSET_BASE = "/static/pixel-agents-assets";
const PA_IMAGES = new Map();
const OFFICIAL_FLOOR_ASSETS = {
  1: `${PA_ASSET_BASE}/floors/floor_0.png`,
  7: `${PA_ASSET_BASE}/floors/floor_6.png`,
  9: `${PA_ASSET_BASE}/floors/floor_8.png`,
};
const OFFICIAL_WALL_ASSET = `${PA_ASSET_BASE}/walls/wall_0.png`;

const OFFICIAL_FURNITURE_GROUP = {
  TABLE_FRONT: "TABLE_FRONT",
  COFFEE_TABLE: "COFFEE_TABLE",
  SOFA_SIDE: "SOFA", SOFA_BACK: "SOFA", SOFA_FRONT: "SOFA",
  HANGING_PLANT: "HANGING_PLANT", DOUBLE_BOOKSHELF: "DOUBLE_BOOKSHELF",
  SMALL_PAINTING: "SMALL_PAINTING", SMALL_PAINTING_2: "SMALL_PAINTING_2",
  CLOCK: "CLOCK", PLANT: "PLANT", PLANT_2: "PLANT_2", COFFEE: "COFFEE",
  WOODEN_CHAIR_SIDE: "WOODEN_CHAIR", DESK_FRONT: "DESK",
  CUSHIONED_BENCH: "CUSHIONED_BENCH", PC_FRONT_OFF: "PC", PC_SIDE: "PC",
  LARGE_PAINTING: "LARGE_PAINTING", BIN: "BIN",
  SMALL_TABLE_FRONT: "SMALL_TABLE_FRONT", SMALL_TABLE_SIDE: "SMALL_TABLE_SIDE",
};

function officialFurnitureUrl(type) {
  const assetId = type.split(":", 1)[0];
  const folder = OFFICIAL_FURNITURE_GROUP[assetId];
  return folder ? `${PA_ASSET_BASE}/furniture/${folder}/${assetId}.png` : null;
}

async function loadOfficialLayout() {
  try {
    const response = await fetch(OFFICIAL_LAYOUT_URL, { credentials: "same-origin" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const layout = await response.json();
    if (layout.cols !== 21 || layout.rows !== 22 || !Array.isArray(layout.tiles)) {
      throw new Error("invalid official layout");
    }
    state.officialLayout = layout;
    const officialUrls = [
      ...Object.values(OFFICIAL_FLOOR_ASSETS),
      OFFICIAL_WALL_ASSET,
      ...(layout.furniture || []).map((item) => officialFurnitureUrl(item.type)),
    ];
    for (const url of officialUrls) {
      if (!url || PA_IMAGES.has(url)) continue;
      const img = new Image();
      img.onload = () => { img.loaded = true; };
      img.onerror = () => { img.failed = true; };
      img.src = url;
      PA_IMAGES.set(url, img);
    }
  } catch (error) {
    console.warn("official Pixel Agents layout failed to load", error);
  }
}

const CHARACTER_SHEETS = {
  yuna: `${PA_ASSET_BASE}/characters/char_0.png`,
  nara: `${PA_ASSET_BASE}/characters/char_1.png`,
  miro: `${PA_ASSET_BASE}/characters/char_2.png`,
  dami: `${PA_ASSET_BASE}/characters/char_3.png`,
};

const FURNITURE_ASSETS = {
  deskFront: `${PA_ASSET_BASE}/furniture/DESK/DESK_FRONT.png`,
  deskSide: `${PA_ASSET_BASE}/furniture/DESK/DESK_SIDE.png`,
  pcFront1: `${PA_ASSET_BASE}/furniture/PC/PC_FRONT_ON_1.png`,
  pcFront2: `${PA_ASSET_BASE}/furniture/PC/PC_FRONT_ON_2.png`,
  pcFront3: `${PA_ASSET_BASE}/furniture/PC/PC_FRONT_ON_3.png`,
  pcSide: `${PA_ASSET_BASE}/furniture/PC/PC_SIDE.png`,
  bookshelf: `${PA_ASSET_BASE}/furniture/BOOKSHELF/BOOKSHELF.png`,
  doubleBookshelf: `${PA_ASSET_BASE}/furniture/DOUBLE_BOOKSHELF/DOUBLE_BOOKSHELF.png`,
  plant: `${PA_ASSET_BASE}/furniture/PLANT/PLANT.png`,
  largePlant: `${PA_ASSET_BASE}/furniture/LARGE_PLANT/LARGE_PLANT.png`,
  sofaFront: `${PA_ASSET_BASE}/furniture/SOFA/SOFA_FRONT.png`,
  sofaSide: `${PA_ASSET_BASE}/furniture/SOFA/SOFA_SIDE.png`,
  tableFront: `${PA_ASSET_BASE}/furniture/TABLE_FRONT/TABLE_FRONT.png`,
  coffeeTable: `${PA_ASSET_BASE}/furniture/COFFEE_TABLE/COFFEE_TABLE.png`,
  cushionedChairFront: `${PA_ASSET_BASE}/furniture/CUSHIONED_CHAIR/CUSHIONED_CHAIR_FRONT.png`,
  cushionedChairBack: `${PA_ASSET_BASE}/furniture/CUSHIONED_CHAIR/CUSHIONED_CHAIR_BACK.png`,
  cushionedChairSide: `${PA_ASSET_BASE}/furniture/CUSHIONED_CHAIR/CUSHIONED_CHAIR_SIDE.png`,
  smallPainting: `${PA_ASSET_BASE}/furniture/SMALL_PAINTING/SMALL_PAINTING.png`,
  largePainting: `${PA_ASSET_BASE}/furniture/LARGE_PAINTING/LARGE_PAINTING.png`,
  whiteboard: `${PA_ASSET_BASE}/furniture/WHITEBOARD/WHITEBOARD.png`,
  clock: `${PA_ASSET_BASE}/furniture/CLOCK/CLOCK.png`,
};

function preloadPixelAgentAssets() {
  // Load only assets used by this fixed four-agent layout. The repository has
  // many optional furniture variants; loading all of them would waste RAM.
  const urls = [
    ...Object.values(CHARACTER_SHEETS),
    FURNITURE_ASSETS.deskFront,
    FURNITURE_ASSETS.deskSide,
    FURNITURE_ASSETS.pcFront1,
    FURNITURE_ASSETS.pcFront2,
    FURNITURE_ASSETS.pcFront3,
    FURNITURE_ASSETS.pcSide,
    FURNITURE_ASSETS.bookshelf,
    FURNITURE_ASSETS.doubleBookshelf,
    FURNITURE_ASSETS.plant,
    FURNITURE_ASSETS.sofaSide,
    FURNITURE_ASSETS.tableFront,
    FURNITURE_ASSETS.cushionedChairFront,
    FURNITURE_ASSETS.cushionedChairSide,
    FURNITURE_ASSETS.largePainting,
    FURNITURE_ASSETS.whiteboard,
    FURNITURE_ASSETS.clock,
  ];
  for (const url of urls) {
    if (PA_IMAGES.has(url)) continue;
    const img = new Image();
    img.onload = () => { img.loaded = true; };
    img.onerror = () => { img.failed = true; };
    img.src = url;
    PA_IMAGES.set(url, img);
  }
}

function getAsset(url) {
  const img = PA_IMAGES.get(url);
  return img && img.complete && !img.failed ? img : null;
}

function drawAsset(url, x, y, w, h, flip = false) {
  const img = getAsset(url);
  if (!img) return false;
  ctx.save();
  ctx.imageSmoothingEnabled = false;
  if (flip) {
    ctx.translate(x + w, y);
    ctx.scale(-1, 1);
    ctx.drawImage(img, 0, 0, w, h);
  } else {
    ctx.drawImage(img, x, y, w, h);
  }
  ctx.restore();
  return true;
}

// --- Task choreography ---------------------------------------------------------

let taskSeq = 0;

function makeTask(agentId, toAgentId, label, bubble) {
  return { id: ++taskSeq, agentId, toAgentId, label, bubble, phase: "to", timer: 0, path: [] };
}

/** Titik berdiri di depan meja agent target. */
function standPointOf(toAgentId) {
  const to = AGENT_HOME[toAgentId];
  return { x: to.desk.x, y: to.desk.y + 46 };
}

/** Posisi lantai di dalam ruangan tepat di sisi pintu (untuk waypoint lewat). */
function doorApproach(room) {
  const point = {
    chart_room: { x: 416, y: 504 },
    learning_room: { x: 544, y: 504 },
    executor_room: { x: 480, y: 536 },
    decision_room: { x: 480, y: 600 },
  }[room];
  return point || { x: 480, y: 568 };
}


/** Rute jalan dari posisi agent ke meja agent lain (lewat koridor tengah). */
function routeToAgent(agent, toAgentId) {
  const from = AGENT_HOME[agent.id];
  const to = AGENT_HOME[toAgentId];
  const stand = standPointOf(toAgentId);
  if (from.room === to.room) return [stand];
  const hub = { x: 480, y: 568 };
  return [doorApproach(from.room), hub, doorApproach(to.room), stand];
}


function roomOf(x, y) {
  for (const [key, info] of Object.entries(ROOM_INFO)) {
    if (x >= info.x && x <= info.x + info.w && y >= info.y && y <= info.y + info.h) return key;
  }
  return null;
}


/** Rute pulang ke kursi sendiri dari ruangan mana pun (termasuk koridor). */
function routeHome(agent) {
  const home = AGENT_HOME[agent.id];
  if (roomOf(agent.x, agent.y) === home.room) {
    return [{ x: home.chair.x, y: home.chair.y }];
  }
  return [{ x: 480, y: 568 }, doorApproach(home.room), { x: home.chair.x, y: home.chair.y }];
}


/** Rute ke break room (dipakai saat status berubah jadi break). */
function routeToBreak(agent) {
  const idx = state.breakAssigned.get(agent.id) ?? 0;
  const spot = BREAK_SPOTS[idx % BREAK_SPOTS.length];
  return [doorApproach(AGENT_HOME[agent.id].room), { x: 480, y: 568 }, spot];
}


function enqueueTask(agent, toAgentId, label, bubble) {
  if (!agent || agent.status === "offline") return;
  const target = state.byId.get(toAgentId);
  // An offline target still exists in the office. The sender may deliver a
  // decision/report to it; the bubble will explain that execution is locked.
  if (!target) return;
  if (agent.task && agent.task.phase !== "done") {
    if (!agent.queuedTask) agent.queuedTask = makeTask(agent.id, toAgentId, label, bubble);
    return;
  }
  agent.task = makeTask(agent.id, toAgentId, label, bubble);
}


// --- Pixel sprite drawing (Harvest Moon-ish chibi) -----------------------------

function drawSprite(x, y, color, facing, walking, typing, tick, holdingDoc, agentId = "yuna") {
  const sheetUrl = CHARACTER_SHEETS[agentId] || CHARACTER_SHEETS.yuna;
  const sheet = getAsset(sheetUrl);
  const frameW = 16;
  const frameH = 32;
  const scale = 2;
  const drawW = frameW * scale;
  const drawH = frameH * scale;
  // Pixel Agents' official character sheet layout is 7 frames per direction:
  // walk [0..2], typing [3..4], reading [5..6]. The three source rows are
  // down, up, right; left is the mirrored right row.
  const rowByFacing = { down: 0, up: 1, right: 2, left: 2 };
  const srcRow = rowByFacing[facing] ?? rowByFacing.down;
  let frame = 0;
  if (walking) {
    const walk = [0, 1, 2, 1];
    frame = walk[Math.floor(tick / 8) % walk.length];
  } else if (holdingDoc) {
    frame = 5 + (Math.floor(tick / 20) % 2);
  } else if (typing) {
    frame = 3 + (Math.floor(tick / 22) % 2);
  } else {
    // Official Pixel Agents idle pose is the middle walking frame.
    frame = 1;
  }

  // shadow
  ctx.fillStyle = "rgba(0,0,0,0.35)";
  ctx.beginPath();
  ctx.ellipse(Math.round(x), Math.round(y) + 4, 13, 5, 0, 0, Math.PI * 2);
  ctx.fill();

  if (sheet) {
    ctx.save();
    ctx.imageSmoothingEnabled = false;
    const dx = Math.round(x - drawW / 2);
    const dy = Math.round(y - drawH + 8);
    if (facing === "left") {
      ctx.translate(dx + drawW, dy);
      ctx.scale(-1, 1);
      ctx.drawImage(sheet, frame * frameW, srcRow * frameH, frameW, frameH, 0, 0, drawW, drawH);
    } else {
      ctx.drawImage(sheet, frame * frameW, srcRow * frameH, frameW, frameH, dx, dy, drawW, drawH);
    }
    ctx.restore();
  } else {
    // fallback if PNG asset has not loaded yet
    ctx.fillStyle = color;
    ctx.fillRect(Math.round(x - 9), Math.round(y - 36), 18, 28);
    ctx.fillStyle = "#f6d5b8";
    ctx.fillRect(Math.round(x - 7), Math.round(y - 52), 14, 14);
  }

  if (holdingDoc) {
    ctx.fillStyle = "#f8fafc";
    ctx.fillRect(Math.round(x + 13), Math.round(y - 28), 10, 14);
    ctx.fillStyle = "#94a3b8";
    ctx.fillRect(Math.round(x + 15), Math.round(y - 24), 6, 1);
    ctx.fillRect(Math.round(x + 15), Math.round(y - 20), 6, 1);
  }
}

function shade(hex, delta) {
  const c = hex.replace("#", "");
  const r = Math.max(0, Math.min(255, parseInt(c.slice(0, 2), 16) + delta));
  const g = Math.max(0, Math.min(255, parseInt(c.slice(2, 4), 16) + delta));
  const b = Math.max(0, Math.min(255, parseInt(c.slice(4, 6), 16) + delta));
  return `rgb(${r},${g},${b})`;
}

// --- World drawing (tiles, walls, furniture) -----------------------------------

function drawTiles() {
  for (let ty = 0; ty < MAP.length; ty++) {
    for (let tx = 0; tx < MAP[ty].length; tx++) {
      const ch = MAP[ty][tx];
      const x = tx * TILE;
      const y = ty * TILE;
      if (ch === "W") {
        ctx.fillStyle = "#101220";
        ctx.fillRect(x, y, TILE, TILE);
        ctx.fillStyle = "#1d2033";
        ctx.fillRect(x, y, TILE, 6);
        ctx.fillStyle = "rgba(255,255,255,0.04)";
        ctx.fillRect(x, y + 6, TILE, 1);
      } else if (ch === "D") {
        ctx.fillStyle = "#241d18";
        ctx.fillRect(x, y, TILE, TILE);
        ctx.fillStyle = "#8a6b43";
        ctx.fillRect(x + 6, y + 2, TILE - 12, TILE - 4);
        ctx.fillStyle = "#6b5436";
        ctx.fillRect(x + 6, y + 2, TILE - 12, 3);
        ctx.fillStyle = "#d9b36c";
        ctx.fillRect(x + TILE / 2 - 1, y + TILE / 2 - 1, 2, 2);
      } else if (ch === "C") {
        ctx.fillStyle = "#7d5f3d";
        ctx.fillRect(x, y, TILE, TILE);
        ctx.fillStyle = "#6d5233";
        ctx.fillRect(x, y + TILE - 3, TILE, 3);
        ctx.fillStyle = "rgba(255,255,255,0.05)";
        ctx.fillRect(x, y, TILE, 2);
        if ((tx & 1) === 0) {
          ctx.fillStyle = "rgba(0,0,0,0.08)";
          ctx.fillRect(x + TILE - 2, y + 4, 2, TILE - 8);
        }
      } else if (ch === "B") {
        ctx.fillStyle = "#4a3b55";
        ctx.fillRect(x, y, TILE, TILE);
        if (((tx + ty) & 1) === 0) {
          ctx.fillStyle = "rgba(255,255,255,0.03)";
          ctx.fillRect(x + 4, y + 4, TILE - 8, TILE - 8);
        }
      } else {
        ctx.fillStyle = ((tx + ty) & 1) === 0 ? "#2a2d3f" : "#262939";
        ctx.fillRect(x, y, TILE, TILE);
      }
    }
  }
}

function drawRoomLabels() {
  for (const info of Object.values(ROOM_INFO)) {
    const cx = (info.tx + info.tw / 2) * TILE;
    const y = info.ty * TILE + 8;
    ctx.font = "bold 10px monospace";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    const w = Math.max(110, info.label.length * 7 + 18);
    ctx.fillStyle = "rgba(13,14,21,0.85)";
    ctx.fillRect(cx - w / 2, y, w, 15);
    ctx.strokeStyle = info.accent;
    ctx.lineWidth = 1;
    ctx.strokeRect(cx - w / 2 + 0.5, y + 0.5, w - 1, 14);
    ctx.fillStyle = info.accent;
    ctx.fillText(info.label, cx, y + 8);
  }
}

function drawDesk(home, accent, active, tick) {
  const { x, y } = home.desk;
  const pcFrames = [FURNITURE_ASSETS.pcFront1, FURNITURE_ASSETS.pcFront2, FURNITURE_ASSETS.pcFront3];
  const pcUrl = active ? pcFrames[Math.floor(tick / 18) % pcFrames.length] : FURNITURE_ASSETS.pcFront1;

  // Pixel Agents furniture PNGs. Fallback procedural drawing stays available while assets load.
  const drewDesk = home.side
    ? drawAsset(FURNITURE_ASSETS.deskSide, x - 16, y - 64, 32, 128)
    : drawAsset(FURNITURE_ASSETS.deskFront, x - 48, y - 8, 96, 64);
  const drewPc = home.side
    ? drawAsset(FURNITURE_ASSETS.pcSide, x - 32, y - 32, 32, 64)
    : drawAsset(pcUrl, x - 16, y - 56, 32, 64);
  if (home.side) {
    drawAsset(FURNITURE_ASSETS.cushionedChairSide, home.chair.x - 16, home.chair.y - 16, 32, 32);
  } else {
    drawAsset(FURNITURE_ASSETS.cushionedChairFront, x - 16, y + 32, 32, 32);
  }

  if (drewDesk && drewPc) return;

  ctx.fillStyle = "#9a7b4f";
  ctx.fillRect(x - 38, y, 76, 18);
  ctx.fillStyle = "#7c6140";
  ctx.fillRect(x - 38, y + 18, 76, 4);
  ctx.fillStyle = "#5d4a30";
  ctx.fillRect(x - 34, y + 22, 6, 12);
  ctx.fillRect(x + 28, y + 22, 6, 12);
  ctx.fillStyle = "#0b1220";
  ctx.fillRect(x - 18, y - 24, 36, 22);
  const glow = active ? (Math.floor(tick / 20) % 2 === 0 ? 1 : 0.75) : 0.45;
  ctx.globalAlpha = glow;
  ctx.fillStyle = accent;
  ctx.fillRect(x - 15, y - 21, 30, 16);
  ctx.globalAlpha = 1;
  ctx.fillStyle = "rgba(11,18,32,0.85)";
  ctx.fillRect(x - 15, y - 10, 30, 5);
  ctx.fillStyle = "#43355c";
  ctx.fillRect(x - 12, y + 28, 24, 10);
}

function drawDecor(tick) {
  for (const sx of [220, 1000]) {
    ctx.fillStyle = "#5b4b8a";
    ctx.fillRect(sx - 36, 650, 72, 18);
    ctx.fillStyle = "#3f356b";
    ctx.fillRect(sx - 36, 642, 72, 8);
  }
  ctx.fillStyle = "#9a7b4f";
  ctx.fillRect(600, 658, 80, 12);
  ctx.fillStyle = "#f8fafc";
  ctx.fillRect(616, 652, 6, 5);
  ctx.fillRect(648, 652, 6, 5);
  for (const [px, py] of [[50, 62], [1210, 62], [50, 382], [1210, 382]]) {
    ctx.fillStyle = "#7c4a2d";
    ctx.fillRect(px - 6, py + 8, 12, 8);
    ctx.fillStyle = "#3f7a46";
    ctx.fillRect(px - 4, py, 8, 8);
    ctx.fillStyle = "#56a35e";
    ctx.fillRect(px - 6, py + 3, 3, 4);
    ctx.fillRect(px + 3, py + 3, 3, 4);
  }
  ctx.fillStyle = "#f8fafc";
  ctx.fillRect(628, 296, 24, 24);
  ctx.fillStyle = "#14151c";
  ctx.fillRect(630, 298, 20, 20);
  ctx.fillStyle = "#f8fafc";
  const t = (tick / 60) % 60;
  ctx.fillRect(638, 302 + Math.floor((t % 12) / 2), 2, 6);
  ctx.fillRect(640, 308, 2, 2);
}

function drawBookShelf(x, y, segments = 2) {
  let drewAsset = true;
  for (let i = 0; i < segments; i += 1) {
    drewAsset = drawAsset(FURNITURE_ASSETS.doubleBookshelf, x + i * 64, y, 64, 64) && drewAsset;
  }
  if (drewAsset) return;
  const w = segments * 64;
  ctx.fillStyle = "#704626";
  ctx.fillRect(x, y, w, 14);
  ctx.fillRect(x, y + 54, w, 14);
  ctx.fillStyle = "#4b2f1d";
  ctx.fillRect(x, y + 14, w, 40);
  const colors = ["#f472b6", "#60a5fa", "#fbbf24", "#34d399", "#e5e7eb"];
  for (let i = 0; i < Math.floor(w / 14); i++) {
    ctx.fillStyle = colors[i % colors.length];
    ctx.fillRect(x + 8 + i * 13, y + 22, 7, 24);
  }
}

function drawPlantPot(x, y) {
  if (drawAsset(FURNITURE_ASSETS.plant, x - 16, y - 32, 32, 64)) return;
  ctx.fillStyle = "#7c4a2d";
  ctx.fillRect(x - 8, y + 12, 16, 13);
  ctx.fillStyle = "#3f7a46";
  ctx.fillRect(x - 5, y + 3, 10, 12);
  ctx.fillStyle = "#56a35e";
  ctx.fillRect(x - 13, y + 8, 8, 7);
  ctx.fillRect(x + 5, y + 8, 8, 7);
}

function drawServerCabinet(x, y) {
  if (drawAsset(FURNITURE_ASSETS.pcFront1, x, y + 8, 32, 64)) return;
  ctx.fillStyle = "#d1d5db";
  ctx.fillRect(x, y, 38, 80);
  ctx.fillStyle = "#374151";
  ctx.fillRect(x + 6, y + 10, 26, 10);
  ctx.fillRect(x + 6, y + 28, 26, 10);
  ctx.fillRect(x + 6, y + 46, 26, 10);
  ctx.fillStyle = tickBlink() ? "#22c55e" : "#60a5fa";
  ctx.fillRect(x + 26, y + 64, 5, 5);
}

function tickBlink() {
  return Math.floor(performance.now() / 400) % 2 === 0;
}

function drawWoodFloor(x, y, w, h) {
  ctx.fillStyle = "#9b6a34";
  ctx.fillRect(x, y, w, h);
  for (let xx = x; xx < x + w; xx += 42) {
    ctx.fillStyle = "rgba(96,55,24,0.26)";
    ctx.fillRect(xx, y, 2, h);
  }
  for (let yy = y; yy < y + h; yy += 32) {
    ctx.fillStyle = "rgba(255,255,255,0.05)";
    ctx.fillRect(x, yy, w, 2);
  }
}

function drawTileFloor(x, y, w, h, base, line) {
  ctx.fillStyle = base;
  ctx.fillRect(x, y, w, h);
  for (let xx = x; xx < x + w; xx += 36) {
    ctx.fillStyle = line;
    ctx.fillRect(xx, y, 2, h);
  }
  for (let yy = y; yy < y + h; yy += 36) {
    ctx.fillStyle = line;
    ctx.fillRect(x, yy, w, 2);
  }
}

function drawHarvestRoomBackground(tick) {
  ctx.fillStyle = "#111220";
  ctx.fillRect(0, 0, CANVAS_W, CANVAS_H);

  // Reference composition: one tall wood room at left and two rooms at right.
  const bx = 145, by = 0, bw = 961, bh = 512;
  ctx.fillStyle = "#202231";
  ctx.fillRect(bx - 10, by, bw + 20, bh);

  drawWoodFloor(145, 0, 528, 512);
  drawTileFloor(673, 0, 433, 208, "#e9e4d8", "rgba(120,120,120,0.12)");
  drawTileFloor(718, 230, 388, 282, "#426b7c", "rgba(255,255,255,0.035)");

  // Clean thick walls/separators.
  ctx.fillStyle = "#202231";
  ctx.fillRect(145, 0, 528, 10);     // top wall
  ctx.fillRect(145, 502, 528, 10);   // bottom wall
  ctx.fillRect(145, 0, 10, 512);      // left wall
  ctx.fillRect(663, 0, 10, 512);      // room separator
  ctx.fillRect(673, 208, 433, 22);    // lab bottom wall
  ctx.fillRect(673, 230, 45, 85);     // meeting left inset wall
  ctx.fillRect(1096, 230, 10, 282);   // right wall

  // Door openings / corridors painted as floor, not black gaps.
  ctx.fillStyle = "#9b6a34";
  ctx.fillRect(648, 150, 34, 82);
  ctx.fillRect(648, 360, 34, 82);
  ctx.fillStyle = "#e9e4d8";
  ctx.fillRect(673, 150, 45, 58);
  ctx.fillStyle = "#426b7c";
  ctx.fillRect(673, 230, 68, 85);

  // Wall furniture follows the reference. Live desks are drawn separately.
  drawBookShelf(194, 35, 3);
  drawBookShelf(480, 35, 3);
  drawBookShelf(725, 275, 2);
  drawBookShelf(960, 275, 2);
  drawAsset(FURNITURE_ASSETS.whiteboard, 1010, 48, 64, 64);
  drawAsset(FURNITURE_ASSETS.clock, 875, 12, 32, 32);
  drawServerCabinet(690, 55);
  drawServerCabinet(745, 55);

  // Meeting room props.
  drawAsset(FURNITURE_ASSETS.largePainting, 874, 240, 64, 64);
  drawAsset(FURNITURE_ASSETS.sofaSide, 810, 350, 32, 64);
  drawAsset(FURNITURE_ASSETS.sofaSide, 1030, 350, 32, 64, true);

  // Plants.
  for (const [x, y] of [[210, 90], [210, 475], [635, 475], [700, 175], [1080, 175], [748, 475], [1080, 475]]) {
    drawPlantPot(x, y);
  }
}

function drawOfficialLayout(drawFurniture = true) {
  const layout = state.officialLayout;
  if (!layout) return false;
  const s = OFFICIAL_TILE * OFFICIAL_ZOOM;
  const offsetX = Math.floor((CANVAS_W - layout.cols * s) / 2);
  const offsetY = Math.floor((CANVAS_H - layout.rows * s) / 2);

  ctx.fillStyle = "#111220";
  ctx.fillRect(0, 0, CANVAS_W, CANVAS_H);
  for (let row = 0; row < layout.rows; row += 1) {
    for (let col = 0; col < layout.cols; col += 1) {
      const tile = layout.tiles[row * layout.cols + col];
      const color = layout.tileColors?.[row * layout.cols + col] || null;
      if (tile === 255) continue;
      const x = offsetX + col * s;
      const y = offsetY + row * s;
      if (tile === 0) {
        const wall = getAsset(OFFICIAL_WALL_ASSET);
        if (wall) {
          let mask = 0;
          const at = (c, r) => c >= 0 && r >= 0 && c < layout.cols && r < layout.rows &&
            layout.tiles[r * layout.cols + c] === 0;
          if (at(col, row - 1)) mask |= 1;
          if (at(col + 1, row)) mask |= 2;
          if (at(col, row + 1)) mask |= 4;
          if (at(col - 1, row)) mask |= 8;
          // Official wall sheet: 4 columns × 4 rows, one 16×32 sprite per mask.
          const sx = (mask % 4) * 16;
          const sy = Math.floor(mask / 4) * 32;
          ctx.drawImage(wall, sx, sy, 16, 32, x, y - s, s, s * 2);
        } else {
          ctx.fillStyle = "#202231";
          ctx.fillRect(x, y, s, s);
        }
      } else {
        const floor = getAsset(OFFICIAL_FLOOR_ASSETS[tile]);
        if (floor) {
          ctx.drawImage(floor, x, y, s, s);
          if (color) {
            // The official assets are grayscale and use Photoshop-style
            // colorization. Canvas `color` blending preserves luminance while
            // applying the layout's hue/saturation without cached tile copies.
            ctx.save();
            ctx.globalCompositeOperation = "color";
            ctx.fillStyle = `hsl(${color.h} ${color.s}% 50%)`;
            ctx.fillRect(x, y, s, s);
            if (color.b) {
              ctx.globalCompositeOperation = color.b < 0 ? "multiply" : "screen";
              ctx.globalAlpha = Math.min(0.8, Math.abs(color.b) / 100);
              ctx.fillStyle = color.b < 0 ? "#000" : "#fff";
              ctx.fillRect(x, y, s, s);
            }
            ctx.restore();
          }
        } else {
          const colors = { 1: "#d7d1c7", 7: "#9b6a34", 9: "#426b7c" };
          ctx.fillStyle = colors[tile] || "#77736d";
          ctx.fillRect(x, y, s, s);
        }
      }
    }
  }

  if (!drawFurniture) return true;
  for (const item of layout.furniture || []) {
    const url = officialFurnitureUrl(item.type);
    const img = url && getAsset(url);
    if (!img) continue;
    const x = offsetX + item.col * s;
    const y = offsetY + item.row * s;
    const w = img.naturalWidth * OFFICIAL_ZOOM;
    const h = img.naturalHeight * OFFICIAL_ZOOM;
    const mirrored = item.type.endsWith(":left");
    ctx.save();
    ctx.imageSmoothingEnabled = false;
    if (mirrored) {
      ctx.translate(x + w, y);
      ctx.scale(-1, 1);
      ctx.drawImage(img, 0, 0, w, h);
    } else {
      ctx.drawImage(img, x, y, w, h);
    }
    ctx.restore();
  }
  return true;
}

function drawOfficialFurnitureItem(item) {
  const layout = state.officialLayout;
  const url = officialFurnitureUrl(item.type);
  const img = url && getAsset(url);
  if (!layout || !img) return;
  const s = OFFICIAL_TILE * OFFICIAL_ZOOM;
  const offsetX = Math.floor((CANVAS_W - layout.cols * s) / 2);
  const offsetY = Math.floor((CANVAS_H - layout.rows * s) / 2);
  const x = offsetX + item.col * s;
  const y = offsetY + item.row * s;
  const w = img.naturalWidth * OFFICIAL_ZOOM;
  const h = img.naturalHeight * OFFICIAL_ZOOM;
  ctx.save();
  ctx.imageSmoothingEnabled = false;
  if (item.type.endsWith(":left")) {
    ctx.translate(x + w, y);
    ctx.scale(-1, 1);
    ctx.drawImage(img, 0, 0, w, h);
  } else {
    ctx.drawImage(img, x, y, w, h);
  }
  ctx.restore();
}

function drawWorld(tick) {
  const official = drawOfficialLayout(false);
  if (official) return;
  drawHarvestRoomBackground(tick);
  for (const [agentId, home] of Object.entries(AGENT_HOME)) {
    const agent = state.byId.get(agentId);
    const active = !!agent && (agent.status === "working" || agent.status === "alert") &&
      !agent.walking && agent.atDesk;
    drawDesk(home, ROOM_INFO[home.room].accent, active, tick);
  }
  // Handoff tetap dianimasikan lewat karakter, dokumen, dan bubble. Garis
  // diagonal sengaja tidak digambar agar komposisi sama seperti referensi.
}

function drawOfficialScene() {
  const layout = state.officialLayout;
  if (!layout) return false;
  const s = OFFICIAL_TILE * OFFICIAL_ZOOM;
  const offsetY = Math.floor((CANVAS_H - layout.rows * s) / 2);
  const scene = state.sceneOrder;
  scene.length = 0;

  for (const item of layout.furniture || []) {
    const img = getAsset(officialFurnitureUrl(item.type));
    if (!img) continue;
    let zY = offsetY + item.row * s + img.naturalHeight * OFFICIAL_ZOOM;
    // Match the official renderer's chair sorting: side/front chairs stay
    // behind a character seated on their first footprint row.
    if (item.type.includes("CHAIR") || item.type.includes("BENCH")) {
      zY = offsetY + (item.row + 1) * s;
    }
    scene.push({ kind: "furniture", value: item, zY });
  }
  for (const agent of state.agents) {
    // A workstation sprite can be 2-3 tiles tall. Sorting it by its full image
    // bottom caused a seated agent to be painted underneath the desk, making
    // one of the four core agents appear missing. Agents at/visiting a desk
    // must remain visible; overlays are still rendered after the whole scene.
    scene.push({ kind: "agent", value: agent, zY: agent.y + s * 3 });
  }
  scene.sort((a, b) => a.zY - b.zY);
  for (const entry of scene) {
    if (entry.kind === "agent") drawAgentBody(entry.value);
    else drawOfficialFurnitureItem(entry.value);
  }
  // Official renderer keeps bubbles and alert indicators above the whole scene.
  for (const agent of state.agents) drawAgentOverlay(agent);
  return true;
}


// --- Bubbles, emotes, alert marks ------------------------------------------------

function wrapText(text, maxChars) {
  const words = String(text).split(/\s+/);
  const lines = [];
  let line = "";
  for (const w of words) {
    if ((line + " " + w).trim().length > maxChars) {
      if (line) lines.push(line);
      line = w;
    } else {
      line = (line + " " + w).trim();
    }
  }
  if (line) lines.push(line);
  return lines.slice(0, 3);
}

function drawBubble(x, y, text, accent) {
  if (!text) return;
  const lines = wrapText(text, 22);
  ctx.font = "9px monospace";
  const w = Math.max(...lines.map((l) => l.length)) * 6 + 12;
  const h = lines.length * 11 + 8;
  const bx = Math.round(Math.min(Math.max(x - w / 2, 4), CANVAS_W - w - 4));
  const by = Math.round(y - 36 - h);
  ctx.fillStyle = "rgba(248,250,252,0.95)";
  ctx.strokeStyle = accent || "#14151c";
  ctx.lineWidth = 1;
  ctx.fillRect(bx, by, w, h);
  ctx.strokeRect(bx + 0.5, by + 0.5, w - 1, h - 1);
  ctx.beginPath();
  ctx.moveTo(x - 4, by + h);
  ctx.lineTo(x + 4, by + h);
  ctx.lineTo(x, by + h + 5);
  ctx.closePath();
  ctx.fillStyle = "rgba(248,250,252,0.95)";
  ctx.fill();
  ctx.fillStyle = "#14151c";
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  lines.forEach((l, i) => ctx.fillText(l, bx + w / 2, by + 4 + i * 11));
}

function drawTypingEmote(x, y, tick) {
  const by = Math.round(y - 30);
  ctx.fillStyle = "rgba(248,250,252,0.95)";
  ctx.fillRect(Math.round(x) - 10, by, 20, 9);
  ctx.strokeStyle = "#14151c";
  ctx.lineWidth = 1;
  ctx.strokeRect(Math.round(x) - 9.5, by + 0.5, 19, 8);
  ctx.fillStyle = "#14151c";
  for (let i = 0; i < 3; i++) {
    const on = Math.floor(tick / 8) % 3 === i;
    ctx.fillRect(Math.round(x) - 6 + i * 5, by + (on ? 2 : 3), 2, 2);
  }
}


// --- Agent movement + task phases --------------------------------------------------

const SPEED = 130;      // px/s saat bertugas (jalan cepat ala NPC Harvest Moon)
const IDLE_SPEED = 46;

function _reached(agent, target) {
  return Math.hypot(target.x - agent.x, target.y - agent.y) < 5;
}

function stepTask(agent, dt) {
  const task = agent.task;
  if (!task) return null;
  if (task.phase === "to" || task.phase === "back") {
    if (task.path.length === 0) {
      task.path = task.phase === "to" ? routeToAgent(agent, task.toAgentId) : routeHome(agent);
    }
    const target = task.path[0];
    if (_reached(agent, target)) {
      task.path.shift();
      if (task.path.length === 0) {
        if (task.phase === "to") {
          task.phase = "interact";
          task.timer = 2.6;
        } else {
          task.phase = "done";
        }
      }
      return null;
    }
    return { x: target.x, y: target.y, sitting: false, speed: SPEED, facing: null };
  }
  if (task.phase === "interact") {
    task.timer -= dt;
    const to = AGENT_HOME[task.toAgentId];
    agent.facing = agent.y < to.desk.y ? "up" : "down";
    if (task.timer <= 0) {
      task.phase = "back";
      task.path = [];
    }
    return { x: agent.x, y: agent.y, sitting: false, speed: 0, facing: agent.facing };
  }
  return null;
}

function computeTarget(agent, dt) {
  const taskTarget = stepTask(agent, dt);
  if (taskTarget) return taskTarget;
  if (agent.task && agent.task.phase === "done") {
    agent.task = null;
    if (agent.queuedTask) {
      agent.task = agent.queuedTask;
      agent.queuedTask = null;
    }
  }
  const home = AGENT_HOME[agent.id];
  if (agent.status === "working" || agent.status === "alert" || agent.status === "offline") {
    // Kalau sedang tidak di ruangan sendiri (habis kunjungan), pulang lewat pintu.
    if (!agent.atDesk && roomOf(agent.x, agent.y) !== home.room) {
      if (!agent._homePath) agent._homePath = routeHome(agent);
      if (agent._homePath.length > 0) {
        const p = agent._homePath[0];
        if (_reached(agent, p)) agent._homePath.shift();
        else return { x: p.x, y: p.y, sitting: false, speed: SPEED, facing: null };
      }
    }
    agent._homePath = null;
    return { x: home.chair.x, y: home.chair.y, sitting: true, speed: SPEED, facing: home.facing };
  }
  agent._homePath = null;
  if (agent.status === "break") {
    if (!agent._breakPath) agent._breakPath = routeToBreak(agent);
    if (agent._breakPath.length > 0) {
      const p = agent._breakPath[0];
      if (_reached(agent, p)) agent._breakPath.shift();
      else return { x: p.x, y: p.y, sitting: false, speed: IDLE_SPEED + 18, facing: null };
    }
    const idx = state.breakAssigned.get(agent.id) ?? 0;
    const spot = BREAK_SPOTS[idx % BREAK_SPOTS.length];
    return { x: spot.x, y: spot.y, sitting: true, speed: IDLE_SPEED + 18, facing: "down" };
  }
  agent._breakPath = null;
  // idle: kalau masih di ruangan lain, pulang dulu ke kursi sendiri
  if (!agent.atDesk && roomOf(agent.x, agent.y) !== home.room) {
    if (!agent._homePath) agent._homePath = routeHome(agent);
    if (agent._homePath.length > 0) {
      const p = agent._homePath[0];
      if (_reached(agent, p)) agent._homePath.shift();
      else return { x: p.x, y: p.y, sitting: false, speed: SPEED, facing: null };
    }
    agent._homePath = null;
    return { x: home.chair.x, y: home.chair.y, sitting: false, speed: SPEED, facing: null };
  }
  // No random wandering: an idle core agent stays at its workstation. Every
  // cross-room movement must represent a real workflow hand-off.
  return { x: home.chair.x, y: home.chair.y, sitting: true, speed: SPEED, facing: home.facing };
}

function stepAgent(agent, dt, tick) {
  const target = computeTarget(agent, dt);
  const dx = target.x - agent.x;
  const dy = target.y - agent.y;
  const dist = Math.hypot(dx, dy);
  const speed = target.speed || 0;
  if (dist > 2 && speed > 0) {
    const step = Math.min(dist, speed * dt);
    agent.x += (dx / dist) * step;
    agent.y += (dy / dist) * step;
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
  const home = AGENT_HOME[agent.id];
  agent.atDesk = Math.hypot(agent.x - home.chair.x, agent.y - home.chair.y) < 8;
  agent.tick = tick;
}

function drawAlertMark(x, y, tick) {
  const dy = Math.floor(tick / 10) % 2;
  ctx.fillStyle = "#ef4444";
  ctx.fillRect(Math.round(x) - 2, Math.round(y) - 38 - dy, 4, 9);
  ctx.fillRect(Math.round(x) - 2, Math.round(y) - 27 - dy, 4, 4);
}


// --- Rendering agents --------------------------------------------------------------

function drawAgentBody(agent) {
  const dim = agent.status === "offline";
  ctx.save();
  // Offline means execution is locked, not that the fourth core agent vanished.
  if (dim) ctx.globalAlpha = 0.78;
  const carrying = !!agent.task && agent.task.phase === "to";
  const typing = (agent.status === "working" || agent.status === "alert") && agent.atDesk && !agent.walking;
  drawSprite(agent.x, agent.y, agent.color, agent.facing || "down", agent.walking, typing, agent.tick, carrying, agent.id);
  ctx.restore();

  if (dim) {
    ctx.fillStyle = "rgba(17,18,32,0.9)";
    ctx.fillRect(Math.round(agent.x - 10), Math.round(agent.y - 72), 20, 16);
    ctx.fillStyle = "#fbbf24";
    ctx.fillRect(Math.round(agent.x - 5), Math.round(agent.y - 67), 10, 8);
    ctx.strokeStyle = "#fbbf24";
    ctx.lineWidth = 2;
    ctx.strokeRect(Math.round(agent.x - 4), Math.round(agent.y - 72), 8, 7);
  }



}

function drawAgentOverlay(agent) {
  if (agent.task && agent.task.phase === "interact") {
    drawTypingEmote(agent.x, agent.y, agent.tick);
    drawBubble(agent.x, agent.y - 6, agent.task.bubble, agent.color);
  } else if ((agent.status === "working" || agent.status === "alert") && agent.atDesk && !agent.walking) {
    drawTypingEmote(agent.x, agent.y, agent.tick);
    if (agent.taskText && Math.floor(agent.tick / 240) % 2 === 0) {
      drawBubble(agent.x, agent.y - 6, agent.taskText, agent.color);
    }
  }
  if (agent.has_alert) drawAlertMark(agent.x, agent.y, agent.tick);
}

function drawAgent(agent) {
  drawAgentBody(agent);
  drawAgentOverlay(agent);
}

// --- Data sync: status -> task choreography (alur sistem nyata) -----------------------

function assignBreakSpots(agents) {
  state.breakAssigned.clear();
  let i = 0;
  for (const agent of agents) {
    if (agent.status === "break") state.breakAssigned.set(agent.id, i++);
  }
}

function evalWorkflow(agent, prev) {
  if (!prev || agent.status === prev.status) return;
  const now = agent.status;
  const was = prev.status;
  const detail = agent.detail || "";

  // Chart selesai analisa -> laporan ke Learning dan Decision.
  if (agent.id === "yuna" && was === "working" && now !== "working") {
    enqueueTask(agent, "nara", "chart->learning", "Yuna → Nara: chart reading baru");
    enqueueTask(agent, "miro", "chart->decision", `Yuna → Miro: ${detail || "bias terbaru"}`);
  }
  // Learning selesai mengolah journal -> insight ke Decision.
  if (agent.id === "nara" && was === "working" && now !== "working") {
    enqueueTask(agent, "miro", "learning->decision", `Nara → Miro: ${detail || "journal terbaru"}`);
  }
  // Decision selesai -> instruksi ke Executor.
  if (agent.id === "miro" && was === "working" && now !== "working") {
    enqueueTask(agent, "dami", "decision->executor", `Miro → Dami: ${agent.taskText || "pipeline"}`);
  }
  // Executor selesai -> feedback balik ke Learning.
  if (agent.id === "dami" && was === "working" && now !== "working") {
    enqueueTask(agent, "nara", "execution->learning", "Dami → Nara: execution feedback");
  }
}

const WORKFLOW_HANDOFFS = [
  {
    from: "yuna",
    to: "nara",
    label: "chart->learning",
    bubble: () => "Yuna → Nara: chart reading & observation baru",
  },
  {
    from: "yuna",
    to: "miro",
    label: "chart->decision",
    bubble: () => `Yuna → Miro: ${state.byId.get("yuna")?.detail || "bias terbaru"}`,
  },
  {
    from: "nara",
    to: "miro",
    label: "learning->decision",
    bubble: () => `Nara → Miro: ${state.byId.get("nara")?.detail || "learning journal"}`,
  },
  {
    from: "miro",
    to: "dami",
    label: "decision->executor",
    bubble: () => `Miro → Dami: ${state.byId.get("miro")?.taskText || "pipeline"}`,
  },
  {
    from: "dami",
    to: "nara",
    label: "execution->learning",
    bubble: () => `Dami → Nara: ${state.byId.get("dami")?.detail || "feedback"}`,
  },
];

function workflowIsBusy() {
  return state.agents.some((agent) =>
    (agent.task && agent.task.phase !== "done") || agent.queuedTask || agent._homePath,
  );
}

/**
 * Run the four-agent hand-off sequence only when the prior hand-off is fully
 * complete. Runtime status changes can still enqueue a higher-priority task
 * through evalWorkflow(); this scheduler fills quiet periods deterministically.
 */
function scheduleWorkflow(now) {
  if (state.agents.length !== 4 || now < state.nextWorkflowAt || workflowIsBusy()) return;

  for (let attempts = 0; attempts < WORKFLOW_HANDOFFS.length; attempts += 1) {
    const flow = WORKFLOW_HANDOFFS[state.workflowIndex % WORKFLOW_HANDOFFS.length];
    state.workflowIndex = (state.workflowIndex + 1) % WORKFLOW_HANDOFFS.length;
    const sender = state.byId.get(flow.from);
    const target = state.byId.get(flow.to);
    // Offline Executor may receive a decision, but cannot send feedback.
    if (!sender || !target || sender.status === "offline") continue;
    enqueueTask(sender, flow.to, flow.label, flow.bubble());
    state.nextWorkflowAt = now + 2500;
    return;
  }

  state.nextWorkflowAt = now + 4000;
}


function hydrate(agents) {
  assignBreakSpots(agents);
  for (const incoming of agents) {
    if (!AGENT_HOME[incoming.id]) continue;
    const existing = state.byId.get(incoming.id);
    if (existing) {
      const prev = { status: existing.status };
      const runtimeTask = existing.task;
      const queuedTask = existing.queuedTask;
      Object.assign(existing, incoming);
      existing.taskText = incoming.task;
      existing.task = runtimeTask;
      existing.queuedTask = queuedTask;
      evalWorkflow(existing, prev);
    } else {
      const home = AGENT_HOME[incoming.id];
      const agent = {
        ...incoming,
        taskText: incoming.task,
        x: home.chair.x,
        y: home.chair.y,
        facing: home.facing,
        walking: false,
        sitting: true,
        atDesk: true,
        tick: 0,
        task: null,
        queuedTask: null,
        _breakPath: null,
        _homePath: null,
      };
      state.byId.set(incoming.id, agent);
      state.agents.push(agent);
    }
  }
}

// --- Legend panel + KPI ----------------------------------------------------------------

function renderLegend() {
  const list = document.getElementById("agent-list");
  const cards = state.agents.map((agent) => {
    const li = document.createElement("li");
    li.className = "agent-card";
    li.dataset.status = agent.status;
    const onDuty = agent.task && agent.task.phase !== "done";
    const flow = onDuty
      ? `<span class="agent-flow">&#8627; laporan ke ${escapeHtml(AGENT_SHORT_NAME[agent.task.to] || agent.task.to)}</span>`
      : "";
    li.innerHTML = `
      <span class="agent-dot" style="background:${agent.color}"></span>
      <div class="agent-body">
        <strong>${escapeHtml(agent.name)} <small style="color:#98a0b4">${escapeHtml(agent.job)}</small></strong>
        <span>${escapeHtml(onDuty && agent.task.phase === "interact" ? agent.task.bubble : agent.taskText || "")}</span>
        <span style="color:#64748b">${escapeHtml(agent.detail || "")}</span>
        ${flow}
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
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

// --- Fetch + render loop -----------------------------------------------------------------

async function pollState() {
  if (!state.pageVisible || state.pollInFlight) return;
  state.pollInFlight = true;
  try {
    const res = await fetch("/api/office/state", { credentials: "same-origin" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    hydrate(data.agents || []);
    updateKpi(data.kpi || {});
    setConnStatus(true);
    const el = document.getElementById("last-updated");
    if (el && data.generated_at) {
      el.textContent = `Updated ${new Date(data.generated_at).toLocaleTimeString()}`;
    }
    state.lastFetchOk = true;
  } catch (err) {
    console.warn("office state fetch failed", err);
    setConnStatus(false);
    state.lastFetchOk = false;
  } finally {
    state.pollInFlight = false;
    schedulePoll();
  }
}

function schedulePoll(delay = POLL_MS) {
  if (state.pollTimerId) window.clearTimeout(state.pollTimerId);
  if (!state.pageVisible) {
    state.pollTimerId = 0;
    return;
  }
  state.pollTimerId = window.setTimeout(() => {
    state.pollTimerId = 0;
    pollState();
  }, delay);
}

let lastFrame = performance.now();
let lastRender = 0;
let tick = 0;

function loop(now) {
  if (!state.pageVisible) {
    state.rafId = 0;
    return;
  }
  if (now - lastRender < FRAME_MS) {
    state.rafId = requestAnimationFrame(loop);
    return;
  }
  const dt = Math.min(0.1, (now - lastFrame) / 1000);
  lastFrame = now;
  lastRender = now;
  tick += 1;
  scheduleWorkflow(now);
  drawWorld(tick);
  for (const agent of state.agents) stepAgent(agent, dt, tick);
  if (drawOfficialScene()) {
    state.rafId = requestAnimationFrame(loop);
    return;
  }
  // Reuse one bounded array (always four entries) instead of allocating every frame.
  const order = state.renderOrder;
  order.length = state.agents.length;
  for (let i = 0; i < state.agents.length; i += 1) order[i] = state.agents[i];
  order.sort((a, b) => a.y - b.y);
  for (const agent of order) drawAgent(agent);
  state.rafId = requestAnimationFrame(loop);
}

function resizeCanvasToDisplay() {
  // CSS handles responsive scaling. Reassigning an unchanged width/height
  // recreates the ~3.5 MiB backing buffer and causes avoidable GC churn.
  if (canvas.width !== CANVAS_W) canvas.width = CANVAS_W;
  if (canvas.height !== CANVAS_H) canvas.height = CANVAS_H;
  ctx.imageSmoothingEnabled = false;
}

document.addEventListener("visibilitychange", () => {
  state.pageVisible = document.visibilityState === "visible";
  if (state.pageVisible && !state.rafId) {
    lastFrame = performance.now();
    lastRender = 0;
    pollState();
    state.rafId = requestAnimationFrame(loop);
  } else if (!state.pageVisible) {
    schedulePoll();
  }
});
window.addEventListener("pagehide", () => {
  if (state.rafId) cancelAnimationFrame(state.rafId);
  if (state.pollTimerId) window.clearTimeout(state.pollTimerId);
  state.rafId = 0;
  state.pollTimerId = 0;
}, { once: true });
resizeCanvasToDisplay();
preloadPixelAgentAssets();
loadOfficialLayout();

pollState();
state.rafId = requestAnimationFrame(loop);

