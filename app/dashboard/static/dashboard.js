const state = { liveEvents: [], lastOrders: null, loading: true, tvChart: null, tvSeries: null, tvVolumeSeries: null, apexChart: null, renderEventsTimer: null, toastTimer: null, lastMetrics: {}, chartSymbol: "BTC/USDT", chartTimeframe: "1h", chartLimit: 200, chartLoading: false, chartRefreshTimer: null };
const fmt = (value) => typeof value === "number" ? value.toLocaleString(undefined, { maximumFractionDigits: 4 }) : (value ?? "-");
const byId = (id) => document.getElementById(id);
const text = (id, value) => { const node = byId(id); if (node) node.textContent = value; };
const json = (id, value) => text(id, JSON.stringify(value, null, 2));
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[char]));

function dashboardApp() { return { theme: localStorage.getItem("theme") || "dark", query: "", toggleTheme() { this.theme = this.theme === "dark" ? "light" : "dark"; localStorage.setItem("theme", this.theme); } }; }
async function getJson(path) { const response = await fetch(path); if (!response.ok) throw new Error(`${path} ${response.status}`); return response.json(); }

async function loadAll() {
  const started = performance.now();
  setLoading(true);
  const [market, portfolio, paper, analytics, liveOrders, health] = await Promise.all([getJson("/api/market"), getJson("/api/portfolio"), getJson("/api/paper"), getJson("/api/analytics"), getJson("/api/live/orders"), getJson("/api/health")]);
  text("latency-badge", `Latency ${Math.round(performance.now() - started)} ms`);
  render({ market, portfolio, paper, analytics, liveOrders, health });
}

function setLoading(isLoading) {
  state.loading = isLoading;
  document.body.classList.toggle("is-loading", isLoading);
  ["market", "positions", "journal-list", "events", "live-orders", "portfolio-json"].forEach((id) => byId(id)?.classList.toggle("loading", isLoading));
}

function render(payload) {
  setLoading(false);
  animateMetric("metric-signals", payload.market?.count ?? 0);
  animateMetric("metric-equity", payload.portfolio?.equity);
  animateMetric("metric-balance", payload.paper?.balance);
  animateMetric("metric-positions", payload.portfolio?.open_positions_count ?? 0);
  renderMarket(payload.market?.signals ?? []);
  renderPositions(payload.portfolio?.open_positions ?? []);
  renderJournal(payload.analytics?.journal?.trades ?? []);
  renderHealth(payload.health ?? {});
  renderOrders(payload.liveOrders ?? {});
  json("portfolio-json", payload.portfolio ?? {});
  json("analytics-json", payload.analytics?.performance ?? payload.analytics ?? {});
  state.lastOrders = payload.liveOrders ?? {};
  renderCharts(payload);
}

function animateMetric(id, value) {
  const node = byId(id);
  if (!node) return;
  if (typeof value !== "number" || !Number.isFinite(value)) { node.textContent = fmt(value); return; }
  const start = Number(node.dataset.value ?? 0);
  const end = value;
  updateTrend(id.replace("metric-", ""), start, end);
  const duration = 650;
  const started = performance.now();
  node.dataset.value = String(end);
  node.classList.remove("metric-pop");
  requestAnimationFrame(() => node.classList.add("metric-pop"));
  const step = (now) => {
    const progress = Math.min((now - started) / duration, 1);
    const eased = 1 - Math.pow(1 - progress, 3);
    node.textContent = fmt(start + (end - start) * eased);
    if (progress < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

function updateTrend(name, start, end) {
  const node = byId(`trend-${name}`);
  if (!node) return;
  const delta = end - start;
  const direction = delta > 0 ? "UP" : delta < 0 ? "DOWN" : "FLAT";
  node.textContent = `${direction} ${delta === 0 ? "" : fmt(Math.abs(delta))}`.trim();
  node.className = direction.toLowerCase();
}

function emptyState(title, detail) {
  return `<div class="empty-state"><span class="empty-mark">--</span><strong>${escapeHtml(title)}</strong><small>${escapeHtml(detail)}</small></div>`;
}

function statusClass(value) {
  const textValue = String(value ?? "").toUpperCase();
  if (textValue.includes("BUY") || textValue.includes("WIN") || textValue.includes("FILLED")) return "success";
  if (textValue.includes("SELL") || textValue.includes("LOSS") || textValue.includes("ERROR") || textValue.includes("REJECT")) return "danger";
  if (textValue.includes("PENDING") || textValue.includes("OPEN") || textValue.includes("NEW")) return "warning";
  return "info";
}

function badge(value) {
  return `<span class="status-badge ${statusClass(value)}">${escapeHtml(value ?? "-")}</span>`;
}

function renderMarket(signals) {
  const node = byId("market");
  if (!node) return;
  const filter = byId("market-filter")?.value || "all";
  const rows = signals.filter(signal => filter === "all" || signal.action === filter);
  node.innerHTML = rows.map(signal => `<div class="item signal-card"><strong><span>${escapeHtml(signal.symbol ?? "unknown")}</span>${badge(signal.action)}</strong><small>score ${fmt(signal.score)} | confidence ${fmt(signal.confidence)}</small></div>`).join("") || emptyState("No market signals", "Scanner output will appear here after the next API refresh.");
}

function renderPositions(positions) {
  const node = byId("positions");
  if (!node) return;
  node.innerHTML = positions.map(position => `<div class="item"><strong><span>${escapeHtml(position.symbol ?? "unknown")}</span><b>${fmt(position.quantity)}</b></strong><small>entry ${fmt(position.average_entry_price ?? position.price)} | source ${escapeHtml(position.source ?? "portfolio")}</small></div>`).join("") || emptyState("No open positions", "Exposure is clear while no positions are reported.");
}

function renderJournal(trades) {
  const node = byId("journal-list");
  if (!node) return;
  const needle = (byId("journal-filter")?.value || "").toLowerCase();
  const rows = trades.filter(trade => JSON.stringify(trade).toLowerCase().includes(needle)).slice(-40).reverse();
  if (!rows.length) { node.innerHTML = emptyState("No closed trades", "Completed trades will build a searchable journal here."); return; }
  node.innerHTML = `<table><thead><tr><th>Symbol</th><th>Net PnL</th><th>Entry</th><th>Exit</th></tr></thead><tbody>${rows.map(trade => `<tr><td data-label="Symbol">${escapeHtml(trade.symbol ?? "unknown")}</td><td data-label="Net PnL"><b>${fmt(trade.net_pnl ?? 0)}</b></td><td data-label="Entry">${escapeHtml(trade.entry_time ?? "-")}</td><td data-label="Exit">${escapeHtml(trade.exit_time ?? "-")}</td></tr>`).join("")}</tbody></table>`;
}

function renderOrders(orders) {
  const node = byId("live-orders");
  if (!node) return;
  const history = Array.isArray(orders?.order_history) ? orders.order_history : (Array.isArray(orders?.orders) ? orders.orders : []);
  if (!history.length) { node.innerHTML = emptyState("No live orders", "Order history from the current API response will appear here."); return; }
  node.innerHTML = `<table><thead><tr><th>Symbol</th><th>Side</th><th>Status</th><th>Qty</th><th>Updated</th></tr></thead><tbody>${history.slice(-50).reverse().map(order => `<tr><td data-label="Symbol">${escapeHtml(order.symbol ?? order.pair ?? "-")}</td><td data-label="Side">${badge(order.side ?? order.action ?? "-")}</td><td data-label="Status">${badge(order.status ?? order.state ?? "-")}</td><td data-label="Qty">${fmt(order.quantity ?? order.qty ?? order.executed_qty)}</td><td data-label="Updated">${escapeHtml(order.update_time ?? order.updated_at ?? order.created_at ?? "-")}</td></tr>`).join("")}</tbody></table>`;
}

function renderHealth(health) { json("health-json", { status: health.status, cpu: health.cpu, ram: health.ram, disk: health.disk, latency_ms: health.latency_ms, exchange_status: health.exchange_status, artifacts: health.artifacts }); }

function renderEventsNow() {
  const node = byId("events");
  if (!node) return;
  node.innerHTML = state.liveEvents.slice(-100).reverse().map(event => `<div class="item event-row"><strong><span>${escapeHtml(event.event_type ?? event.type ?? "event")}</span><b>${escapeHtml(event.occurred_at ?? "")}</b></strong><small>${escapeHtml(JSON.stringify(event.payload ?? {}))}</small></div>`).join("") || emptyState("Waiting for events", "Realtime Event Bus updates will stream into this panel.");
}

function renderEvents() {
  if (state.renderEventsTimer) return;
  state.renderEventsTimer = requestAnimationFrame(() => {
    state.renderEventsTimer = null;
    renderEventsNow();
  });
}

function renderCharts(payload) {
  if (window.ApexCharts && byId("pnl-chart") && !state.apexChart) {
    state.apexChart = new ApexCharts(byId("pnl-chart"), {
      chart: { type: "area", height: 190, toolbar: { show: false }, foreColor: "#8b98ad", animations: { enabled: true } },
      theme: { mode: "dark" },
      series: [{ name: "Equity", data: [payload.paper?.balance ?? 0, payload.portfolio?.equity ?? 0] }],
      stroke: { curve: "smooth", width: 3 },
      fill: { type: "gradient", gradient: { opacityFrom: 0.36, opacityTo: 0.02 } },
      colors: ["#38bdf8"],
      grid: { borderColor: "rgba(148,163,184,.12)" },
    });
    state.apexChart.render();
  }
  ensureTradingViewChart();
}

function ensureTradingViewChart() {
  if (!window.LightweightCharts || !byId("tv-chart") || state.tvChart) return;
  const node = byId("tv-chart");
  state.tvChart = LightweightCharts.createChart(node, {
    height: node.clientHeight || 460,
    layout: { background: { color: "transparent" }, textColor: "#8b98ad" },
    grid: { vertLines: { color: "rgba(148,163,184,.08)" }, horzLines: { color: "rgba(148,163,184,.08)" } },
    rightPriceScale: { borderColor: "rgba(148,163,184,.14)" },
    timeScale: { borderColor: "rgba(148,163,184,.14)", timeVisible: true, secondsVisible: false },
    crosshair: { mode: 1 },
  });
  state.tvSeries = state.tvChart.addCandlestickSeries({
    upColor: "#22c55e",
    downColor: "#ef4444",
    borderUpColor: "#22c55e",
    borderDownColor: "#ef4444",
    wickUpColor: "#22c55e",
    wickDownColor: "#ef4444",
  });
  state.tvVolumeSeries = state.tvChart.addHistogramSeries({
    priceFormat: { type: "volume" },
    priceScaleId: "",
    color: "rgba(56,189,248,.35)",
  });
  state.tvVolumeSeries.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
  resizeCharts();
  loadKlines().catch((error) => console.warn("initial klines load failed", error));
  if (!state.chartRefreshTimer) {
    state.chartRefreshTimer = setInterval(() => loadKlines().catch(() => {}), 60_000);
  }
}

async function loadKlines() {
  if (state.chartLoading || !state.tvSeries) return;
  state.chartLoading = true;
  const params = new URLSearchParams({
    symbol: state.chartSymbol,
    timeframe: state.chartTimeframe,
    limit: String(state.chartLimit),
  });
  try {
    const payload = await getJson(`/api/klines?${params.toString()}`);
    applyKlines(payload);
  } finally {
    state.chartLoading = false;
  }
}

function applyKlines(payload) {
  if (!state.tvSeries || !state.tvVolumeSeries) return;
  const candles = Array.isArray(payload?.candles) ? payload.candles : [];
  const seen = new Set();
  const priceRows = [];
  const volumeRows = [];
  for (const candle of candles) {
    const time = Number(candle?.time);
    if (!Number.isFinite(time) || time <= 0 || seen.has(time)) continue;
    seen.add(time);
    priceRows.push({
      time,
      open: Number(candle.open ?? 0),
      high: Number(candle.high ?? 0),
      low: Number(candle.low ?? 0),
      close: Number(candle.close ?? 0),
    });
    const close = Number(candle.close ?? 0);
    const open = Number(candle.open ?? 0);
    volumeRows.push({
      time,
      value: Number(candle.volume ?? 0),
      color: close >= open ? "rgba(34,197,94,.45)" : "rgba(239,68,68,.45)",
    });
  }
  priceRows.sort((a, b) => a.time - b.time);
  volumeRows.sort((a, b) => a.time - b.time);
  state.tvSeries.setData(priceRows);
  state.tvVolumeSeries.setData(volumeRows);
  if (priceRows.length) state.tvChart?.timeScale().fitContent();
  const source = payload?.source ? ` | source ${payload.source}` : "";
  const warning = payload?.warning ? ` | ${payload.warning}` : "";
  text("chart-caption", `${payload?.symbol ?? state.chartSymbol} @ ${payload?.timeframe ?? state.chartTimeframe} | ${priceRows.length} candles${source}${warning}`);
}

function setChartSymbol(symbol) {
  if (!symbol || symbol === state.chartSymbol) return;
  state.chartSymbol = symbol;
  loadKlines().catch((error) => showToast(`chart: ${error.message}`));
}

function setChartTimeframe(timeframe) {
  if (!timeframe || timeframe === state.chartTimeframe) return;
  state.chartTimeframe = timeframe;
  loadKlines().catch((error) => showToast(`chart: ${error.message}`));
}

function sortOrders() {
  const orders = state.lastOrders || {};
  const history = [...(orders.order_history || orders.orders || [])].sort((a, b) => String(b.update_time || b.updated_at || "").localeCompare(String(a.update_time || a.updated_at || "")));
  renderOrders({ ...orders, order_history: history });
}

function setWsStatus(status) {
  const node = byId("ws-status");
  if (!node) return;
  node.textContent = status;
  node.className = `pill ws ${status.toLowerCase()}`;
}

function showToast(message) {
  const node = byId("toast");
  if (!node) return;
  node.textContent = message;
  node.classList.remove("show");
  requestAnimationFrame(() => node.classList.add("show"));
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => node.classList.remove("show"), 3200);
}

function toggleSidebar() {
  document.body.classList.toggle("sidebar-collapsed");
  localStorage.setItem("sidebarCollapsed", document.body.classList.contains("sidebar-collapsed") ? "1" : "0");
  resizeCharts();
}

function toggleFullscreenChart() {
  byId("chart-card")?.classList.toggle("fullscreen-chart");
  setTimeout(resizeCharts, 120);
}

function resizeCharts() {
  const chartNode = byId("tv-chart");
  if (state.tvChart && chartNode) state.tvChart.applyOptions({ width: chartNode.clientWidth, height: chartNode.clientHeight || 460 });
  if (state.apexChart) state.apexChart.updateOptions({ chart: { height: byId("pnl-chart")?.clientHeight || 190 } }, false, false);
}

function debounce(fn, wait = 160) {
  let timer;
  return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), wait); };
}

function tickClock() {
  text("clock", new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }));
}

function initUi() {
  if (localStorage.getItem("sidebarCollapsed") === "1") document.body.classList.add("sidebar-collapsed");
  tickClock();
  setInterval(tickClock, 1000);
  window.addEventListener("resize", debounce(resizeCharts, 180), { passive: true });
  document.querySelectorAll(".sidebar nav a").forEach((link) => link.addEventListener("click", () => {
    document.querySelectorAll(".sidebar nav a").forEach((item) => item.classList.remove("active"));
    link.classList.add("active");
  }));
}

function connectWs() {
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  setWsStatus("Reconnecting");
  const ws = new WebSocket(`${protocol}://${location.host}/ws`);
  ws.onopen = () => { setWsStatus("Connected"); showToast("Websocket connected"); };
  ws.onerror = () => setWsStatus("Disconnected");
  ws.onclose = () => { setWsStatus("Disconnected"); setTimeout(() => { setWsStatus("Reconnecting"); connectWs(); }, 3000); };
  ws.onmessage = (message) => { const data = JSON.parse(message.data); if (data.type === "snapshot") render(data.payload); if (data.type === "live_events") state.liveEvents = data.payload ?? []; if (data.type === "event") { state.liveEvents.push(data); showToast(`${data.event_type ?? "event"} received`); } renderEvents(); };
}

document.addEventListener("change", (event) => { if (event.target?.id === "market-filter") loadAll().catch(handleError); });
document.addEventListener("input", (event) => { if (event.target?.id === "journal-filter") loadAll().catch(handleError); });
function handleError(error) { console.error(error); setLoading(false); showToast(error.message); }
initUi(); loadAll().catch(handleError); connectWs();
