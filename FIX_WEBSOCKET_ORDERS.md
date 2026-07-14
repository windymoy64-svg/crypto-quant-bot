// Fix: WebSocket snapshot harus render di semua view, termasuk Orders
// Problem: di menu Orders, Active Orders tidak update realtime karena tidak trigger render()
// Solution: hapus conditional, selalu render dengan debounce adaptif

// SEBELUM (BROKEN):
// if(data.type==="snapshot"){
//   if(state.currentView==="orders"){
//     state.lastPayload=normalizePayload(data.payload);  // <-- TIDAK RENDER!
//   } else {
//     clearTimeout(snapshotTimer);
//     snapshotTimer=setTimeout(()=>render(data.payload),800);
//   }
//   renderEvents();
// }

// SESUDAH (FIXED):
// if(data.type==="snapshot"){
//   clearTimeout(snapshotTimer);
//   const delay = state.currentView==="orders" ? 100 : 800;  // Lebih cepat di Orders
//   snapshotTimer=setTimeout(()=>render(data.payload), delay);
//   renderEvents();
// }

// Apply fix ke dashboard.js line 81, di dalam ws.onmessage handler
// Ganti blok if currentView orders dengan render langsung
