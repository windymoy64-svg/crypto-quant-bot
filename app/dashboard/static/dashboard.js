const FALLBACK_SYMBOLS = ["BTC/USDT","ETH/USDT","BNB/USDT","SOL/USDT","XRP/USDT","ADA/USDT","DOGE/USDT","TRX/USDT","AVAX/USDT","LINK/USDT","DOT/USDT","MATIC/USDT","LTC/USDT","BCH/USDT","UNI/USDT","ATOM/USDT","XLM/USDT","NEAR/USDT","APT/USDT","ARB/USDT","OP/USDT","INJ/USDT","SUI/USDT","PEPE/USDT","TIA/USDT"];
const DEFAULT_PAYLOAD = { market:{count:0,signals:[],tracked_signals:[],symbols:FALLBACK_SYMBOLS,configured_symbols:[]}, portfolio:{equity:0,available_balance:0,open_positions_count:0,open_positions:[],source:"local"}, multiPortfolio:{view_mode:"single",active_execution_exchange:null,accounts:[],positions:[],open_orders:[],order_history:[],closed_positions:[],accounts_connected:0}, paper:{balance:0,equity:0,available_balance:0,open_positions:[],fills:[],orders:[]}, analytics:{performance:{},journal:{trades:[]}}, liveOrders:{order_history:[],closed_positions:[],open_orders:[],filled_orders:[],rejected_orders:[]}, health:{status:"unknown"} };

// The execution mode is authoritative for every snapshot source.
// mode:state.executionMode
const state = { liveEvents:[], lastOrders:null, loading:true, executionMode:null, multiPortfolio:null, tvChart:null, tvSeries:null, tvVolumeSeries:null, apexChart:null, renderEventsTimer:null, toastTimer:null, chartSymbol:"BTC/USDT", chartTimeframe:"1h", chartExchange:null, chartLastCandle:null, chartLimit:200, chartLoading:false, chartRefreshTimer:null, dashboardRefreshTimer:null, clockTimer:null, ws:null, wsReconnectTimer:null, wsSnapshotTimer:null, symbols:[...FALLBACK_SYMBOLS], configuredSymbols:[], currentView:"overview", liveEntryCandidates:[], lastEntryLiveTs:0, lastAgentPipeline:null, lastPayload:clone(DEFAULT_PAYLOAD) };
const byId = id => document.getElementById(id);
function dashboardAuthHeaders(){ const token=document.querySelector('meta[name="dashboard-token"]')?.content||""; return token?{Authorization:`Bearer ${token}`} : {}; }
const fmt = v => typeof v === "number" && Number.isFinite(v) ? v.toLocaleString(undefined,{maximumFractionDigits:4}) : (v ?? "-");
const money = v => `$${fmt(Number(v ?? 0))}`;
const text = (id,v) => { const n=byId(id); if(n) n.textContent=v; };
const json = (id,v) => text(id, JSON.stringify(v,null,2));
const AMP = String.fromCharCode(38);
const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({"&":AMP+"amp;","<":AMP+"lt;",">":AMP+"gt;",'"':AMP+"quot;","'":AMP+"#39;"}[c]));


function clone(v){ return JSON.parse(JSON.stringify(v)); }
function list(v){ return Array.isArray(v)?v:[]; }
function normalizePayload(payload={}){ const raw=payload&&typeof payload==="object"?payload:{}; const p={...clone(DEFAULT_PAYLOAD),...raw}; p.market={...clone(DEFAULT_PAYLOAD.market),...(raw.market??{})}; p.paper={...clone(DEFAULT_PAYLOAD.paper),...(raw.paper??{})}; p.portfolio={...clone(DEFAULT_PAYLOAD.portfolio),...(raw.portfolio??{})}; p.multiPortfolio={...clone(DEFAULT_PAYLOAD.multiPortfolio),...(raw.multiPortfolio??raw.multi_portfolio??{})}; p.analytics={...clone(DEFAULT_PAYLOAD.analytics),...(raw.analytics??{})}; p.health={...clone(DEFAULT_PAYLOAD.health),...(raw.health??{})}; p.liveOrders={...clone(DEFAULT_PAYLOAD.liveOrders),...(raw.liveOrders??raw.live_orders??{})}; p.market.signals=list(p.market.signals); p.market.tracked_signals=list(p.market.tracked_signals); p.market.symbols=list(p.market.symbols); p.market.configured_symbols=list(p.market.configured_symbols); p.paper.open_positions=list(p.paper.open_positions); p.paper.fills=list(p.paper.fills); p.paper.orders=list(p.paper.orders); p.portfolio.open_positions=list(p.portfolio.open_positions); p.multiPortfolio.accounts=list(p.multiPortfolio.accounts); p.multiPortfolio.positions=list(p.multiPortfolio.positions); p.multiPortfolio.open_orders=list(p.multiPortfolio.open_orders); p.multiPortfolio.order_history=list(p.multiPortfolio.order_history); p.multiPortfolio.closed_positions=list(p.multiPortfolio.closed_positions); p.liveOrders.order_history=list(p.liveOrders.order_history); p.liveOrders.closed_positions=list(p.liveOrders.closed_positions); p.liveOrders.open_orders=list(p.liveOrders.open_orders); p.liveOrders.filled_orders=list(p.liveOrders.filled_orders); p.liveOrders.rejected_orders=list(p.liveOrders.rejected_orders); return p; }
function orderHistory(orders){ const rows=list(orders?.closed_positions).length?list(orders.closed_positions):list(orders?.order_history).filter(o=>String(o?.status||"").toUpperCase()==="CLOSED"); return rows.map(o=>({...o,reason:o.reason??o.close_label??o.close_reason,reason_source:o.reason_source??"exchange_lifecycle"})); }
function positionsFrom(portfolio,paper){ return list(portfolio?.open_positions).length?list(portfolio.open_positions):list(paper?.open_positions); }
function dashboardApp(){ return { theme:localStorage.getItem("theme")||"dark", query:"", toggleTheme(){ this.theme=this.theme==="dark"?"light":"dark"; localStorage.setItem("theme",this.theme); } }; }
async function getJson(path){ const r=await fetch(path,{cache:"no-store",credentials:"same-origin",headers:dashboardAuthHeaders()}); if(!r.ok) throw new Error(`${path} ${r.status}`); return r.json(); }
let dashboardRefreshRunning=false;
function syncDashboardPanels(payload){
  const p=normalizePayload(payload);
  const multi=p.multiPortfolio||{};
  const nextChartExchange=String(multi.active_execution_exchange||"").toLowerCase();
  const chartExchangeChanged=Boolean(nextChartExchange&&nextChartExchange!==state.chartExchange);
  if(nextChartExchange) state.chartExchange=nextChartExchange;
  if(chartExchangeChanged) subscribeChartSymbol();
  if(chartExchangeChanged&&state.currentView==="scanner") setTimeout(()=>loadKlines().catch(()=>{}),0);
  const mode=state.executionMode||"paper";
  const paperMode=mode==="paper";
  const realSourceSelected=!paperMode;
  const positions=realSourceSelected?list(multi.positions):positionsFrom(p.portfolio,p.paper);
  const pending=realSourceSelected?list(multi.open_orders):list(p.paper?.pending_orders);
  const orders=realSourceSelected?{...p.liveOrders,order_history:list(multi.order_history),closed_positions:list(multi.closed_positions)}:p.liveOrders;
  const portfolio=realSourceSelected?{equity:multi.equity_usdt,available_balance:multi.available_balance_usdt,open_positions:positions,open_positions_count:positions.length,source:"exchange",timestamp:multi.timestamp}:p.portfolio;
  if(realSourceSelected) renderRealPortfolioSummary(multi); else renderPortfolioSummary(portfolio,p.paper,orders);
  renderPortfolioDetail(portfolio,p.paper);
  renderPositions(positions);
  renderOrders(orders);
  renderAnalyticsSummary(p.analytics);
  renderHealth(p.health);
  renderJournal(list(p.analytics?.journal?.trades));
  renderCharts({...p,portfolio});
}
async function loadAll(){ if(dashboardRefreshRunning) return; dashboardRefreshRunning=true; const start=performance.now(); if(state.loading) setLoading(true); try{ const execution=await getJson("/api/settings/execution"); state.executionMode=String(execution?.mode||"paper").toLowerCase(); }catch(err){ console.warn("Execution mode load failed",err); state.executionMode=state.executionMode||"paper"; } const mode=state.executionMode||"paper"; const paperMode=mode==="paper"; const realSourceSelected=!paperMode; const endpoints=[["market","/api/market"],["portfolio","/api/portfolio"],["multiPortfolio","/api/portfolio/multi"],["analytics","/api/analytics"],["liveOrders","/api/live/orders"],["health","/api/health"]]; if(state.executionMode==="paper") endpoints.push(["paper","/api/paper"]); const payload=clone(state.lastPayload||DEFAULT_PAYLOAD); if(state.executionMode!=="paper") payload.paper=clone(DEFAULT_PAYLOAD.paper); try{ const results=await Promise.allSettled(endpoints.map(([,p])=>getJson(p))); results.forEach((res,i)=>{ const [key,path]=endpoints[i]; if(res.status==="fulfilled") payload[key]=res.value; else console.warn(`Failed to load ${path}`,res.reason); }); text("latency-badge",`Latency ${Math.round(performance.now()-start)} ms`); render(payload); syncDashboardPanels(payload); renderExecutionModeSummary(payload.multiPortfolio); if(typeof window.syncLivePanels==="function") window.syncLivePanels(payload); }finally{ dashboardRefreshRunning=false; setLoading(false); } }
function setLoading(v){ state.loading=v; document.body.classList.toggle("is-loading",v); ["market","symbol-universe","portfolio-summary","portfolio-detail","positions","journal-list","events","live-orders","portfolio-json","analytics-summary","active-orders"].forEach(id=>{ const el=byId(id); if(!el) return; el.classList.toggle("loading",v); if(!v) el.classList.remove("skeleton-box","skeleton"); }); }
function render(payload){ if(payload&&!payload.multiPortfolio&&!payload.multi_portfolio&&state.multiPortfolio) payload={...payload,multiPortfolio:state.multiPortfolio}; const p=normalizePayload(payload); const mode=state.executionMode||"paper"; const paperMode=mode==="paper"; const realSourceSelected=!paperMode; const realConnected=Number(p.multiPortfolio?.accounts_connected??0)>0; const positions=realSourceSelected?list(p.multiPortfolio.positions):positionsFrom(p.portfolio,p.paper); const pendingOrders=realSourceSelected?list(p.multiPortfolio.open_orders):list(p.paper?.pending_orders); const liveOrders=realSourceSelected?{...p.liveOrders,open_orders:pendingOrders,order_history:list(p.multiPortfolio.order_history),closed_positions:list(p.multiPortfolio.closed_positions)}:p.liveOrders; const balanceRaw=p.multiPortfolio?.account_balance_usdt??p.multiPortfolio?.available_balance_usdt; const equityRaw=p.multiPortfolio?.equity_usdt??balanceRaw; const realBalance=balanceRaw===null||balanceRaw===undefined?NaN:Number(balanceRaw); const realEquity=equityRaw===null||equityRaw===undefined?NaN:Number(equityRaw); state.multiPortfolio=p.multiPortfolio; state.lastPayload=p; setLoading(false); animateMetric("metric-signals",Number(p.market?.count??0)); if(realConnected&&Number.isFinite(realBalance)){ animateMetric("metric-equity",Number.isFinite(realEquity)?realEquity:realBalance); animateMetric("metric-balance",realBalance); }else if(realConnected){ text("metric-equity","Separate"); text("metric-balance","Separate"); }else{ animateMetric("metric-equity",Number(p.portfolio?.equity??p.paper?.equity??0)); animateMetric("metric-balance",Number(p.paper?.balance??p.portfolio?.available_balance??0)); } animateMetric("metric-positions",realConnected?Number(p.multiPortfolio?.open_positions_count??positions.length):Number(p.portfolio?.open_positions_count??positions.length)); renderRuntimeBadges(p.multiPortfolio); renderMarket(p.market?.signals??[],p.market?.tracked_signals??[]); renderSymbolUniverse(p.market??{}); if(realConnected) renderRealPortfolioSummary(p.multiPortfolio); else renderPortfolioSummary(p.portfolio??{},p.paper??{},liveOrders??{}); renderPortfolioDetail(p.portfolio??{},p.paper??{}); renderPositions(positions); renderActiveOrders(positions,pendingOrders); renderAnalyticsSummary(p.analytics??{}); renderJournal(p.analytics?.journal?.trades??[]); renderHealth(p.health??{}); renderOrders(liveOrders??{}); json("portfolio-json",realConnected?p.multiPortfolio:(p.portfolio??{})); json("analytics-json",p.analytics?.performance??p.analytics??{}); state.lastOrders=liveOrders??{}; renderEvents(); }
function animateMetric(id,value){ const n=byId(id); if(!n) return; const fmtVal = id==="metric-balance" ? (x=>"$"+Number(x).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})) : fmt; if(typeof value!=="number"||!Number.isFinite(value)){ n.textContent=fmtVal(value); return; } updateTrend(id.replace("metric-",""),Number(n.dataset.value??0),value); n.dataset.value=String(value); n.textContent=fmtVal(value); }
function updateTrend(name,start,end){ const n=byId(`trend-${name}`); if(!n) return; const d=end-start, dir=d>0?"UP":d<0?"DOWN":"FLAT"; n.textContent=`${dir} ${d?fmt(Math.abs(d)):""}`.trim(); n.className=dir.toLowerCase(); }
function emptyState(title,detail){ return `<div class="empty-state"><span class="empty-mark">--</span><strong>${esc(title)}</strong><small>${esc(detail)}</small></div>`; }
function statusClass(v){ const s=String(v??"").toUpperCase(); if(/ENTRY|BUY|WIN|FILLED|OK|CONNECTED/.test(s)&&!s.includes("REJECT")) return "success"; if(/SELL|LOSS|ERROR|REJECT|DOWN|DISCONNECT/.test(s)) return "danger"; if(/PROCESSING|PENDING|OPEN|NEW|RECONNECT/.test(s)) return "warning"; return "info"; }
function badge(v){ return `<span class="status-badge ${statusClass(v)}">${esc(v??"-")}</span>`; }
function globalSearch(){ return (byId("search")?.value||"").trim().toLowerCase(); }
function matchesQuery(v,q){ return !q || JSON.stringify(v??{}).toLowerCase().includes(q); }
function normalizeSymbols(symbols){ const seen=new Set(); return symbols.map(s=>String(s||"").trim().toUpperCase().replace("-","/")).filter(s=>s&&!seen.has(s)&&seen.add(s)); }
function signalPrice(s){ return s?.price??s?.last_price??s?.current_price??s?.entry??s?.entry_price??null; }
function renderMarket(signals,tracked=[]){ const n=byId("market"); if(!n) return; const filter=byId("market-filter")?.value||"all", q=globalSearch(); const rows=signals.filter(s=>(filter==="all"||s.action===filter)&&matchesQuery(s,q)); const topSymbols=new Set(rows.map(s=>String(s.symbol??"").toUpperCase())); const trackedRows=list(tracked).filter(s=>!topSymbols.has(String(s.symbol??"").toUpperCase())&&matchesQuery(s,q)); const topHtml=rows.map(s=>{ const price=signalPrice(s); return `<div class="item signal-card"><strong><span>${esc(s.symbol??"unknown")}</span>${badge(s.action)}</strong><small>score ${fmt(s.score)} | confidence ${fmt(s.confidence)}${price!=null?` | price ${fmt(Number(price))}`:""}</small></div>`; }).join(""); const trackedHtml=trackedRows.map(s=>{ const price=signalPrice(s); return `<div class="item signal-card tracked"><strong><span>${esc(s.symbol??"unknown")}</span><span class="status-badge info">TRACKED</span></strong><small>open position | price ${price!=null?fmt(Number(price)):"-"} | realtime</small></div>`; }).join(""); const html=topHtml+trackedHtml; n.innerHTML=html||emptyState("No market signals","Scanner output will appear here after the next API refresh."); }
function renderSymbolUniverse(market){ const api=Array.isArray(market?.symbols)?market.symbols:[], configured=normalizeSymbols(Array.isArray(market?.configured_symbols)?market.configured_symbols:[]); state.symbols=normalizeSymbols([...api,...configured]); if(!state.symbols.length) state.symbols=[...FALLBACK_SYMBOLS]; state.configuredSymbols=configured; populateChartSymbols(state.symbols); text("universe-count",`${state.symbols.length} symbols`); text("universe-caption",configured.length?`${configured.length} symbols from bot config + exchange universe.`:"Exchange symbol data unavailable; showing local defaults."); const n=byId("symbol-universe"); if(!n) return; const q=(byId("symbol-filter")?.value||globalSearch()).trim().toLowerCase(); const rows=state.symbols.filter(s=>!q||s.toLowerCase().includes(q)); n.innerHTML=rows.map(s=>`<button type="button" class="symbol-chip${configured.includes(s)?" configured":""}" onclick="setChartSymbol('${esc(s)}')"><strong>${esc(s)}</strong><small>${configured.includes(s)?"config":"exchange"}</small></button>`).join("")||emptyState("No symbols found","Try BTC, ETH, SOL, PEPE, or LINK."); }
function populateChartSymbols(symbols){ const sel=byId("chart-symbol"); if(!sel||!symbols?.length) return; if(!symbols.includes(state.chartSymbol)) state.chartSymbol=symbols[0]; sel.innerHTML=symbols.map(s=>`<option value="${esc(s)}"${s===state.chartSymbol?" selected":""}>${esc(s)}</option>`).join(""); }
function summaryTile(label,value,detail="",icon=""){ return `<div class="summary-tile"><small>${esc(label)}</small><strong>${esc(fmt(value))}</strong>${detail?`<span>${esc(detail)}</span>`:""}${icon?`<em>${esc(icon)}</em>`:""}</div>`; }
function renderPortfolioSummary(portfolio,paper,liveOrders){ const n=byId("portfolio-summary"); if(!n) return; const orders=orderHistory(liveOrders), positions=positionsFrom(portfolio,paper), equity=Number(portfolio?.equity??paper?.equity??0), available=Number(portfolio?.available_balance??paper?.available_balance??0), exposure=Math.max(equity-available,0), openCount=Number(portfolio?.open_positions_count??positions.length); n.innerHTML=[summaryTile("Total Equity",money(equity),"synced account","EQ"),summaryTile("Available",money(available),"free balance","BL"),summaryTile("Exposure",money(exposure),`${openCount} open positions`,"PX"),summaryTile("Orders",orders.length,"live history","OR")].join(""); }
function renderPortfolioDetail(portfolio,paper){ const n=byId("portfolio-detail"); if(!n) return; const positions=positionsFrom(portfolio,paper), fills=list(paper?.fills); const allocation=positions.length?positions.slice(0,6).map(p=>{ const qty=Number(p.quantity??p.qty??p.amount??0), price=Number(p.average_entry_price??p.entry_price??p.price??0); return `<div class="allocation-row"><span>${esc(p.symbol??"unknown")}</span><strong>${fmt(qty)}</strong><small>${money(qty*price)}</small></div>`; }).join(""):emptyState("No allocation yet","Portfolio cards stay ready and will update when positions are reported."); n.innerHTML=`<div class="portfolio-hero"><div><small>Portfolio Source</small><strong>${esc(portfolio?.source??"paper/live sync")}</strong><span>Read-only account reconciliation</span></div><div><small>Last Update</small><strong>${esc(portfolio?.timestamp??paper?.updated_at??"-")}</strong><span>${fills.length} recent fills tracked</span></div></div><div class="allocation-list">${allocation}</div>`; }
function runtimeModeLabel(mode){ const value=String(mode||"").toLowerCase(); if(value==="paper") return "PAPER"; if(value==="dry-run"||value==="live-dry-run") return "DRY RUN"; if(value==="live") return "LIVE"; return value ? value.toUpperCase() : "PAPER"; }
function renderRuntimeBadges(data){
  const account = Number(data?.accounts_connected??0)>0;
  const hasExchangeData = !!(data?.active_execution_exchange || data?.accounts?.length);
  const mode = runtimeModeLabel(data?.bot_mode);
  const liveExecution = mode === "LIVE";
  const primary = exchangeLabel(data?.active_execution_exchange || "binance").toUpperCase();
  const displayed = list(data?.displayed_exchanges).map(exchangeLabel);
  const source = displayed.length === 1 ? displayed[0].toUpperCase() : primary;
  const view = data?.view_mode === "multi" ? "MULTI" : source;
  const exchangeBadge = byId("exchange-badge");
  const modeBadge = byId("mode-badge");
  const viewBadge = byId("portfolio-view-badge");
  if(exchangeBadge) exchangeBadge.textContent = data?.view_mode === "multi" ? "EXCHANGES" : (hasExchangeData ? source : "...");
  if(modeBadge){ modeBadge.textContent = account ? `${view} DATA · ${mode}` : (hasExchangeData ? `NO REAL DATA · ${mode}` : "LOADING..."); modeBadge.className = `market-badge ${liveExecution ? "live" : (mode === "DRY RUN" ? "dry" : "paper")}`; }
  if(viewBadge) viewBadge.textContent = hasExchangeData ? `Portfolio ${view}` : "Portfolio ...";
  text("balance-source-badge",account?(data?.view_mode==="multi"?"Multi Real":`${source} Real`):hasExchangeData?"Paper":"...");
  text("balance-source-caption",account?"real exchange account":hasExchangeData?"paper simulation account":"loading...");
  text("pnl-stream-status", account ? `${view} REAL DATA` : hasExchangeData ? "PAPER DATA" : "...");
}
function renderRealPortfolioSummary(data){
  const n=byId("portfolio-summary");
  if(!n) return;
  n.innerHTML=[
    summaryTile("USDT Available",data?.available_balance_usdt===null?"separate":money(data?.available_balance_usdt),"real account sync","BL"),
    summaryTile("Accounts",data?.accounts_connected??0,"connected","AC"),
    summaryTile("Positions",data?.open_positions_count??0,"real open positions","PX"),
    summaryTile("Orders",data?.open_orders_count??0,"real open orders","OR"),
  ].join("");
}
function renderAnalyticsSummary(a){ const n=byId("analytics-summary"); if(!n) return; const p=a?.performance??a??{}, j=a?.journal??{}, trades=Array.isArray(j?.trades)?j.trades.length:0; n.innerHTML=[summaryTile("Total Return",p.total_return??p.total_return_pct??0,"performance","TR"),summaryTile("Win Rate",p.win_rate??0,"closed trades","WR"),summaryTile("Max Drawdown",p.max_drawdown??0,"risk","DD"),summaryTile("Trades",p.trades_count??trades,"journal","TJ")].join(""); }
function renderPositions(pos){ const n=byId("positions"); if(!n) return; n.innerHTML=pos.map(p=>{ const qty=p.quantity??p.qty??p.remaining_size??p.size; const entry=p.average_entry_price??p.entry_price??p.entry??p.price; const current=p.last_price??p.current_price??p.mark_price??p.price; const pnl=p.unrealized_pnl; return `<div class="item"><strong><span>${esc(p.symbol??"unknown")}</span><b>${fmt(qty)}</b></strong><small>entry ${fmt(entry)} | current ${fmt(current)}${pnl!==undefined?` | PnL ${fmt(pnl)}`:""} | ${esc(p.side??p.source??"portfolio")}</small></div>`; }).join("")||emptyState("No open positions","Exposure is clear while no positions are reported."); }
// Panel Orders: shell tabel di-mount sekali supaya container pemilik scroll tidak
// ikut dibuat ulang tiap render. Hanya tbody / list card mobile yang dipatch.
const AO_SHELL='<div class="ao-scroll desktop-only"><table class="ao-table"><thead><tr><th>Symbol</th><th>Arah</th><th>Entry</th><th>Harga Kini</th><th>Stop Loss</th><th>Take Profit</th><th>Trailing</th><th>Modal</th><th>Unrealized PnL</th></tr></thead><tbody></tbody></table></div><div class="mc-list mobile-only"></div>';
const OH_SHELL='<div class="order-history-scroll"><table class="order-history-table"><thead><tr><th>Symbol</th><th>Status</th><th>Qty</th><th>Price</th><th>Modal</th><th>PnL</th><th>Reason</th><th>Time</th></tr></thead><tbody></tbody></table></div>';
function ensureShell(node,shell,probe){ let target=node.querySelector(probe); if(!target){ node.innerHTML=shell; target=node.querySelector(probe); } return target; }
function keepScroll(nodes,mutate){ const saved=nodes.filter(Boolean).map(el=>[el,el.scrollTop,el.scrollLeft]); mutate(); saved.forEach(([el,top,left])=>{ if(top) el.scrollTop=top; if(left) el.scrollLeft=left; }); }
function patchActiveOrders(node,rows){ const tbody=ensureShell(node,AO_SHELL,".ao-scroll .ao-table > tbody"); if(!tbody) return; const cards=node.querySelector(".mc-list"); keepScroll([node,node.querySelector(".ao-scroll"),cards],()=>{ tbody.innerHTML=rows.map(r=>r.tr).join(""); if(cards) cards.innerHTML=rows.map(r=>r.card).join(""); }); }
function patchOrderHistory(node,rowsHtml){ const tbody=ensureShell(node,OH_SHELL,".order-history-scroll .order-history-table > tbody"); if(!tbody) return; keepScroll([node,node.querySelector(".order-history-scroll")],()=>{ tbody.innerHTML=rowsHtml; }); }
function positionMargin(p,entry,size){ const stored=Number(p?.used_capital); if(Number.isFinite(stored)&&stored>=0) return stored; const notional=Number(p?.notional); const exposure=Number.isFinite(notional)&&notional>0?Math.abs(notional):entry*size; const leverage=Math.max(Number(p?.leverage??p?.configured_leverage??1)||1,1); return exposure/leverage; }
function renderActiveOrders(pos,pending=[]){ const n=byId("active-orders"); if(!n) return; const all=[...(pos||[]),...(pending||[]).map(o=>({...o,pending_order:true,last_price:o.current_price??o.entry}))]; if(!all.length){ n.innerHTML=emptyState("Tidak ada order aktif","Posisi dan limit order aktif akan muncul di sini."); return; } const rows=all.map(p=>{ const sym=p.symbol??"unknown"; const side=String(p.side||"BUY").toUpperCase(); const isShort=side==="SHORT"||side==="SELL"; const dirLabel=p.pending_order?`${isShort?"SHORT":"LONG"} LIMIT`:(isShort?"SHORT":"LONG"); const dirCls=isShort?"dir-short":"dir-long"; const entry=Number(p.entry??p.entry_price??p.average_entry_price??p.price??0); const current=Number(p.last_price??p.current_price??p.mark_price??p.price??entry); const sl=Number(p.stop_loss??p.sl??0); const tp1=Array.isArray(p.take_profit)?Number(p.take_profit[0]??0):Number(p.take_profit??0); const trailing=Number(p.trailing_stop_loss??0); const trailingActive=!!p.trailing_active; const size=Number(p.remaining_size??p.quantity??p.qty??p.size??0); const modal=p.pending_order?0:positionMargin(p,entry,size); const pnl=p.pending_order?0:Number(p.unrealized_pnl??((isShort?(entry-current):(current-entry))*size)); const pnlCls=pnl>=0?"pnl-pos":"pnl-neg"; const pnlPct=modal>0?((pnl/modal)*100):0; const distToSl=sl&&entry?Math.abs(((sl-entry)/entry)*100):0; const distToTp=tp1&&entry?Math.abs(((tp1-entry)/entry)*100):0; const slWarn=sl&&current&&(isShort?(current>=sl*0.995):(current<=sl*1.005))?" sl-near":""; const tpWarn=tp1&&current&&(isShort?(current<=tp1*1.005):(current>=tp1*0.995))?" tp-near":""; const levRaw=Number(p.leverage??p.configured_leverage??0); const levBadge=Number.isFinite(levRaw)&&levRaw>=1?`<span class="mc-lev">${levRaw%1===0?levRaw:levRaw.toFixed(1)}x</span>`:""; const tr=`<tr data-symbol="${esc(sym)}" class="${dirCls}">
<td data-label="Symbol"><span class="ao-sym">${esc(sym)}</span></td>
<td data-label="Arah"><span class="ao-dir ${dirCls}">${dirLabel}</span></td>
<td data-label="Entry"><span class="ao-price">${fmtPrice(entry)}</span></td>
<td data-label="Harga Kini"><span class="ao-current" id="ao-price-${esc(sym)}">${fmtPrice(current)}</span></td>
<td data-label="Stop Loss"><span id="ao-sl-${esc(sym)}" class="ao-sl${slWarn}">${sl?fmtPrice(sl):"-"}${sl&&distToSl?`<small>SL ${distToSl.toFixed(2)}%</small>`:""}</span></td>
<td data-label="Take Profit"><span class="ao-tp${tpWarn}">${tp1?fmtPrice(tp1):"-"}${tp1&&distToTp?`<small>${distToTp.toFixed(2)}% · RR ${Number(p.actual_risk_reward??0).toFixed(2)} · ${Number(p.take_profit_order_count??0)} order</small>`:""}</span></td>
<td data-label="Trailing"><span id="ao-trailing-${esc(sym)}" class="ao-trail ${trailingActive?"trail-active":""}">${trailing?fmtPrice(trailing):"-"}${trailingActive?" ●":""}</span></td>
<td data-label="Modal"><span class="ao-capital">${p.pending_order?"WAIT":moneyFull(modal)}</span><small>${p.pending_order?`exp ${esc(p.expires_at??"-")}`:`${fmt(size)} unit`}</small></td>
<td data-label="Unrealized PnL"><span class="ao-pnl ${pnlCls}" id="ao-pnl-${esc(sym)}">${p.pending_order?"PENDING":`${pnl>=0?"+":""}${moneyFull(pnl)}<small>${pnlPct>=0?"+":""}${pnlPct.toFixed(2)}%</small>`}</span></td>
</tr>`; const card=`<article class="mc-card ${dirCls}" data-symbol="${esc(sym)}"><div class="mc-top"><div class="mc-pair"><span class="mc-sym">${esc(sym)}</span><span class="mc-tags"><span class="mc-dir ${dirCls}">${dirLabel}</span>${levBadge}</span></div><div class="mc-right"><strong class="${p.pending_order?"":pnlCls}" id="ao-pnl-m-${esc(sym)}">${p.pending_order?"PENDING":`${pnl>=0?"+":""}${moneyFull(pnl)}`}</strong><small>${p.pending_order?"limit":`${pnlPct>=0?"+":""}${pnlPct.toFixed(2)}% pnl`}</small></div></div><div class="mc-metrics"><div class="mc-metric"><em>Entry</em><span>${fmtPrice(entry)}</span></div><div class="mc-metric"><em>Harga Kini</em><span id="ao-price-m-${esc(sym)}">${fmtPrice(current)}</span></div><div class="mc-metric${slWarn}"><em>Stop Loss</em><span>${sl?fmtPrice(sl):"-"}</span>${sl&&distToSl?`<small>SL ${distToSl.toFixed(2)}%</small>`:""}</div><div class="mc-metric${tpWarn}"><em>Take Profit</em><span>${tp1?fmtPrice(tp1):"-"}</span>${tp1&&distToTp?`<small>${distToTp.toFixed(2)}%</small>`:""}</div><div class="mc-metric"><em>Trailing</em><span>${trailing?fmtPrice(trailing):"-"}${trailingActive?" ●":""}</span></div><div class="mc-metric"><em>Modal</em><span>${p.pending_order?"WAIT":moneyFull(modal)}</span><small>${p.pending_order?`exp ${esc(p.expires_at??"-")}`:`${fmt(size)} unit`}</small></div></div></article>`; return {tr,card}; }); patchActiveOrders(n,rows); }
function fmtPrice(v){ const n=Number(v); if(!n||!Number.isFinite(n)) return "-"; if(n>=1000) return "$"+n.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2}); if(n>=1) return "$"+n.toLocaleString(undefined,{minimumFractionDigits:4,maximumFractionDigits:4}); return "$"+n.toLocaleString(undefined,{minimumFractionDigits:6,maximumFractionDigits:8}); }
function moneyFull(v){ const n=Number(v??0); return (n<0?"-$":"$")+Math.abs(n).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2}); }
function renderJournal(trades){ const n=byId("journal-list"); if(!n) return; const q=(byId("journal-filter")?.value||"").toLowerCase(), rows=trades.filter(t=>JSON.stringify(t).toLowerCase().includes(q)).slice(-40).reverse(); n.innerHTML=rows.length?`<table><thead><tr><th>Symbol</th><th>Net PnL</th><th>Entry</th><th>Exit</th></tr></thead><tbody>${rows.map(t=>`<tr><td data-label="Symbol">${esc(t.symbol??"unknown")}</td><td data-label="Net PnL"><b>${fmt(t.net_pnl??0)}</b></td><td data-label="Entry">${esc(t.entry_time??"-")}</td><td data-label="Exit">${esc(t.exit_time??"-")}</td></tr>`).join("")}</tbody></table>`:emptyState("No closed trades","Completed trades will build a searchable journal here."); }
function renderOrders(orders){ const n=byId("live-orders"); if(!n) return; const h=[...orderHistory(orders)].sort((a,b)=>String(b.closed_at??b.update_time??"").localeCompare(String(a.closed_at??a.update_time??""))); if(!h.length){ n.innerHTML=emptyState("Tidak ada posisi selesai hari ini","Posisi yang ditutup penuh pada sesi hari ini akan muncul di sini."); return; } const rows=h.slice(0,100).map(o=>{ const sym=o.symbol??o.pair??"-"; const side=String(o.side??o.action??"-").toUpperCase(); const isShort=side==="SHORT"||side==="SELL"; const dirLabel=`${isShort?"SHORT":"LONG"} CLOSED`; const dirCls=isShort?"order-short":"order-long"; const status="CLOSED"; const qty=Number(o.quantity??o.qty??0); const price=Number(o.entry??o.entry_price??o.price??0); const pnl=o.pnl??o.realized_pnl??o.net_pnl; const modal=Number(o.modal??o.capital??0); const reason=String(o.reason??o.close_reason??"").replace(/[_-]+/g," "); const time=o.closed_at??o.update_time??"-"; const timeShort=String(time).includes("T")?String(time).split("T")[1].slice(0,8):String(time).slice(-8); const pnlNum=pnl===undefined||pnl===null?null:Number(pnl); const pnlCls=pnlNum===null?"":(pnlNum>=0?"pnl-pos":"pnl-neg"); return `<tr class="order-row ${dirCls}"><td data-label="Symbol" class="order-sym"><span>${esc(sym)}</span><small class="order-dir ${dirCls}">${dirLabel}</small></td><td data-label="Status" class="order-status"><span class="order-badge status-filled">${status}</span></td><td data-label="Qty" class="order-qty">${fmt(qty)}</td><td data-label="Entry" class="order-price">${price?fmtPrice(price):"-"}</td><td data-label="Modal" class="order-modal">${modal&&Number.isFinite(modal)?moneyFull(modal):"-"}</td><td data-label="PnL" class="order-pnl">${pnlNum===null?"-":`<span class="${pnlCls}">${pnlNum>=0?"+":""}${moneyFull(pnl)}</span>`}</td><td data-label="Reason" class="order-reason"><span>${esc(reason||"Reason bot tidak tersedia")}</span></td><td data-label="Time" class="order-time"><span>${esc(timeShort)}</span><small>${esc(String(time).slice(0,10))}</small></td></tr>`; }).join(""); patchOrderHistory(n,rows); }
function renderHealth(h){ json("health-json",{status:h.status,cpu:h.cpu,ram:h.ram,disk:h.disk,latency_ms:h.latency_ms,exchange_status:h.exchange_status,artifacts:h.artifacts}); }
function renderEventsNow(){ const n=byId("events"); if(!n) return; n.innerHTML=state.liveEvents.slice(-100).reverse().map(e=>`<div class="item event-row"><strong><span>${esc(e.event_type??e.type??"event")}</span><b>${esc(e.occurred_at??"")}</b></strong><small>${esc(JSON.stringify(e.payload??{}))}</small></div>`).join("")||emptyState("Waiting for events","Realtime Event Bus updates will stream into this panel."); }
function renderEvents(){ if(state.renderEventsTimer) return; state.renderEventsTimer=requestAnimationFrame(()=>{ state.renderEventsTimer=null; renderEventsNow(); }); }
function renderCharts(payload){ renderApexChart(payload); ensureTradingViewChart(); }
function renderApexChartLegacy(payload){ if(!window.ApexCharts||!byId("pnl-chart")) return; const data=[Number(payload.paper?.balance??0),Number(payload.portfolio?.equity??0)]; if(!state.apexChart){ state.apexChart=new ApexCharts(byId("pnl-chart"),{chart:{type:"area",height:220,toolbar:{show:false},foreColor:"#64748b",animations:{enabled:true}},theme:{mode:"light"},series:[{name:"Equity",data}],stroke:{curve:"smooth",width:3},fill:{type:"gradient",gradient:{opacityFrom:.32,opacityTo:.02}},colors:["#2563eb"],grid:{borderColor:"rgba(100,116,139,.16)"}}); state.apexChart.render(); } else state.apexChart.updateSeries([{name:"Equity",data}],true); }
function ensureTradingViewChart(){ const node=byId("tv-chart"); if(!node||state.tvChart) return; if(!window.LightweightCharts){ renderFallbackChart([],"Chart library unavailable. Fallback is active."); return; } try{ state.tvChart=LightweightCharts.createChart(node,{height:node.clientHeight||460,layout:{background:{color:"transparent"},textColor:"#64748b"},grid:{vertLines:{color:"rgba(100,116,139,.10)"},horzLines:{color:"rgba(100,116,139,.10)"}},rightPriceScale:{borderColor:"rgba(100,116,139,.18)"},timeScale:{borderColor:"rgba(100,116,139,.18)",timeVisible:true,secondsVisible:false},crosshair:{mode:1}}); state.tvSeries=state.tvChart.addCandlestickSeries({upColor:"#16a34a",downColor:"#dc2626",borderUpColor:"#16a34a",borderDownColor:"#dc2626",wickUpColor:"#16a34a",wickDownColor:"#16a34a"}); state.tvVolumeSeries=state.tvChart.addHistogramSeries({priceFormat:{type:"volume"},priceScaleId:"",color:"rgba(37,99,235,.32)"}); state.tvVolumeSeries.priceScale().applyOptions({scaleMargins:{top:.82,bottom:0}}); resizeCharts(); if(state.chartExchange) loadKlines().catch(err=>renderFallbackChart([],err.message)); } catch(err){ console.warn("chart init failed",err); renderFallbackChart([],err.message); } if(!state.chartRefreshTimer) state.chartRefreshTimer=setInterval(()=>{ if(state.chartExchange) loadKlines().catch(()=>{}); },60000); }
function renderApexChart(payload){ if(!window.ApexCharts||!byId("pnl-chart")) return; const real=String(state.executionMode||payload?.execution_mode||"paper").toLowerCase()!=="paper"; const source=real?(payload?.multiPortfolio??payload?.multi_portfolio??{}):(payload?.paper??{}); const data=[Number(source.balance??source.account_balance_usdt??0),Number(source.equity??source.equity_usdt??source.balance??0)]; if(!state.apexChart){ state.apexChart=new ApexCharts(byId("pnl-chart"),{chart:{type:"area",height:220,toolbar:{show:false},foreColor:"#64748b",animations:{enabled:true}},theme:{mode:"light"},series:[{name:"Equity",data}],stroke:{curve:"smooth",width:3},fill:{type:"gradient",gradient:{opacityFrom:.32,opacityTo:.02}},colors:["#2563eb"],grid:{borderColor:"rgba(100,116,139,.16)"}}); state.apexChart.render(); } else state.apexChart.updateSeries([{name:"Equity",data}],true); }
async function loadKlines(){ if(state.chartLoading||!state.chartExchange) return; state.chartLoading=true; text("chart-caption",`${state.chartSymbol} @ ${state.chartTimeframe} | ${state.chartExchange} | loading candles...`); const params=new URLSearchParams({symbol:state.chartSymbol,timeframe:state.chartTimeframe,exchange:state.chartExchange,limit:String(state.chartLimit)}); try{ const p=await getJson(`/api/klines?${params.toString()}`); applyKlines(p); } catch(err){ renderFallbackChart([],`API candles unavailable: ${err.message}`); throw err; } finally{ state.chartLoading=false; } }
function normalizeCandles(candles){ const seen=new Set(), priceRows=[], volumeRows=[]; for(const c of candles){ const time=Number(c?.time); if(!Number.isFinite(time)||time<=0||seen.has(time)) continue; seen.add(time); const open=Number(c.open??0), high=Number(c.high??open), low=Number(c.low??open), close=Number(c.close??open); priceRows.push({time,open,high,low,close}); volumeRows.push({time,value:Number(c.volume??0),color:close>=open?"rgba(22,163,74,.42)":"rgba(220,38,38,.42)"}); } priceRows.sort((a,b)=>a.time-b.time); volumeRows.sort((a,b)=>a.time-b.time); return {priceRows,volumeRows}; }
function applyKlines(payload){ const rows=normalizeCandles(Array.isArray(payload?.candles)?payload.candles:[]); if(state.tvSeries&&state.tvVolumeSeries){ state.tvSeries.setData(rows.priceRows); state.tvVolumeSeries.setData(rows.volumeRows); state.chartLastCandle=rows.priceRows.at(-1)||null; if(rows.priceRows.length) state.tvChart?.timeScale().fitContent(); } else renderFallbackChart(rows.priceRows,"Fallback chart active."); const source=payload?.source?` | source ${payload.source}`:"", warning=payload?.warning?` | ${payload.warning}`:""; text("chart-caption",`${payload?.symbol??state.chartSymbol} @ ${payload?.timeframe??state.chartTimeframe} | ${rows.priceRows.length} candles${source}${warning}`); }
function timeframeSeconds(tf){ const match=String(tf||"1h").match(/^(\d+)(m|h|d)$/i); if(!match) return 3600; const value=Number(match[1]); return value*(match[2].toLowerCase()==="m"?60:match[2].toLowerCase()==="h"?3600:86400); }
function updateRealtimeChart(payload){ if(!state.tvSeries||String(payload?.symbol||"").toUpperCase()!==String(state.chartSymbol||"").toUpperCase()||!Number(payload?.price)) return; const price=Number(payload.price); const bucket=Math.floor((Number(payload.timestamp?Date.parse(payload.timestamp):Date.now())||Date.now())/1000/timeframeSeconds(state.chartTimeframe))*timeframeSeconds(state.chartTimeframe); const previous=state.chartLastCandle; const candle=previous&&previous.time===bucket?{...previous,high:Math.max(previous.high,price),low:Math.min(previous.low,price),close:price}:{time:bucket,open:previous?.close??price,high:price,low:price,close:price}; state.chartLastCandle=candle; state.tvSeries.update(candle); state.tvChart?.timeScale().scrollToRealTime(); }
function subscribeChartSymbol(){ if(state.ws?.readyState!==WebSocket.OPEN||state.chartExchange!=="bitunix") return; state.ws.send(JSON.stringify({type:"chart_subscribe",symbol:state.chartSymbol})); }
function makeSyntheticCandles(){ const now=Math.floor(Date.now()/1000); let price=state.chartSymbol.startsWith("BTC")?65000:state.chartSymbol.startsWith("ETH")?3200:100; return Array.from({length:64},(_,i)=>{ const open=price, wave=Math.sin(i/4)*price*.006, close=Math.max(.0001,open+wave+(i%5-2)*price*.001); price=close; return {time:now-(63-i)*3600,open,high:Math.max(open,close)*1.004,low:Math.min(open,close)*.996,close}; }); }
function renderFallbackChart(rows,message){ const n=byId("tv-chart"); if(!n) return; n.innerHTML=`<div class="empty-state"><span class="empty-mark">--</span><strong>${esc(state.chartSymbol)} data unavailable</strong><small>${esc(message||"Market candles are not available.")}</small></div>`; text("chart-caption",`${state.chartSymbol} @ ${state.chartTimeframe} | no market data`); }
function setChartSymbol(symbol){ if(!symbol) return; state.chartSymbol=symbol; subscribeChartSymbol(); const sel=byId("chart-symbol"); if(sel) sel.value=symbol; showView("scanner"); ensureTradingViewChart(); loadKlines().catch(err=>showToast(`chart: ${err.message}`)); }
function setChartTimeframe(tf){ if(!tf||tf===state.chartTimeframe) return; state.chartTimeframe=tf; loadKlines().catch(err=>showToast(`chart: ${err.message}`)); }
function sortOrders(){ const orders=state.lastOrders||{}, h=[...orderHistory(orders)].sort((a,b)=>String(b.update_time||b.updated_at||b.created_at||"").localeCompare(String(a.update_time||a.updated_at||a.created_at||""))); renderOrders({...orders,order_history:h}); }
function setWsStatus(s){ const n=byId("ws-status"); if(!n) return; n.textContent=s; n.className=`pill ws ${s.toLowerCase()}`; }
function symbolKey(symbol){ return String(symbol||"").toUpperCase().replace(/[^A-Z0-9]/g,""); }
function patchActiveOrderStops(position){ const symbol=position?.symbol; if(!symbol) return; const entry=Number(position.entry??position.entry_price??position.average_entry_price??position.price??0); const current=Number(position.last_price??position.current_price??position.mark_price??entry); const side=String(position.side||"BUY").toUpperCase(); const isShort=side==="SHORT"||side==="SELL"; const sl=Number(position.stop_loss??position.sl??0); const trailing=Number(position.trailing_stop_loss??0); const trailingActive=!!position.trailing_active; const slWarn=sl&&current&&(isShort?(current>=sl*0.995):(current<=sl*1.005))?" sl-near":""; const slNode=byId(`ao-sl-${symbol}`); if(slNode){ slNode.className=`ao-sl${slWarn}`; slNode.innerHTML=`${sl?fmtPrice(sl):"-"}${sl&&entry?`<small>SL ${Math.abs(((sl-entry)/entry)*100).toFixed(2)}%</small>`:""}`; } const trailingNode=byId(`ao-trailing-${symbol}`); if(trailingNode){ trailingNode.className=`ao-trail ${trailingActive?"trail-active":""}`; trailingNode.textContent=`${trailing?fmtPrice(trailing):"-"}${trailingActive?" ●":""}`; } }
function handlePriceUpdate(payload){ const sym=payload?.symbol; const price=Number(payload?.price); if(!sym||!price) return; const p=state.lastPayload; const realConnected=Number(p.multiPortfolio?.accounts_connected??0)>0; const tickKey=symbolKey(sym); const apply=pos=>{ if(!pos||symbolKey(pos.symbol)!==tickKey) return false; const entry=Number(pos.entry??pos.entry_price??pos.average_entry_price??pos.price??0); const size=Number(pos.remaining_size??pos.quantity??pos.qty??pos.size??0); const side=String(pos.side||"BUY").toUpperCase(); const dir=side==="SHORT"||side==="SELL"?-1:1; pos.last_price=price; pos.current_price=price; if(entry&&size) pos.unrealized_pnl=(price-entry)*size*dir; return true; }; let updated=false; list(p.paper?.open_positions).forEach(pos=>{ updated=apply(pos)||updated; }); list(p.portfolio?.open_positions).forEach(pos=>{ updated=apply(pos)||updated; }); list(p.multiPortfolio?.positions).forEach(pos=>{ updated=apply(pos)||updated; }); list(p.paper?.pending_orders).forEach(ord=>{ if(ord&&symbolKey(ord.symbol)===tickKey){ ord.current_price=price; ord.last_price=price; updated=true; } }); const uiPosition=[...list(p.multiPortfolio?.positions),...list(p.portfolio?.open_positions),...list(p.paper?.open_positions)].find(pos=>symbolKey(pos?.symbol)===tickKey); const uiSym=uiPosition?.symbol||sym; const priceEl=byId(`ao-price-${uiSym}`); if(priceEl){ priceEl.textContent=fmtPrice(price); updated=true; }
  // Mobile Active Orders cards (mc-card) use *-m- ids; keep them in sync with P&L Stream.
  const priceElM=byId(`ao-price-m-${uiSym}`); if(priceElM){ priceElM.textContent=fmtPrice(price); updated=true; }
  if(updated){ const positions=realConnected?list(p.multiPortfolio.positions):positionsFrom(p.portfolio,p.paper); const pos=positions.find(p=>symbolKey(p.symbol)===tickKey); if(pos){ const entry=Number(pos.entry??pos.entry_price??pos.average_entry_price??pos.price??0); const size=Number(pos.remaining_size??pos.quantity??pos.qty??pos.size??0); const modal=positionMargin(pos,entry,size); const pnl=Number(pos.unrealized_pnl??0); const pnlPct=modal>0?((pnl/modal)*100):0; const pnlHtml=`${pnl>=0?"+":""}${moneyFull(pnl)}<small>${pnlPct>=0?"+":""}${pnlPct.toFixed(2)}%</small>`; const pnlEl=byId(`ao-pnl-${uiSym}`); if(pnlEl){ pnlEl.className=`ao-pnl ${pnl>=0?"pnl-pos":"pnl-neg"}`; pnlEl.innerHTML=pnlHtml; } const pnlElM=byId(`ao-pnl-m-${uiSym}`); if(pnlElM){ pnlElM.className=pnl>=0?"pnl-pos":"pnl-neg"; pnlElM.textContent=`${pnl>=0?"+":""}${moneyFull(pnl)}`; const pctEl=pnlElM.parentElement?.querySelector("small"); if(pctEl) pctEl.textContent=`${pnlPct>=0?"+":""}${pnlPct.toFixed(2)}% pnl`; } } if(!realConnected){ const equity=Number(p.paper?.balance||0)+positions.reduce((s,po)=>s+Number(po.unrealized_pnl||0),0); if(Number.isFinite(equity)) animateMetric("metric-equity",equity); } if(typeof window.renderPnl==="function"){ const now=Date.now(); if(now-(state.pnlThrottle||0)>300){ state.pnlThrottle=now; const panelSource=typeof window.__livePanelSource==="function"?window.__livePanelSource(p):p.paper; try{ window.renderPnl(panelSource); }catch(e){} try{ if(typeof window.renderStats==="function") window.renderStats(panelSource); }catch(e){} /* Active Orders tidak di-rebuild di sini: harga + PnL sudah dipatch per-sel di atas
   (ao-price-*, ao-pnl-*, ao-price-m-*, ao-pnl-m-*). Perubahan set posisi (open/close
   baru) tetap masuk lewat snapshot berkala, tanpa mereset scroll panel. */ } } } }
function showToast(msg){ const n=byId("toast"); if(!n) return; n.textContent=msg; n.classList.remove("show"); requestAnimationFrame(()=>n.classList.add("show")); clearTimeout(state.toastTimer); state.toastTimer=setTimeout(()=>n.classList.remove("show"),3200); }
function toggleMobileMenu(force){ const m=byId("mobile-menu"); if(!m) return; const open=force===undefined?!m.classList.contains("open"):!!force; m.classList.toggle("open",open); document.body.classList.toggle("menu-open",open); document.querySelector(".nav-menu-btn")?.classList.toggle("menu-open",open); }
function toggleSidebar(){ document.body.classList.toggle("sidebar-collapsed"); localStorage.setItem("sidebarCollapsed",document.body.classList.contains("sidebar-collapsed")?"1":"0"); resizeCharts(); }
function toggleFullscreenChart(){ byId("chart-card")?.classList.toggle("fullscreen-chart"); setTimeout(resizeCharts,120); }
function resizeCharts(){ const node=byId("tv-chart"); if(state.tvChart&&node){ state.tvChart.applyOptions({width:node.clientWidth,height:node.clientHeight||460}); state.tvChart.timeScale().fitContent(); } if(state.apexChart) state.apexChart.updateOptions({chart:{height:byId("pnl-chart")?.clientHeight||220}},false,false); }
function debounce(fn,wait=160){ let timer; return (...args)=>{ clearTimeout(timer); timer=setTimeout(()=>fn(...args),wait); }; }
function tickClock(){ text("clock",new Date().toLocaleTimeString([],{hour:"2-digit",minute:"2-digit",second:"2-digit"})); }
function showView(view){ state.currentView=view||"overview"; document.querySelectorAll("[data-view-section]").forEach(s=>s.classList.toggle("active",s.dataset.viewSection===state.currentView)); document.querySelectorAll("[data-view-link]").forEach(l=>l.classList.toggle("active",l.dataset.viewLink===state.currentView)); const isMenuView=["portfolio","health","agents","settings"].includes(state.currentView); document.querySelector(".nav-menu-btn")?.classList.toggle("active",isMenuView); toggleMobileMenu(false); document.body.dataset.view=state.currentView; history.replaceState(null,"",`#${state.currentView}`); if(state.currentView==="scanner"){ ensureTradingViewChart(); loadKlines().catch(()=>{}); requestAnimationFrame(()=>requestAnimationFrame(resizeCharts)); } setTimeout(resizeCharts,80); if(state.currentView==="agents") loadAgentPanels().catch(console.warn); }
function initUi(){ if(localStorage.getItem("sidebarCollapsed")==="1") document.body.classList.add("sidebar-collapsed"); populateChartSymbols(state.symbols); renderSymbolUniverse({symbols:state.symbols,configured_symbols:[]}); tickClock(); state.clockTimer=setInterval(tickClock,1000); window.addEventListener("resize",debounce(resizeCharts,180),{passive:true}); document.querySelectorAll("[data-view-link]").forEach(link=>link.addEventListener("click",e=>{ e.preventDefault(); showView(link.dataset.viewLink); })); document.addEventListener("keydown",e=>{ if(e.key==="Escape") toggleMobileMenu(false); }); showView(location.hash?.replace("#","")||"overview"); }
function handleEntryCandidateUpdate(payload){ if(!payload||!payload.symbol) return; if(!state.liveEntryCandidates) state.liveEntryCandidates=[]; const ts=payload.timestamp||new Date().toISOString(); const parsed=Date.parse(ts); state.lastEntryLiveTs=Number.isFinite(parsed)?parsed:Date.now(); const row={symbol:payload.symbol,scanner_confidence:payload.scanner_confidence,scanner_action:payload.scanner_action,soft_entry:payload.soft_entry,result:payload.result,timestamp:ts}; state.liveEntryCandidates=[row,...state.liveEntryCandidates.filter(item=>String(item?.symbol||"").toUpperCase()!==String(payload.symbol).toUpperCase())].slice(0,50); if(state.currentView==="agents"){ const entries=byId("agent-pipeline-entries"); if(entries&&state.liveEntryCandidates.length) entries.innerHTML=renderAgentEntries(state.liveEntryCandidates); } showToast(`Entry: ${payload.symbol}`); }
function handleAgentPipelineUpdate(payload){ if(!payload||typeof payload!=="object") return; state.lastAgentPipeline=payload; const ts=Date.parse(payload.generated_at||""); if(Number.isFinite(ts)) state.lastEntryLiveTs=Math.max(state.lastEntryLiveTs||0,ts); state.liveEntryCandidates=list(payload.entries); if(state.currentView==="agents") renderAgentPipeline(payload,{sync_status:"online"}); }
function disconnectWs(){ clearTimeout(state.wsReconnectTimer); clearTimeout(state.wsSnapshotTimer); state.wsReconnectTimer=null; state.wsSnapshotTimer=null; const ws=state.ws; state.ws=null; if(ws){ ws.onclose=null; ws.close(); } }
function connectWs(){ if(document.hidden||state.ws?.readyState===WebSocket.OPEN||state.ws?.readyState===WebSocket.CONNECTING) return; clearTimeout(state.wsReconnectTimer); state.wsReconnectTimer=null; const protocol=location.protocol==="https:"?"wss":"ws"; setWsStatus("Reconnecting"); const token=document.querySelector('meta[name="dashboard-token"]')?.content||""; const query=token?`?api_key=${encodeURIComponent(token)}`:""; const ws=new WebSocket(`${protocol}://${location.host}/ws${query}`); state.ws=ws; ws.onopen=()=>{ setWsStatus("Connected"); subscribeChartSymbol(); showToast("Websocket connected"); }; ws.onerror=()=>setWsStatus("Disconnected"); ws.onclose=()=>{ if(state.ws===ws) state.ws=null; setWsStatus("Disconnected"); if(!document.hidden){ state.wsReconnectTimer=setTimeout(()=>{ state.wsReconnectTimer=null; setWsStatus("Reconnecting"); connectWs(); },3000); } }; ws.onmessage=msg=>{ let data; try{ data=JSON.parse(msg.data); }catch(err){ console.warn("Invalid websocket payload",err); return; } if(data.type==="snapshot"){ clearTimeout(state.wsSnapshotTimer); if(state.executionMode) state.wsSnapshotTimer=setTimeout(()=>{ render(data.payload); syncDashboardPanels(data.payload); if(typeof window.syncLivePanels==="function") window.syncLivePanels(data.payload); },800); setTimeout(()=>render(data.payload),800); renderEvents(); } if(data.type==="agent_snapshot") renderAgentSnapshot(data.payload); if(data.type==="agent_pipeline_update") handleAgentPipelineUpdate(data.payload); if(data.type==="entry_candidate_processed") handleEntryCandidateUpdate(data.payload); if(data.type==="live_events"){ state.liveEvents=list(data.payload); renderEvents(); } if(data.type==="event"){ state.liveEvents.push(data); showToast(`${data.event_type??"event"} received`); renderEvents(); } if(data.type==="price_update"){ updateRealtimeChart(data.payload); handlePriceUpdate(data.payload); } }; }
function setDashboardActivity(active){ if(active){ if(!state.dashboardRefreshTimer) state.dashboardRefreshTimer=setInterval(()=>loadAll().catch(handleError),10000); connectWs(); loadAll().catch(handleError); return; } clearInterval(state.dashboardRefreshTimer); state.dashboardRefreshTimer=null; disconnectWs(); }
document.addEventListener("change",e=>{ if(e.target?.id==="market-filter") render(state.lastPayload); });
document.addEventListener("input",debounce(e=>{ if(["journal-filter","symbol-filter","search"].includes(e.target?.id)) render(state.lastPayload); },180));
function handleError(err){ console.error(err); setLoading(false); showToast(err.message); if(state.lastPayload) render(state.lastPayload); }

// Global helper used across dashboard.js and templates.
function setText(id, val){ const n = document.getElementById(id); if(n) n.textContent = val; }

// ---------- Settings: Exchange API credentials ----------
async function apiFetch(path, options={}){
  const opts = { cache: "no-store", credentials: "same-origin", ...options };
  opts.headers = { "Content-Type": "application/json", ...dashboardAuthHeaders(), ...(opts.headers || {}) };
  const r = await fetch(path, opts);
  const text = await r.text();
  let data; try { data = text ? JSON.parse(text) : {}; } catch(_) { data = { raw: text }; }
  if(!r.ok){ const raw=String(data.detail||data.error||""); if(raw==="invalid api key") throw new Error("Sesi dashboard tidak valid"); if(raw.includes("new_api_key_required_when_provider_changes")) throw new Error("new_api_key_required_when_provider_changes"); if(path.includes("/settings/llm")) throw new Error(`API key ditolak oleh provider LLM: ${raw||r.status}`); throw new Error(raw || `${path} ${r.status}`); }
  return data;
}
function currentExchange(){
  const sel = byId("settings-exchange-select");
  const value = String(sel?.value || "").toLowerCase();
  return value === "bitunix" ? "bitunix" : "binance";
}
function exchangeLabel(name){
  const n = String(name || "").toLowerCase();
  if(n === "bitunix") return "Bitunix";
  return "Binance";
}
function setSettingsStatus(state, label){
  const badge = byId("settings-status");
  if(!badge) return;
  badge.classList.remove("ok","warn","err");
  if(state) badge.classList.add(state);
  badge.textContent = label;
}
function renderSettingsSummary(s){
  const configured = !!(s && s.configured);
  setText("settings-cur-status", configured ? "Configured" : "Not configured");
  setText("settings-cur-key", configured ? (s.api_key_masked || "-") : "-");
  setText("settings-cur-net", configured ? (s.testnet ? "Testnet" : "Mainnet") : "-");
  setText("settings-cur-updated", configured ? (s.updated_at || "-") : "-");
  const testnetBox = byId("settings-testnet");
  if(testnetBox) testnetBox.checked = configured ? !!s.testnet : false;
  setSettingsStatus(configured ? "ok" : "warn", configured ? "configured" : "not configured");
}
function renderSettingsResult(payload, ok){
  const box = byId("settings-result");
  if(!box) return;
  box.hidden = false;
  box.classList.remove("ok","err");
  box.classList.add(ok ? "ok" : "err");
  box.textContent = typeof payload === "string" ? payload : JSON.stringify(payload, null, 2);
}
function applyExchangeUiHints(){
  const ex = currentExchange();
  const heading = byId("settings-exchange-heading");
  if(heading) heading.textContent = `${exchangeLabel(ex)} API Credentials`;
  const testnetRow = byId("settings-testnet-row");
  if(testnetRow) testnetRow.style.display = (ex === "bitunix") ? "none" : "";
  const testnetHint = byId("settings-testnet-hint");
  if(testnetHint) testnetHint.textContent = (ex === "bitunix")
    ? "Bitunix does not provide a public testnet; requests use production endpoints."
    : "";
  const leverageHint = byId("settings-leverage-hint");
  if(leverageHint) leverageHint.textContent = ex === "bitunix"
    ? "Bitunix leverage limit follows the selected symbol and position tier; the exchange may cap a saved value below 125x."
    : "Binance leverage limit follows the selected symbol and notional bracket; the exchange may cap a saved value below 125x.";
}
function setOptionalNumber(id, value){
  const input = byId(id);
  if(input) input.value = value === null || value === undefined ? "" : String(value);
}
function optionalNumberValue(id){
  const raw = byId(id)?.value.trim();
  if(!raw) return null;
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
}
function syncTradingExitMode(){
  const tp = byId("settings-tp-percent");
  const sl = byId("settings-sl-percent");
  const rr = byId("settings-target-rr");
  if(!tp || !sl || !rr) return;
  const hasRr = rr.value.trim() !== "";
  const hasManual = tp.value.trim() !== "" || sl.value.trim() !== "";
  // Data lama yang ambigu diperlakukan seperti runtime saat ini: RR menang.
  tp.disabled = hasRr;
  sl.disabled = hasRr;
  rr.disabled = !hasRr && hasManual;
  const manualFields = [byId("settings-tp-field"), byId("settings-sl-field")];
  const rrField = byId("settings-rr-field");
  manualFields.forEach(field => {
    field?.classList.toggle("exit-mode-active", hasManual && !hasRr);
    field?.classList.toggle("exit-mode-disabled", hasRr);
  });
  rrField?.classList.toggle("exit-mode-active", hasRr);
  rrField?.classList.toggle("exit-mode-disabled", !hasRr && hasManual);
  const hint = byId("settings-exit-mode-hint");
  if(hint) hint.textContent = hasRr
    ? "Mode Target RR aktif: TP dan SL manual dinonaktifkan; SL berasal dari signal."
    : hasManual
      ? "Mode TP/SL manual aktif: Target RR dinonaktifkan. Kosongkan TP dan SL untuk memakai RR."
      : "Pilih salah satu: Target RR, atau TP/SL manual. Target RR memakai Stop Loss dari signal dan menonaktifkan kolom TP/SL.";
}
function renderTradingSettings(data){
  setOptionalNumber("settings-tp-percent", data.take_profit_percent);
  setOptionalNumber("settings-sl-percent", data.stop_loss_percent);
  setOptionalNumber("settings-trailing-percent", data.trailing_stop_percent);
  setOptionalNumber("settings-target-margin-percent", data.target_margin_percent);
  setOptionalNumber("settings-target-rr", data.target_risk_reward);
  syncTradingExitMode();
  const select = byId("settings-leverage");
  if(select){
    const selected = data.leverage === null || data.leverage === undefined ? "" : String(data.leverage);
    select.innerHTML = '<option value="">Default existing</option>' +
      (data.leverage_options || []).map(value => `<option value="${value}">${value}x</option>`).join("");
    select.value = selected;
  }
}
function setPortfolioSettingsStatus(stateName,label){
  const badge=byId("portfolio-settings-status");
  if(!badge) return;
  badge.classList.remove("ok","warn","err");
  if(stateName) badge.classList.add(stateName);
  badge.textContent=label;
}
function renderPortfolioSettings(data){
  const mode=byId("portfolio-view-mode");
  const active=byId("portfolio-active-exchange");
  const exchange=data?.active_execution_exchange==="bitunix"?"bitunix":"binance";
  if(mode) mode.value=data?.view_mode==="multi"?"multi":"single";
  if(active) active.value=exchange;
  applyPrimaryExchangeUi(exchange);
  setPortfolioSettingsStatus("ok",data?.view_mode==="multi"?"multi enabled":"single exchange");
}
function applyPrimaryExchangeUi(exchange){
  const normalized=exchange==="bitunix"?"bitunix":"binance";
  const credentialSelect=byId("settings-exchange-select");
  const changed=credentialSelect&&credentialSelect.value!==normalized;
  if(credentialSelect) credentialSelect.value=normalized;
  document.querySelectorAll('[data-exchange-only="binance"]').forEach(el=>{
    el.hidden=normalized!=="binance";
  });
  if(changed) loadExchangeSettings();
}
function renderExecutionModeSummary(data){
  const connected=Number(data?.accounts_connected??0)>0;
  const displayed=list(data?.displayed_exchanges).map(exchangeLabel);
  const source=connected?(data?.view_mode==="multi"?"Multi real accounts":`${displayed[0]||exchangeLabel(data?.active_execution_exchange)} real account`):"Paper account";
  const mode=runtimeModeLabel(data?.bot_mode);
  text("execution-account-source",source);
  text("execution-bot-mode",mode);
  text("execution-live-readiness",mode==="LIVE"?"Live enabled":"Locked — no real orders");
}
function onExecutionModeChange(){
  const live=byId("execution-mode-select")?.value==="live";
  const label=byId("execution-live-confirm-label");
  if(label) label.hidden=!live;
  if(!live){ const input=byId("execution-live-confirmation"); if(input) input.value=""; }
}
function renderExecutionSettings(data){
  const mode=byId("execution-mode-select");
  if(mode) mode.value=data?.mode||"paper";
  onExecutionModeChange();
  text("execution-bot-mode",runtimeModeLabel(data?.mode));
  text("execution-live-readiness",data?.network_enabled?"LIVE — real orders enabled":"Locked — no real orders");
}
async function loadExecutionSettings(){
  try{ const data=await apiFetch("/api/settings/execution"); state.executionMode=String(data?.mode||"paper").toLowerCase(); window.__executionMode=state.executionMode; renderExecutionSettings(data); }
  catch(err){ console.warn("Execution settings load failed",err); }
}
async function saveExecutionMode(event){
  event?.preventDefault();
  const box=byId("execution-mode-result");
  try{
    const data=await apiFetch("/api/settings/execution",{
      method:"PUT",
      body:JSON.stringify({
        mode:byId("execution-mode-select")?.value||"paper",
        confirmation:byId("execution-live-confirmation")?.value||"",
      }),
    });
    renderExecutionSettings(data);
    await loadMultiPortfolio();
    if(box){ box.hidden=false; box.className="settings-result ok"; box.textContent=`Execution mode saved: ${runtimeModeLabel(data.mode)} on ${exchangeLabel(data.primary_exchange)}.`; }
    showToast(`Execution mode: ${runtimeModeLabel(data.mode)}`);
  }catch(err){
    if(box){ box.hidden=false; box.className="settings-result err"; box.textContent=err.message; }
  }
  return false;
}
async function triggerKillSwitch(){
  const box=byId("execution-mode-result");
  try{
    const data=await apiFetch("/api/settings/execution/kill",{method:"POST",body:"{}"});
    renderExecutionSettings(data);
    await loadMultiPortfolio();
    if(box){ box.hidden=false; box.className="settings-result ok"; box.textContent="Kill switch active. Runtime returned to Paper; real order submission is blocked."; }
    showToast("Kill switch: Paper mode active");
  }catch(err){ if(box){ box.hidden=false; box.className="settings-result err"; box.textContent=err.message; } }
}
async function loadPortfolioSettings(){
  try{
    const data=await apiFetch("/api/settings/portfolio");
    renderPortfolioSettings(data);
  }catch(err){
    setPortfolioSettingsStatus("err","load failed");
    const box=byId("portfolio-settings-result");
    if(box){ box.hidden=false; box.className="settings-result err"; box.textContent=err.message; }
  }
}
async function savePortfolioSettings(event){
  event?.preventDefault();
  setPortfolioSettingsStatus("warn","saving...");
  try{
    const data=await apiFetch("/api/settings/portfolio",{
      method:"PUT",
      body:JSON.stringify({
        view_mode:byId("portfolio-view-mode")?.value||"single",
        active_execution_exchange:byId("portfolio-active-exchange")?.value||"binance",
      }),
    });
    renderPortfolioSettings(data);
    const box=byId("portfolio-settings-result");
    if(box){ box.hidden=false; box.className="settings-result ok"; box.textContent="Portfolio view saved. Primary routing remains single-exchange and live safety gates are unchanged."; }
    await loadMultiPortfolio();
    showToast("Portfolio view saved");
  }catch(err){
    setPortfolioSettingsStatus("err","save failed");
    const box=byId("portfolio-settings-result");
    if(box){ box.hidden=false; box.className="settings-result err"; box.textContent=err.message; }
  }
  return false;
}
async function loadMultiPortfolio(){
  try{
    const data=await apiFetch("/api/portfolio/multi");
    state.multiPortfolio=data;
    if(state.lastPayload){
      state.lastPayload.multiPortfolio=data;
      render(state.lastPayload);
    }else renderRuntimeBadges(data);
    renderExecutionModeSummary(data);
    return data;
  }catch(err){
    console.warn("Multi-portfolio refresh failed",err);
    return null;
  }
}
async function loadExchangeSettings(){
  applyExchangeUiHints();
  try {
    const ex = currentExchange();
    const [credentials, trading] = await Promise.all([
      apiFetch(`/api/settings/exchange?exchange=${encodeURIComponent(ex)}`),
      apiFetch(`/api/settings/trading?exchange=${encodeURIComponent(ex)}`),
    ]);
    renderSettingsSummary(credentials);
    renderTradingSettings(trading);
  } catch(err) {
    setSettingsStatus("err", "load failed");
    renderSettingsResult(err.message, false);
  }
}
async function saveTradingSettings(){
  const exchange = currentExchange();
  syncTradingExitMode();
  const payload = {
    exchange,
    take_profit_percent: byId("settings-tp-percent")?.disabled ? null : optionalNumberValue("settings-tp-percent"),
    stop_loss_percent: byId("settings-sl-percent")?.disabled ? null : optionalNumberValue("settings-sl-percent"),
    trailing_stop_percent: optionalNumberValue("settings-trailing-percent"),
    leverage: byId("settings-leverage")?.value || null,
    target_margin_percent: optionalNumberValue("settings-target-margin-percent"),
    target_risk_reward: byId("settings-target-rr")?.disabled ? null : optionalNumberValue("settings-target-rr"),
  };
  setSettingsStatus("warn", "saving defaults...");
  try {
    const data = await apiFetch("/api/settings/trading", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    renderTradingSettings(data);
    setSettingsStatus("ok", "defaults saved");
    renderSettingsResult({
      ok: true,
      exchange: data.exchange,
      take_profit_percent: data.take_profit_percent,
      stop_loss_percent: data.stop_loss_percent,
      trailing_stop_percent: data.trailing_stop_percent,
      leverage: data.leverage,
      target_margin_percent: data.target_margin_percent,
      target_risk_reward: data.target_risk_reward,
    }, true);
    showToast(`${exchangeLabel(exchange)} trading defaults saved`);
  } catch(err){
    setSettingsStatus("err", "save failed");
    renderSettingsResult(err.message, false);
  }
}
document.addEventListener("input", event => {
  if(["settings-tp-percent", "settings-sl-percent", "settings-target-rr"].includes(event.target?.id)){
    syncTradingExitMode();
  }
});
async function submitExchangeSettings(event){
  event.preventDefault();
  const exchange = currentExchange();
  const apiKey = byId("settings-api-key")?.value.trim();
  const apiSecret = byId("settings-api-secret")?.value.trim();
  const testnet = !!byId("settings-testnet")?.checked;
  if(!apiKey || !apiSecret){
    renderSettingsResult("api_key and api_secret required", false);
    return false;
  }
  setSettingsStatus("warn", "saving...");
  try {
    const data = await apiFetch("/api/settings/exchange", {
      method: "PUT",
      body: JSON.stringify({
        exchange,
        api_key: apiKey,
        api_secret: apiSecret,
        testnet: exchange === "binance" ? testnet : false,
      }),
    });
    renderSettingsSummary(data);
    renderSettingsResult("Credentials saved. Run Test Connection to verify.", true);
    byId("settings-api-key").value = "";
    byId("settings-api-secret").value = "";
    await loadMultiPortfolio();
    showToast(`${exchangeLabel(exchange)} API credentials saved`);
  } catch(err){
    setSettingsStatus("err", "save failed");
    renderSettingsResult(err.message, false);
  }
  return false;
}
async function testExchangeSettings(){
  const exchange = currentExchange();
  const apiKey = byId("settings-api-key")?.value.trim();
  const apiSecret = byId("settings-api-secret")?.value.trim();
  const testnet = !!byId("settings-testnet")?.checked;
  const body = { exchange };
  if(Boolean(apiKey) !== Boolean(apiSecret)){
    setSettingsStatus("err", "test failed");
    renderSettingsResult("API Key and API Secret must be provided together.", false);
    return;
  }
  if(apiKey && apiSecret){
    body.api_key = apiKey;
    body.api_secret = apiSecret;
    if(exchange === "binance") body.testnet = testnet;
  }
  setSettingsStatus("warn", "testing...");
  try {
    const data = await apiFetch("/api/settings/exchange/test", {
      method: "POST",
      body: JSON.stringify(body),
    });
    const ok = !!data.ok;
    setSettingsStatus(ok ? "ok" : "err", ok ? "connected" : "test failed");
    renderSettingsResult(data, ok);
    if(ok) await loadMultiPortfolio();
  } catch(err){
    setSettingsStatus("err", "test failed");
    renderSettingsResult(err.message, false);
  }
}
async function clearExchangeSettings(){
  const exchange = currentExchange();
  if(!confirm(`Hapus API key ${exchangeLabel(exchange)} yang tersimpan?`)) return;
  try {
    const data = await apiFetch(`/api/settings/exchange?exchange=${encodeURIComponent(exchange)}`, { method: "DELETE" });
    renderSettingsSummary(data);
    renderSettingsResult("Credentials cleared.", true);
    await loadMultiPortfolio();
    showToast("Credentials cleared");
  } catch(err){
    setSettingsStatus("err", "clear failed");
    renderSettingsResult(err.message, false);
  }
}
function onExchangeSelectChange(){
  const key = byId("settings-api-key"); if(key) key.value = "";
  const secret = byId("settings-api-secret"); if(secret) secret.value = "";
  const result = byId("settings-result"); if(result) result.hidden = true;
  loadExchangeSettings();
}

// ---------- Settings: Optional LLM Provider ----------
const LLM_AGENTS = ["chart","learning","decision","executor"];
function setLLMStatus(state,label){ const badge=byId("llm-settings-status"); if(!badge) return; badge.classList.remove("ok","warn","err"); if(state) badge.classList.add(state); badge.textContent=label; }
function renderLLMResult(message, ok){ const box=byId("llm-settings-result"); if(!box) return; box.hidden=false; box.classList.remove("ok","err"); box.classList.add(ok?"ok":"err"); box.textContent=String(message||""); }
function renderLLMSettings(data){
  const models=list(data?.models);
  const configured=!!data?.api_key_configured;
  setText("llm-cur-provider",data?.base_url||"-");
  setText("llm-cur-key",configured?(data.api_key_masked||"configured"):"missing");
  setText("llm-cur-models",models.length?`${models.length} detected`:"none");
  setText("llm-cur-learning",data?.agent_models?.learning||"None");
  const base=byId("llm-base-url"); if(base) base.value=data?.base_url||"";
  const timeout=byId("llm-timeout"); if(timeout) timeout.value=String(data?.timeout_seconds||30);
  LLM_AGENTS.forEach(agent=>{
    const sel=byId(`llm-agent-${agent}`); if(!sel) return;
    const selected=data?.agent_models?.[agent]||"none";
    sel.innerHTML='<option value="none">None — deterministic</option>'+models.map(m=>`<option value="${esc(m)}">${esc(m)}</option>`).join("");
    if(models.includes(selected)) sel.value=selected; else sel.value="none";
  });
  setLLMStatus(configured&&data?.base_url?"ok":"warn",configured&&data?.base_url?"configured":"optional");
}
async function loadLLMSettings(){ try{ renderLLMSettings(await apiFetch("/api/settings/llm")); }catch(err){ setLLMStatus("err","load failed"); renderLLMResult(err.message,false); } }
async function saveLLMProvider(event){
  event?.preventDefault(); setLLMStatus("warn","saving...");
  try{
    const payload={ base_url:byId("llm-base-url")?.value||"", timeout_seconds:Number(byId("llm-timeout")?.value||30) };
    const key=byId("llm-api-key")?.value.trim(); if(key) payload.api_key=key;
    const data=await apiFetch("/api/settings/llm/provider",{method:"PUT",body:JSON.stringify(payload)});
    const keyInput=byId("llm-api-key"); if(keyInput) keyInput.value="";
    renderLLMSettings(data); renderLLMResult("LLM provider saved. Fetch Models to populate dropdowns.",true); showToast("LLM provider saved");
  }catch(err){ setLLMStatus("err","save failed"); renderLLMResult(err.message,false); }
  return false;
}
async function fetchLLMModels(){ setLLMStatus("warn","fetching..."); try{ const data=await apiFetch("/api/settings/llm/models",{method:"POST",body:"{}"}); renderLLMSettings(data); renderLLMResult(`${data.models_found||0} models detected`,true); showToast(`${data.models_found||0} LLM models detected`); }catch(err){ setLLMStatus("err","fetch failed"); renderLLMResult(err.message,false); } }
async function testLLMProvider(){ setLLMStatus("warn","testing..."); try{ const payload={base_url:byId("llm-base-url")?.value||"",timeout_seconds:Number(byId("llm-timeout")?.value||30)}; const key=byId("llm-api-key")?.value.trim(); if(key) payload.api_key=key; const data=await apiFetch("/api/settings/llm/test",{method:"POST",body:JSON.stringify(payload)}); setLLMStatus(data.ok?"ok":"err",data.ok?"connected":"test failed"); renderLLMResult(data.ok?`Connected — ${data.models_found||0} models available`:`Test failed: ${data.error||"unknown error"}`,!!data.ok); }catch(err){ setLLMStatus("err","test failed"); renderLLMResult(err.message,false); } }
async function saveLLMAgentModels(){ setLLMStatus("warn","saving models..."); try{ const agent_models={}; LLM_AGENTS.forEach(agent=>{ agent_models[agent]=byId(`llm-agent-${agent}`)?.value||"none"; }); const data=await apiFetch("/api/settings/llm/agents",{method:"PUT",body:JSON.stringify({agent_models})}); renderLLMSettings(data); renderLLMResult("Agent LLM model assignment saved. None means no LLM.",true); showToast("Agent LLM models saved"); }catch(err){ setLLMStatus("err","save failed"); renderLLMResult(err.message,false); } }
async function clearLLMSettings(){ if(!confirm("Hapus LLM provider, API key, model list, dan assignment agent?")) return; try{ const data=await apiFetch("/api/settings/llm",{method:"DELETE"}); renderLLMSettings(data); renderLLMResult("LLM settings cleared.",true); showToast("LLM settings cleared"); }catch(err){ setLLMStatus("err","clear failed"); renderLLMResult(err.message,false); } }

// Restart bot services via systemd (no double: UI lock + backend file lock).
let _restartBusy=false;
async function restartBot(btn){
  if(_restartBusy) return;
  if(!confirm("Restart bot sekarang?")) return;
  _restartBusy=true;
  const status=byId("restart-bot-status");
  if(btn) btn.disabled=true;
  if(status){ status.textContent="restarting"; status.className="pill warn"; }
  try{
    await apiFetch("/api/settings/restart",{method:"POST",body:"{}"});
  }catch(err){
    // API process dies during self-restart — expected.
  }
  // Poll until API is back (max ~20s).
  let alive=false;
  for(let n=0;n<20;n++){
    try{
      const r=await fetch("/api/health",{cache:"no-store",credentials:"same-origin"});
      if(r.ok){ alive=true; break; }
    }catch(e){}
    await new Promise(res=>setTimeout(res,1000));
  }
  if(status){
    status.textContent=alive?"restarted":"failed";
    status.className="pill "+(alive?"ok":"err");
  }
  if(btn) btn.disabled=false;
  _restartBusy=false;
  // alert = notif pasti kelihatan di Settings (toast cuma di panel Event Stream).
  if(alive) alert("Bot berhasil di-restart.");
  else alert("Restart gagal atau API belum up.");
}



// ---------- Settings: Telegram Notifications ----------
function setTelegramStatus(state, label) {
  const badge = byId("telegram-settings-status");
  if(!badge) return;
  badge.classList.remove("ok", "warn", "err");
  if(state) badge.classList.add(state);
  badge.textContent = label;
}

function renderTelegramResult(message, ok) {
  const box = byId("telegram-settings-result");
  if(!box) return;
  box.hidden = false;
  box.classList.remove("ok", "err");
  box.classList.add(ok ? "ok" : "err");
  box.textContent = typeof message === "string" ? message : JSON.stringify(message, null, 2);
}

function renderTelegramSettings(data) {
  const configured = data.enabled && !!data.bot_token_masked && !!data.chat_id_masked;
  
  setText("telegram-cur-status", configured ? "Enabled" : "Disabled");
  setText("telegram-cur-token", data.bot_token_masked || "-");
  setText("telegram-cur-chat", data.chat_id_masked || "-");
  setText("telegram-cur-updated", data.updated_at || "-");
  
  const enabledBox = byId("telegram-enabled");
  if(enabledBox) enabledBox.checked = !!data.enabled;
  
  // Don't show actual tokens in input fields for security
  byId("telegram-bot-token").value = "";
  byId("telegram-chat-id").value = "";
  
  setTelegramStatus(configured ? "ok" : "warn", configured ? "configured" : "not configured");
}

async function loadTelegramSettings() {
  try {
    const data = await apiFetch("/api/settings/telegram");
    renderTelegramSettings(data);
  } catch(err) {
    setTelegramStatus("err", "load failed");
    renderTelegramResult(err.message, false);
  }
}

async function saveTelegramSettings(event) {
  event?.preventDefault();
  const botToken = byId("telegram-bot-token")?.value.trim();
  const chatId = byId("telegram-chat-id")?.value.trim();
  const enabled = byId("telegram-enabled")?.checked || false;
  
  // Validate: if enabled, both token and chat_id required
  if (enabled && (!botToken || !chatId)) {
    renderTelegramResult("Both Bot Token and Chat ID are required when enabling Telegram notifications.", false);
    setTelegramStatus("err", "validation failed");
    return false;
  }
  
  setTelegramStatus("warn", "saving...");
  try {
    const payload = {
      enabled: enabled,
      bot_token: botToken || null,
      chat_id: chatId || null,
    };
    
    const data = await apiFetch("/api/settings/telegram", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    
    renderTelegramSettings(data);
    renderTelegramResult("Telegram settings saved successfully!", true);
    showToast("Telegram notifications configured");
    
    // Clear input fields after save
    byId("telegram-bot-token").value = "";
    byId("telegram-chat-id").value = "";
  } catch(err) {
    setTelegramStatus("err", "save failed");
    renderTelegramResult(err.message, false);
  }
  return false;
}

async function clearTelegramSettings() {
  if(!confirm("Clear all Telegram notification settings? This will disable notifications.")) return;
  
  try {
    const data = await apiFetch("/api/settings/telegram/clear", { method: "POST" });
    renderTelegramSettings(data);
    renderTelegramResult("Telegram settings cleared.", true);
    showToast("Telegram settings cleared");
  } catch(err) {
    setTelegramStatus("err", "clear failed");
    renderTelegramResult(err.message, false);
  }
}

async function testTelegramConnection(){
  const btn = byId("telegram-test-btn");
  if(!btn) return;
  
  btn.disabled = true;
  btn.textContent = "Testing...";
  btn.classList.add("loading");
  
  try {
    setTelegramStatus("warn", "testing connection...");
    const result = await apiFetch("/api/settings/telegram/test", {
      method: "POST",
      body: JSON.stringify({}),
    });
    
    if(result.ok){
      const details = result.details || {};
      const message = `Connection successful!\n` +
        `Message ID: ${details.message_id || '-'}\n` +
        `From: ${details.from_username || 'Unknown'}\n` +
        `Check your Telegram app for the test message.`;
      
      setTelegramStatus("ok", "connected");
      const resultBox = byId("telegram-test-result");
      if(resultBox){ resultBox.hidden=false; resultBox.className="settings-result ok"; resultBox.textContent=message; }
      showToast("Test message sent to Telegram!");
    } else {
      const error = result.error || result.status || "Unknown error";
      const hint = result.hint ? "\n\n" + result.hint : "";
      const fullMsg = `${error}${hint}`;
      
      setTelegramStatus("err", "failed");
      const resultBox = byId("telegram-test-result");
      if(resultBox){ resultBox.hidden=false; resultBox.className="settings-result err"; resultBox.textContent=fullMsg; }
      showToast("Connection test failed");
    }
  } catch(err){
    setTelegramStatus("err", "test failed");
    const resultBox = byId("telegram-test-result");
    if(resultBox){ resultBox.hidden=false; resultBox.className="settings-result err"; resultBox.textContent=`Test failed: ${err.message}`; }
    showToast("Connection test failed");
  } finally {
    btn.disabled = false;
    btn.textContent = "🔗 Test Connection";
    btn.classList.remove("loading");
  }
}


// ---------- Settings: Futures (USDⓈ-M) ----------
function setFuturesStatus(state, label){
  const badge = byId("futures-status");
  if(!badge) return;
  badge.classList.remove("ok","warn","err");
  if(state) badge.classList.add(state);
  badge.textContent = label;
}
function renderFuturesResult(payload, ok){
  const box = byId("futures-result");
  if(!box) return;
  box.hidden = false;
  box.classList.remove("ok","err");
  box.classList.add(ok ? "ok" : "err");
  box.textContent = typeof payload === "string" ? payload : JSON.stringify(payload, null, 2);
}
function renderFuturesSummary(data){
  setText("futures-cur-enabled", data.enabled ? "Yes" : "No");
  setText("futures-cur-network", data.network || "-");
  setText("futures-cur-mode", data.position_mode || "-");
  setText("futures-cur-margin", data.margin_type || "-");
  setText("futures-cur-leverage", String(data.default_leverage ?? "-"));
  setText("futures-cur-multi", data.multi_assets_margin ? "Yes" : "No");
  setText("futures-cur-symbols", (data.symbols || []).map(s => `${s.symbol}×${s.leverage}`).join(", ") || "none");
  setText("futures-cur-creds", data.credentials_configured ? "configured" : "missing");
  const en = byId("futures-enabled"); if(en) en.checked = !!data.enabled;
  const net = byId("futures-network"); if(net && data.network) net.value = data.network;
  const pm = byId("futures-position-mode"); if(pm && data.position_mode) pm.value = data.position_mode;
  const mt = byId("futures-margin-type"); if(mt && data.margin_type) mt.value = data.margin_type;
  const dl = byId("futures-default-leverage"); if(dl && data.default_leverage) dl.value = data.default_leverage;
  const ma = byId("futures-multi-assets"); if(ma) ma.checked = !!data.multi_assets_margin;
  const syms = byId("futures-symbols");
  if(syms) syms.value = (data.symbols || []).map(s => `${s.symbol}:${s.leverage}`).join("\n");
  setFuturesStatus(data.enabled ? "ok" : "warn", data.enabled ? "enabled" : "disabled");
}
function parseSymbolsTextarea(text){
  const out = {};
  (text || "").split(/[\n,]/).forEach(line => {
    const trimmed = line.trim();
    if(!trimmed) return;
    const [symbol, leverage] = trimmed.split(":").map(s => s.trim());
    if(!symbol || !leverage) return;
    const lev = parseInt(leverage, 10);
    if(!Number.isFinite(lev) || lev < 1 || lev > 125) return;
    out[symbol.toUpperCase()] = { leverage: lev };
  });
  return out;
}
async function loadFuturesSettings(){
  try {
    const data = await apiFetch("/api/settings/futures");
    renderFuturesSummary(data);
  } catch(err){
    setFuturesStatus("err", "load failed");
    renderFuturesResult(err.message, false);
  }
}
async function submitFuturesSettings(event){
  event.preventDefault();
  const payload = {
    enabled: !!byId("futures-enabled")?.checked,
    network: byId("futures-network")?.value || "testnet",
    position_mode: byId("futures-position-mode")?.value || "one_way",
    margin_type: byId("futures-margin-type")?.value || "ISOLATED",
    default_leverage: parseInt(byId("futures-default-leverage")?.value || "3", 10),
    multi_assets_margin: !!byId("futures-multi-assets")?.checked,
    symbols: parseSymbolsTextarea(byId("futures-symbols")?.value),
  };
  setFuturesStatus("warn", "saving...");
  try {
    const data = await apiFetch("/api/settings/futures", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    renderFuturesSummary(data);
    renderFuturesResult("Futures config saved. Run Bootstrap to apply on Binance.", true);
    showToast("Futures config saved");
  } catch(err){
    setFuturesStatus("err", "save failed");
    renderFuturesResult(err.message, false);
  }
  return false;
}
async function triggerFuturesBootstrap(){
  setFuturesStatus("warn", "bootstrapping...");
  try {
    const data = await apiFetch("/api/settings/futures/bootstrap", { method: "POST", body: "{}" });
    const ok = !!data.ok;
    setFuturesStatus(ok ? "ok" : "err", ok ? "bootstrap ok" : "bootstrap errors");
    renderFuturesResult(data, ok);
  } catch(err){
    setFuturesStatus("err", "bootstrap failed");
    renderFuturesResult(err.message, false);
  }
}
async function loadFuturesAccount(){
  setFuturesStatus("warn", "fetching account...");
  try {
    const data = await apiFetch("/api/futures/account");
    setFuturesStatus("ok", "account ok");
    renderFuturesResult(data, true);
  } catch(err){
    setFuturesStatus("err", "account failed");
    renderFuturesResult(err.message, false);
  }
}

let agentPanelsLoading = false;

async function loadAgentPanels(){
  if(agentPanelsLoading) return;
  agentPanelsLoading = true;
  try {
    renderAgentSnapshot(await getJson("/api/agent/snapshot?limit=20"));
  } catch (err) {
    console.warn("agent panels failed", err);
  } finally {
    agentPanelsLoading = false;
  }
}

function renderAgentSnapshot(snapshot){
  if(!snapshot || typeof snapshot !== "object") return;
  const snapshotPipeline = snapshot.pipeline || null;
  const snapshotTs = Date.parse(snapshotPipeline?.generated_at || "");
  const liveTs = Date.parse(state.lastAgentPipeline?.generated_at || "");
  const pipeline = Number.isFinite(liveTs) && (!Number.isFinite(snapshotTs) || liveTs > snapshotTs)
    ? state.lastAgentPipeline
    : snapshotPipeline;
  const learning = snapshot.learning || null;
  const observations = snapshot.observations || null;
  const llm = snapshot.llm || null;
  const llmInsights = snapshot.llm_insights || null;
  renderAgentSquad(pipeline, learning, observations, snapshot, llm);
  renderAgentPipeline(pipeline, snapshot);
  renderAgentLearning(learning);
  renderAgentLLMInsights(llmInsights, llm);
  renderAgentObservations(observations);
}

function formatAgentTime(value, includeDate=false){
  const date = new Date(value || "");
  if(Number.isNaN(date.getTime())) return "-";
  const options = includeDate
    ? {day:"2-digit",month:"short",hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:false}
    : {hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:false};
  return new Intl.DateTimeFormat(undefined, options).format(date);
}

function setAgentState(agent, mode, statusLabel){
  const card = document.querySelector(`.agent-avatar[data-agent="${agent}"]`);
  if(!card) return;
  card.classList.remove("is-active","is-alert","is-idle");
  if(mode && mode !== "idle") card.classList.add(`is-${mode}`);
  else card.classList.add("is-idle");
  const s = card.querySelector(".agent-status");
  if(s && statusLabel) s.textContent = statusLabel;
}

function renderAgentSquad(pipeline, learning, obs, snapshot={}, llm=null){
  const status = byId("agent-squad-status");
  const caption = byId("agent-squad-caption");
  if(!status || !caption) return;

  const enabled = !!(pipeline && pipeline.available !== false);
  const entries = list(pipeline?.entries);
  const monitor = list(pipeline?.monitor);
  const executing = !!pipeline?.execute_decisions;
  const observations = list(obs?.observations);
  const trades = Number(learning?.total_trades || 0);
  const generated = formatAgentTime(pipeline?.generated_at);
  const syncStatus = String(snapshot?.sync_status || "offline");
  const age = snapshot?.age_seconds == null ? null : Number(snapshot.age_seconds);

  if(!enabled){
    status.textContent = "pipeline offline";
    status.className = "pill";
    setAgentState("chart","idle","standby");
    setAgentState("learning","idle","standby");
    setAgentState("decision","idle","standby");
    setAgentState("executor","idle","standby");
    caption.textContent = "// Agent pipeline belum aktif. Aktifkan agent_pipeline.enabled=true di configs/realtime.json lalu restart run_realtime.";
    return;
  }

  status.textContent = syncStatus === "online" ? "all agents synced" : `agents ${syncStatus}`;
  status.className = "pill " + (syncStatus === "online" ? "success" : "warning");

  // Availability and work output are different states: every configured agent
  // remains online even when the current scan has no eligible candidate.
  const llmModels = llm?.agent_models || {};
  const llmLabel = agent => llmModels?.[agent] ? ` · LLM ${llmModels[agent]}` : "";
  setAgentState("chart", "active", (observations.length ? `online · ${observations.length} reads` : "online · scanning") + llmLabel("chart"));
  setAgentState("learning", "active", (trades > 0 ? `online · ${trades} trades` : "online · collecting") + llmLabel("learning"));

  // Decision Agent: aktif kalau ada decision di entries/monitor.
  const decisionCount =
    entries.filter(e => e?.result?.decision).length +
    monitor.filter(m => m?.result?.decision).length;
  const hasExit = monitor.some(m => (m?.result?.decision?.action || "") === "EXIT");
  setAgentState("decision", hasExit ? "alert" : "active", (hasExit ? "exit signal" : (decisionCount > 0 ? `online · ${decisionCount} decisions` : "online · watching")) + llmLabel("decision"));

  const executorMode = String(pipeline?.executor_mode || (executing ? "dry_run" : "advisory"));
  setAgentState("executor", "active", (executing ? `online · ${executorMode.replace("_", " ")}` : "online · gated") + llmLabel("executor"));

  const bits = [];
  bits.push(`entries=${entries.length}`);
  bits.push(`monitor=${monitor.length}`);
  bits.push(`observations=${observations.length}`);
  bits.push(`trades=${trades}`);
  if(generated !== "-") bits.push(`cycle=${generated}`);
  if(Number.isFinite(age)) bits.push(`sync_age=${Math.round(age)}s`);
  bits.push(`executor=${executorMode}`);
  if(llm?.api_key_configured) bits.push(`llm=${Object.entries(llmModels).filter(([,m])=>m).map(([a,m])=>`${a}:${m}`).join(",")||"none"}`);
  caption.textContent = "// " + bits.join("  ·  ") + (executorMode === "live" ? "  ·  ⚠ live execution" : "  ·  live order gate remains locked");
}

function kpiCard(label, value){
  return `<article class="kpi-card"><span>${esc(label)}</span><strong>${esc(String(value))}</strong></article>`;
}

const AGENT_METRIC_ICONS = {
  entries: '<path d="M12 3v18M3 12h18"/>',
  monitored: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  cycle: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  executor: '<path d="M8 5l8 7-8 7V5z"/>',
  trades: '<path d="M4 16l5-5 4 3 7-8"/><path d="M15 6h5v5"/>',
  winrate: '<circle cx="12" cy="12" r="9"/><path d="M8 12l3 3 5-6"/>',
  factor: '<path d="M5 19V9M12 19V5M19 19v-7"/>',
  confluence: '<path d="M12 3l3 6 6 .9-4.5 4.4 1.1 6.2L12 17.6l-5.6 2.9 1.1-6.2L3 9.9 9 9z"/>',
};

function agentMetricCard(label, value, icon, tone="green"){
  const glyph = AGENT_METRIC_ICONS[icon] || AGENT_METRIC_ICONS.factor;
  return `<article class="agent-metric-card tone-${esc(tone)}">
    <span class="agent-metric-icon"><svg viewBox="0 0 24 24" aria-hidden="true">${glyph}</svg></span>
    <div class="agent-metric-copy"><small>${esc(label)}</small><strong>${esc(String(value))}</strong></div>
  </article>`;
}

function renderAgentPipeline(payload, snapshot={}){
  const status = byId("agent-pipeline-status");
  const summary = byId("agent-pipeline-summary");
  const entries = byId("agent-pipeline-entries");
  const monitor = byId("agent-pipeline-monitor");
  if (!status || !summary || !entries || !monitor) return;

  if (!payload || payload.available === false) {
    status.textContent = "not running";
    status.className = "pill";
    summary.innerHTML = emptyState("Pipeline belum aktif", "Aktifkan agent_pipeline di configs/realtime.json.");
    entries.innerHTML = "";
    monitor.innerHTML = "";
    return;
  }

  const syncStatus = String(snapshot?.sync_status || "online");
  status.textContent = payload.processing ? "processing candidates" : (syncStatus === "online" ? "realtime synced" : syncStatus);
  status.className = "pill " + (syncStatus === "online" ? "success" : "warning");
  const livePositions = liveExchangePositions();
  const monitoredCount = new Set([
    ...list(payload.monitor).map(item=>monitorSymbolKey(item?.symbol)),
    ...livePositions.map(item=>monitorSymbolKey(item?.symbol)),
  ].filter(Boolean)).size;
  summary.innerHTML = [
    agentMetricCard("Entries", (payload.entries || []).length, "entries", "green"),
    agentMetricCard("Monitored", monitoredCount, "monitored", "green"),
    agentMetricCard("Last cycle", formatAgentTime(payload.generated_at, true), "cycle", "blue"),
    agentMetricCard("Executor", payload.execute_decisions ? String(payload.executor_mode || "dry_run").replace("_", " ") : "gated", "executor", "amber"),
  ].join("");

  entries.innerHTML = renderAgentEntries(pickEntryCandidates(payload));
  // Posisi exchange live harus langsung terlihat; hasil Decision Agent boleh
  // menyusul setelah cycle. Gabungkan berdasarkan symbol agar tidak duplikat.
  monitor.innerHTML = renderAgentMonitor(payload.monitor || [], livePositions);
}

// Opsi 1 guard + merge: snapshot periodik (5s, dari logs/agent_pipeline.json) tidak
// boleh menimpa Entry Candidates realtime yang lebih baru dari `generated_at` siklus file.
// Saat live lebih baru, gabungkan: baris terevaluasi realtime diprioritaskan, sedangkan
// baris lain dari file (mis. skip / missing candles) tetap tampil. Dedup per symbol.
function pickEntryCandidates(payload){
  const fileEntries = payload.entries || [];
  const live = state.liveEntryCandidates || [];
  if (!live.length) return fileEntries;
  const genTs = Date.parse(payload.generated_at || "");
  const fileFresh = Number.isFinite(genTs) && genTs >= (state.lastEntryLiveTs || 0);
  // File snapshot mewakili siklus sama/lebih baru → sudah lengkap (termasuk skip).
  if (fileFresh) return fileEntries;
  const merged = [];
  const seen = new Set();
  const push = item => {
    const sym = String((item && item.symbol) || "").toUpperCase();
    if (!sym || seen.has(sym)) return;
    seen.add(sym);
    merged.push(item);
  };
  // Live dulu (paling baru, sudah dievaluasi), lalu sisa file (skip/rows lain).
  live.forEach(push);
  fileEntries.forEach(push);
  return merged;
}

function agentText(value){
  if(value===null||value===undefined) return "";
  if(typeof value==="string") return value;
  if(typeof value==="number"||typeof value==="boolean") return String(value);
  if(typeof value==="object"){
    return String(
      value.text || value.message || value.summary || value.human_summary || value.reason ||
      value.assessment || value.hypothesis || value.description ||
      value.title || value.note || value.explanation || value.analysis || ""
    );
  }
  return String(value);
}
function agentPrettyReason(value){
  if(value && typeof value === "object" && !Array.isArray(value)){
    const main = agentText(value);
    const rationale = agentText(value.rationale);
    return [main, rationale && rationale !== main ? rationale : ""].filter(Boolean).join(" — ");
  }
  return agentText(value).replace(/[_-]+/g," ").replace(/\s+/g," ").trim();
}
function agentJoin(values,limit=2){
  return list(values).map(agentPrettyReason).filter(Boolean).slice(0,limit).join("; ");
}
function agentClip(text, max=280){
  const value = String(text || "").replace(/\s+/g," ").trim();
  if(!value) return "";
  if(value.length <= max) return value;
  return value.slice(0, max - 1).trimEnd() + "…";
}
function llmInsightDisplay(output){
  const raw = (output && typeof output === "object") ? output : {};
  const patch = (raw.policy_patch && typeof raw.policy_patch === "object") ? raw.policy_patch : {};
  const summaryText = agentClip(
    agentText(
      raw.summary || raw.human_summary || raw.explanation || raw.reason || raw.analysis ||
      patch.human_summary || patch.summary || raw.message || raw.text
    )
  );
  let recommendations = agentJoin(raw.recommendations, 4);
  if(!recommendations && patch && typeof patch === "object"){
    const bits = [];
    const prefer = agentJoin(patch.prefer_patterns, 3);
    const avoid = agentJoin(patch.avoid_patterns, 3);
    if(prefer) bits.push(`prefer: ${prefer}`);
    if(avoid) bits.push(`avoid: ${avoid}`);
    if(patch.size_multiplier != null && patch.size_multiplier !== "") bits.push(`size×${patch.size_multiplier}`);
    if(patch.min_confluence_delta != null && patch.min_confluence_delta !== "") bits.push(`confΔ ${patch.min_confluence_delta}`);
    if(patch.max_entries_per_cycle != null && patch.max_entries_per_cycle !== "") bits.push(`max_entries ${patch.max_entries_per_cycle}`);
    if(patch.confidence != null && patch.confidence !== "") bits.push(`conf ${patch.confidence}`);
    recommendations = bits.slice(0, 4).join("; ");
  }
  const reasons = agentJoin(raw.reasons || patch.reasons, 2);
  const warnings = agentJoin(raw.warnings || patch.warnings, 2);
  const fallback = reasons || recommendations || warnings;
  return {
    summaryText: summaryText || agentClip(fallback) || "-",
    recommendations,
    warnings,
    reasons,
  };
}

function renderAgentEntries(items){
  if (!items.length) return emptyState("Belum ada kandidat entry", "Chart Agent akan mengevaluasi kandidat scanner dengan confidence >= 90.");
  const rows = items.map(item => {
    const symbol = esc(item.symbol || "-");
    const conf = fmt(Number(item.scanner_confidence ?? 0));
    const res = item.result || {};
    const processing = item.processing === true || String(item.status || "").toUpperCase() === "PROCESSING";
    const decision = res.decision || {};
    const chart = res.chart_reading || {};
    const conflictRejected = res.eligibility_reason === "scanner_chart_conflict_rejected";
    const conflict = agentPrettyReason(res.scanner_chart_conflict);
    const eligibility = agentPrettyReason(res.eligibility_reason) || "-";
    const decisionReason = agentJoin(decision.reasons, 3);
    const execution = res.execution || {};
    const executionResults = list(execution.results);
    const exchangeReject = executionResults.find(result => String(result?.status || "").toUpperCase() === "REJECTED");
    const executionFailed = !!exchangeReject || (execution && execution.success === false && executionResults.length > 0);
    const executionReason = exchangeReject ? agentPrettyReason(exchangeReject.reason) : "";
    const riskReason = res.risk_approval?.approved === false
      ? agentPrettyReason(res.risk_approval.reason || list(res.risk_approval.hard_rejections)[0])
      : "";
    const conflictReason = conflictRejected
      ? `Rejected: scanner and chart directions conflict${conflict ? ` (${conflict})` : ""}`
      : "";
    const reason = esc(processing ? "Scanner passed · Chart/Decision Agent processing" : (executionReason || riskReason || decisionReason || conflictReason || eligibility));
    const rawAction = processing ? "Processing" : (executionFailed ? "Rejected" : (decision.action || (conflictRejected ? "Rejected" : (res.eligible ? "-" : "SKIP"))));
    const action = esc(String(rawAction).toUpperCase() === "ENTRY" ? "Entry" : rawAction);
    const bias = esc(decision.regime || chart.regime || "-");
    const scoreValue = decision.confidence_score ?? chart.confluence_score;
    const score = scoreValue === null || scoreValue === undefined ? "-" : fmt(Number(scoreValue));
    return `<tr><td data-label="Symbol">${symbol}</td><td data-label="Scanner conf">${conf}</td><td data-label="Decision">${badge(action)}</td><td data-label="Score">${score}</td><td data-label="Regime">${bias}</td><td data-label="Reason"><small>${reason}</small></td></tr>`;
  }).join("");
  return `<table class="agent-table agent-entry-table"><thead><tr><th>Symbol</th><th>Scanner Conf</th><th>Decision</th><th>Score</th><th>Regime</th><th>Reason</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function liveExchangePositions(){
  const multi=state.lastPayload?.multiPortfolio;
  return String(state.executionMode||"paper").toLowerCase() !== "paper" ? list(multi?.positions) : [];
}
function monitorSymbolKey(symbol){ return String(symbol||"").toUpperCase().replace(/[^A-Z0-9]/g,""); }
function renderAgentMonitor(items,livePositions=liveExchangePositions()){
  const merged=[];
  const bySymbol=new Map();
  list(items).forEach(item=>{ const key=monitorSymbolKey(item?.symbol); if(key){ bySymbol.set(key,item); merged.push(item); } });
  list(livePositions).forEach(position=>{ const key=monitorSymbolKey(position?.symbol); if(key&&!bySymbol.has(key)) merged.push({symbol:position.symbol,live_position:true,position}); });
  if (!merged.length) return emptyState("Tidak ada posisi dipantau", "Posisi live exchange akan muncul langsung, tanpa menunggu cycle agent.");
  const rows = merged.map(item => {
    const symbol = esc(item.symbol || "-");
    const res = item.result || {};
    const decision = res.decision || {};
    const action = esc(decision.action || (item.live_position ? "OPEN" : "-"));
    const reasons = agentJoin(decision.reasons, 2);
    return `<tr><td data-label="Symbol">${symbol}</td><td data-label="Decision">${badge(action)}</td><td data-label="Reasons"><small>${esc(reasons || (item.live_position ? "Live Bitunix position · awaiting Decision Agent review" : "-"))}</small></td></tr>`;
  }).join("");
  return `<table class="agent-table agent-monitor-table"><thead><tr><th>Symbol</th><th>Decision</th><th>Reasons</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function renderAgentLearning(payload){
  const status = byId("agent-learning-status");
  const summary = byId("agent-learning-summary");
  const detail = byId("agent-learning-detail");
  if (!status || !summary || !detail) return;

  if (!payload || payload.available === false) {
    status.textContent = "no data";
    status.className = "pill";
    summary.innerHTML = emptyState("Belum ada trade history", "Learning Agent akan menghasilkan insight setelah trade recorder menulis TradeRecord.");
    detail.innerHTML = "";
    return;
  }

  status.textContent = `${payload.total_trades || 0} trades`;
  status.className = "pill success";
  summary.innerHTML = [
    agentMetricCard("Trades", payload.total_trades || 0, "trades", "green"),
    agentMetricCard("Winrate", `${fmt(Number(payload.overall_winrate ?? 0))}%`, "winrate", "green"),
    agentMetricCard("Profit Factor", fmt(Number(payload.overall_profit_factor ?? 0)), "factor", "blue"),
    agentMetricCard("Min Confluence", fmt(Number(payload.min_confluence_recommended ?? 0)), "confluence", "amber"),
  ].join("");

  const hot = list(payload.hot_patterns).slice(0, 5).join(", ") || "-";
  const cold = list(payload.cold_patterns).slice(0, 5).join(", ") || "-";
  detail.innerHTML = `
    <div>Best regime</div><strong>${esc(payload.best_regime || "-")}</strong>
    <div>Worst regime</div><strong>${esc(payload.worst_regime || "-")}</strong>
    <div>Hot patterns</div><strong>${esc(hot)}</strong>
    <div>Cold patterns</div><strong>${esc(cold)}</strong>
    <div>Avg confluence (winners)</div><strong>${fmt(Number(payload.avg_confluence_winners ?? 0))}</strong>
    <div>Avg confluence (losers)</div><strong>${fmt(Number(payload.avg_confluence_losers ?? 0))}</strong>
    <div>LLM</div><strong>${esc(payload.meta?.llm?.enabled ? (payload.meta.llm.model || "enabled") : "none")}</strong>
  `;
}

function renderAgentLLMInsights(payload, llm){
  const status = byId("agent-llm-status");
  const summary = byId("agent-llm-summary");
  const listEl = byId("agent-llm-list");
  if(!status || !summary || !listEl) return;

  const configured = !!llm?.api_key_configured;
  const insights = list(payload?.insights);
  if(!configured){
    status.textContent = "optional";
    status.className = "pill";
    summary.innerHTML = emptyState("LLM belum dikonfigurasi", "Isi Base URL + API Key di Settings, lalu Fetch Models.");
    listEl.innerHTML = "";
    return;
  }

  status.textContent = `${insights.length} / ${payload?.total_stored || 0}`;
  status.className = "pill info";
  summary.innerHTML = [
    agentMetricCard("Models", Object.values(llm?.agent_models || {}).filter(Boolean).length, "factor", "blue"),
    agentMetricCard("Insights", payload?.total_stored || 0, "trades", "green"),
    agentMetricCard("Latest", insights.length ? formatAgentTime(insights[insights.length-1]?.timestamp, true) : "-", "cycle", "amber"),
  ].join("");

  if(!insights.length){
    listEl.innerHTML = emptyState("Belum ada insight LLM", "Learning Agent akan menulis insight ketika model learning dipilih.");
    return;
  }

  const rows = insights.slice().reverse().map(item=>{
    const display = llmInsightDisplay(item.output || item.result || {});
    const summaryText = display.summaryText;
    const recommendations = display.recommendations;
    const warnings = display.warnings;
    const reasons = display.reasons && display.reasons !== summaryText ? display.reasons : "";
    return `<tr>
      <td data-label="Time">${esc(formatAgentTime(item.timestamp,true))}</td>
      <td data-label="Agent">${esc(item.agent||"-")}</td>
      <td data-label="Model">${esc(item.model||"-")}</td>
      <td data-label="Output"><strong>${esc(summaryText)}</strong>${reasons?`<div><small>Reasons: ${esc(agentClip(reasons,160))}</small></div>`:""}${warnings?`<div><small>Warnings: ${esc(warnings)}</small></div>`:""}${recommendations?`<div><small>Recommendations: ${esc(agentClip(recommendations,180))}</small></div>`:""}</td>
    </tr>`;
  }).join("");
  listEl.innerHTML = `<table class="agent-table"><thead><tr><th>Time</th><th>Agent</th><th>Model</th><th>Output</th></tr></thead><tbody>${rows}</tbody></table>`;
}


function renderAgentObservations(payload){
  const status = byId("agent-observations-status");
  const listEl = byId("agent-observations-list");
  if (!status || !listEl) return;

  if (!payload || payload.available === false) {
    status.textContent = "no data";
    status.className = "pill";
    listEl.innerHTML = emptyState("Belum ada observation", "Chart Agent akan menulis observation setiap kali membaca chart.");
    return;
  }

  const observations = list(payload.observations);
  status.textContent = `${payload.count || 0} / ${payload.total_stored || 0}`;
  status.className = "pill info";

  if (!observations.length) {
    listEl.innerHTML = emptyState("Belum ada observation", "Chart Agent akan menulis observation setiap kali membaca chart.");
    return;
  }

  const rows = observations.slice().reverse().map(obs => {
    const reading = obs.chart_reading || {};
    const decision = obs.decision || {};
    const symbol = esc(obs.symbol || "-");
    const stage = esc(obs.stage || "-");
    const bias = esc(reading.bias || "-");
    const confluence = fmt(Number(reading.confluence_score ?? 0));
    const action = esc(decision.action || "-");
    const ts = formatAgentTime(obs.timestamp, true);
    return `<tr><td data-label="Time"><time datetime="${esc(obs.timestamp || "")}">${esc(ts)}</time></td><td data-label="Symbol">${symbol}</td><td data-label="Stage">${stage}</td><td data-label="Bias">${badge(bias)}</td><td data-label="Confluence">${confluence}</td><td data-label="Decision">${badge(action)}</td></tr>`;
  }).join("");
  listEl.innerHTML = `<table class="agent-table agent-observations-table"><thead><tr><th>Time</th><th>Symbol</th><th>Stage</th><th>Bias</th><th>Confluence</th><th>Decision</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function syncModeKpis(payload){ const mode=String(state.executionMode||payload?.execution_mode||"paper").toLowerCase(); if(mode==="paper") return; const multi=payload?.multiPortfolio??payload?.multi_portfolio??{}; const balance=multi.account_balance_usdt??multi.available_balance_usdt; const equity=multi.equity_usdt??balance; if(Number.isFinite(Number(balance))) animateMetric("metric-balance",Number(balance)); if(Number.isFinite(Number(equity))) animateMetric("metric-equity",Number(equity)); animateMetric("metric-positions",Number(multi.open_positions_count??list(multi.positions).length)); }
function refreshActiveOrderStops(){ const p=state.lastPayload||{}; const mode=String(state.executionMode||"paper").toLowerCase(); const positions=mode==="paper"?list(p.paper?.open_positions):list(p.multiPortfolio?.positions); positions.forEach(patchActiveOrderStops); syncModeKpis(p); }
initUi(); setDashboardActivity(!document.hidden); setInterval(refreshActiveOrderStops,1000); loadLLMSettings(); loadExchangeSettings(); loadPortfolioSettings(); loadExecutionSettings(); loadFuturesSettings(); loadTelegramSettings(); loadAgentPanels().catch(console.warn);
// Satu snapshot akun exchange menjadi sumber semua menu. TTL backend 5 detik
// menjaga request tetap ringan, sedangkan guard loadAll mencegah poll tumpang tindih.
document.addEventListener("visibilitychange",()=>setDashboardActivity(!document.hidden));
window.addEventListener("pagehide",()=>setDashboardActivity(false),{once:true});
