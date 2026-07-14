#!/usr/bin/env python3
import sys

file = "/opt/crypto-quant-bot/app/dashboard/static/dashboard.js"

with open(file, "r", encoding="utf-8") as f:
    content = f.read()

# Pattern exact dari output (ada spasi setelah kurung kurawal)
old = 'if(state.currentView==="orders"){ state.lastPayload=normalizePayload(data.payload); } else { clearTimeout(snapshotTimer); snapshotTimer=setTimeout(()=>render(data.payload),800); }'
new = 'clearTimeout(snapshotTimer); snapshotTimer=setTimeout(()=>render(data.payload),state.currentView==="orders"?100:800);'

if old in content:
    content = content.replace(old, new)
    with open(file, "w", encoding="utf-8") as f:
        f.write(content)
    print("✅ FIXED: Active Orders sekarang update realtime (100ms delay)")
    print("   Overview tetap 800ms debounce")
    print("   Reload dashboard untuk apply fix")
    sys.exit(0)
else:
    print("❌ Pattern masih tidak match")
    idx = content.find('state.currentView==="orders"')
    if idx > 0:
        print(f"\nSnippet di index {idx}:")
        print(repr(content[idx:idx+300]))
    sys.exit(1)
