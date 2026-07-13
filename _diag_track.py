import json

with open("logs/signals.jsonl", "rb") as f:
    lines = f.readlines()[-4:]

# Current open positions from paper state
ps = json.load(open("logs/paper_state.json"))
ops = ps.get("open_positions", {})
open_syms = list(ops.keys()) if isinstance(ops, dict) else [p.get("symbol") for p in ops]
print("OPEN POSITIONS:", open_syms)
print("paper updated_at:", ps.get("updated_at"))
print()

for line in lines:
    d = json.loads(line)
    ts = d.get("timestamp")
    tr = {t["symbol"]: t.get("entry") for t in d.get("tracked_signals", [])}
    top = {s["symbol"]: s.get("entry") for s in d.get("signals", [])}
    row = {}
    for w in open_syms:
        if w in tr:
            row[w] = ("TRACKED", tr[w])
        elif w in top:
            row[w] = ("TOP", top[w])
        else:
            row[w] = ("MISSING", None)
    print(ts, row)

