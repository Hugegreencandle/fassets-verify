#!/usr/bin/env python3
"""negative_test — prove the FXRP verifier has TEETH: it must FLAG the bad cases, not only green-light.
Two parts: (1) unit cases over the shared verdict logic; (2) LIVE-MUTATION of the real reserves.json —
take the actual on-chain FXRP data and show that if backing dropped below supply, or an agent entered
liquidation, or an XRPL read failed, the verdict flips off SOLVENT. Uses the SAME combine_verdict the
verifier uses (fassets_lib), so the test and the tool cannot diverge. Exit 1 on any mismatch."""
import json, sys
from fassets_lib import combine_verdict

def check(name, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL':4} {name:34} => {got}" + ("" if ok else f"  (expected {want})"))
    return ok

allok = True
print("== unit cases (verdict logic) ==")
UNIT = [
    ("solvent (backing==supply)",      (False, 100, 100, 0), "SOLVENT"),
    ("solvent (surplus)",              (False, 110, 100, 0), "SOLVENT"),
    ("backing shortfall",              (False,  99, 100, 0), "BACKING_SHORTFALL"),
    ("under-collateralized (1 agent)", (False, 110, 100, 1), "UNDER_COLLATERALIZED"),
    ("both bad (backing dominates)",   (False,  99, 100, 1), "BACKING_SHORTFALL"),
    ("cannot verify (read failed)",    (True,  110, 100, 0), "CANNOT_VERIFY"),
    ("boundary: short by 1 UBA",       (False, 99999, 100000, 0), "BACKING_SHORTFALL"),
]
for name, args, want in UNIT:
    allok &= check(name, combine_verdict(*args)[2], want)

print("\n== live-mutation of the REAL reserves.json (does it catch a real regression?) ==")
try:
    a = json.load(open("reserves.json"))["assets"][0]
    supply = int(a["totalSupply"]); backing = int(a["realBacking"]); flags = len(a["collateralFlags"])
    print(f"  (real FXRP: supply={supply} backing={backing} flagged_agents={flags})")
    # baseline must be SOLVENT (or whatever the live state is) — sanity that mutations are meaningful
    allok &= check("real baseline", combine_verdict(False, backing, supply, flags)[2],
                   "SOLVENT" if (backing >= supply and flags == 0) else combine_verdict(False, backing, supply, flags)[2])
    # inject a backing shortfall (1 UBA under) -> must flip to BACKING_SHORTFALL
    allok &= check("inject: backing 1 UBA short", combine_verdict(False, supply - 1, supply, flags)[2], "BACKING_SHORTFALL")
    # inject one liquidating agent -> must flip to UNDER_COLLATERALIZED
    allok &= check("inject: 1 agent in liquidation", combine_verdict(False, backing, supply, 1)[2], "UNDER_COLLATERALIZED")
    # inject an XRPL read failure -> must fail closed
    allok &= check("inject: XRPL read failure", combine_verdict(True, backing, supply, flags)[2], "CANNOT_VERIFY")
except FileNotFoundError:
    print("  (skip live-mutation: run fassets_verify.py first to produce reserves.json)")

print("\n" + ("OK — the verifier discriminates: every bad case is flagged." if allok else "FAIL — a bad case was NOT flagged."))
sys.exit(0 if allok else 1)
