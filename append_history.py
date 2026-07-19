#!/usr/bin/env python3
"""append_history — append one compact record per verifier run to history.jsonl, so the dashboard can show
solvency as a LIVE property over time (not a single snapshot). Append-only; dedups by flare_block so a
re-run at the same block doesn't double-count. Reads reserves.json (from fassets_verify.py). No network."""
import json, os, datetime

R = json.load(open("reserves.json"))
a = R["assets"][0]
pin = R["pinned"]
supply = int(a["totalSupply"]); backing = int(a["realBacking"]); surplus = int(a["surplus"])
rec = {
    "t": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "flare_block": pin["flare_block"], "xrpl_ledger": pin["xrpl_ledger"],
    "verdict": a["verdict"], "backing_verdict": a["backingVerdict"], "collateral_verdict": a["collateralVerdict"],
    "floor_read_ok": a.get("floorReadOk"),
    "supply_uba": str(supply), "backing_uba": str(backing), "surplus_uba": str(surplus),
    "surplus_pct": round(surplus / supply * 100, 4) if supply else None,
    "agents": len(a["agents"]), "flags": len(a["collateralFlags"]),
}

HIST = "history.jsonl"
last = None
if os.path.exists(HIST):
    with open(HIST) as f:
        lines = [l for l in f if l.strip()]
    if lines:
        try: last = json.loads(lines[-1])
        except Exception: last = None

# dedup only when the FULL pin (both chains) AND the verdict are unchanged — a same-block re-run whose
# XRPL-side backing or verdict moved must still be recorded (LEG 2 is pinned to the XRPL ledger, not the block).
if (last and last.get("flare_block") == rec["flare_block"]
        and last.get("xrpl_ledger") == rec["xrpl_ledger"]
        and last.get("verdict") == rec["verdict"]):
    print(f"history: skip (same pin {rec['flare_block']}/{rec['xrpl_ledger']} + verdict {rec['verdict']} as last)")
else:
    with open(HIST, "a") as f:
        f.write(json.dumps(rec) + "\n")
    print(f"history: appended {rec['t']} verdict={rec['verdict']} surplus%={rec['surplus_pct']} (block {rec['flare_block']})")
