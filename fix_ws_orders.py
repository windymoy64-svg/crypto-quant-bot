#!/usr/bin/env python3
"""Fix WebSocket snapshot update di menu Orders - Active Orders tidak update realtime"""

import re

file_path = "/opt/crypto-quant-bot/app/dashboard/static/dashboard.js"

with open(file_path, "r") as f:
    content = f.read()

# Pattern to find: conditional render di snapshot handler
old_pattern = r'if\(state\.currentView==="orders"\)\{state\.lastPayload=normalizePayload\(data\.payload\);\}else\{clearTimeout\(snapshotTimer\);snapshotTimer=setTimeout\(\(\)=>render\(data\.payload\),800\);\}'

# New: always render, tapi Orders dapat delay lebih cepat
new_code = 'clearTimeout(snapshotTimer);snapshotTimer=setTimeout(()=>render(data.payload),state.currentView==="orders"?100:800);'

# Replace
content_fixed = re.sub(old_pattern, new_code, content)

if content != content_fixed:
    with open(file_path, "w") as f:
        f.write(content_fixed)
    print("✅ Fixed: WebSocket snapshot sekarang render di semua view termasuk Orders")
    print("   Active Orders akan update realtime dengan delay 100ms")
    print("   Overview tetap 800ms debounce")
else:
    print("⚠️  Pattern tidak ditemukan atau sudah dipatch")
