#!/usr/bin/env python3
"""negative_test — prove the FXRP verifier has TEETH: it must FLAG the bad cases, not only green-light.
Three parts, all against the SAME pure logic the live verifier calls (fassets_lib), so the test and the
tool cannot diverge:
  (1) unit cases over combine_verdict (the two-leg verdict);
  (2) DERIVATION cases — underlying_backing (with a mocked xrpl_fn) + evaluate_agent — so a regression in
      the accounting/collateral logic is caught, not just the final combinator (this is the layer a pure
      combine_verdict test used to miss);
  (3) live-mutation of the real reserves.json — mutate the derived figures and confirm the verdict flips.
Exit 1 on any mismatch."""
import json, sys
from fassets_lib import combine_verdict, underlying_backing, evaluate_agent, mark_to_market

allok = True
def check(name, got, want):
    global allok
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL':4} {name:44} => {got}" + ("" if ok else f"  (expected {want})"))
    allok &= ok
    return ok

# ---------------------------------------------------------------------------------------------------------
print("== (1) unit cases — combine_verdict ==")
# (cannot_verify, backing, supply, coll_flag_count, coll_unverifiable_count) -> overall
UNIT = [
    ("solvent (backing==supply)",        (False, 100, 100, 0),    "SOLVENT"),
    ("solvent (surplus)",                (False, 110, 100, 0),    "SOLVENT"),
    ("backing shortfall",                (False,  99, 100, 0),    "BACKING_SHORTFALL"),
    ("under-collateralized (1 flag)",    (False, 110, 100, 1),    "UNDER_COLLATERALIZED"),
    ("both bad (backing dominates)",     (False,  99, 100, 1),    "BACKING_SHORTFALL"),
    ("cannot verify (read failed)",      (True,  110, 100, 0),    "CANNOT_VERIFY"),
    ("floor UNVERIFIABLE => cannot-verify",(False,110, 100, 0, 1),"CANNOT_VERIFY"),   # NEW fail-closed path
    ("unverifiable dominates a clean backing",(False,110,100,0,2),"CANNOT_VERIFY"),
    ("boundary: short by 1 UBA",         (False, 99999, 100000, 0),"BACKING_SHORTFALL"),
]
for name, args, want in UNIT:
    check(name, combine_verdict(*args)[2], want)

# ---------------------------------------------------------------------------------------------------------
print("\n== (2) derivation — underlying_backing (mocked XRPL) + evaluate_agent ==")
ADDR = "rAGENT"; OTHER = "rEXTERNAL"

def mock_xrpl(balance, escrows, no_account=False, no_objects=False):
    """Build a fake xrpl_fn(method, params) returning canned account_info / account_objects."""
    def fn(method, params):
        if method == "account_info":
            return {} if no_account else {"account_data": {"Balance": str(balance)}}
        if method == "account_objects":
            if no_objects: return {}
            return {"account_objects": escrows}
        return {}
    return fn

# a self-returning escrow counts as locked backing; an external-destination escrow is EXCLUDED (leaves system)
esc_self = [{"Account": ADDR, "Destination": ADDR,   "Amount": "50"}]
esc_ext  = [{"Account": ADDR, "Destination": OTHER,  "Amount": "50"}]
check("self escrow counts (dest_filter=self)",  underlying_backing(mock_xrpl(100, esc_self), ADDR, "v", dest_filter=ADDR), (100, 50, 0))
check("external escrow EXCLUDED (dest_filter=self)", underlying_backing(mock_xrpl(100, esc_ext), ADDR, "v", dest_filter=ADDR), (100, 0, 50))
check("no filter counts external as backing (old behaviour)", underlying_backing(mock_xrpl(100, esc_ext), ADDR, "v"), (100, 50, 0))
check("unreadable account -> None (fail-closed)", underlying_backing(mock_xrpl(0, [], no_account=True), ADDR, "v", dest_filter=ADDR), None)
check("unreadable objects -> None (fail-closed)", underlying_backing(mock_xrpl(100, [], no_objects=True), ADDR, "v", dest_filter=ADDR), None)

def agent(status=0, liq=0, vcr=20000, pcr=20000, token="0xTOKEN"):
    return {"status": status, "liquidationStartTimestamp": liq, "vaultCollateralRatioBIPS": vcr,
            "poolCollateralRatioBIPS": pcr, "vaultCollateralToken": token, "mintedUBA": "1"}
RV = {"0xtoken": 12000}; RP = 15000   # vault floor 120%, pool floor 150%
check("NORMAL, above both floors -> HEALTHY",   evaluate_agent(agent(), RV, RP)["collateral"], "HEALTHY")
check("NORMAL, below vault floor -> FLAGGED",   evaluate_agent(agent(vcr=11000), RV, RP)["collateral"], "FLAGGED")
check("NORMAL, below pool floor -> FLAGGED",    evaluate_agent(agent(pcr=14000), RV, RP)["collateral"], "FLAGGED")
check("LIQUIDATION status -> FLAGGED",           evaluate_agent(agent(status=2), RV, RP)["collateral"], "FLAGGED")
check("liq timestamp set -> FLAGGED",            evaluate_agent(agent(liq=1), RV, RP)["collateral"], "FLAGGED")
check("NORMAL but token not in floor map -> UNVERIFIED", evaluate_agent(agent(token="0xUNKNOWN"), RV, RP)["collateral"], "UNVERIFIED")
check("NORMAL but floor read failed (no floors) -> UNVERIFIED", evaluate_agent(agent(), {}, None)["collateral"], "UNVERIFIED")

print("\n== (2b) LEG 1.5 mark-to-market (FTSOv2 USD re-derivation, pure) ==")
# 1 XRP minted @ $1; 2 USDT vault (6dp) @ $1 => vault CR 200%; 3 FLR pool (18dp) @ $1 => pool CR 300%
mt = {"mintedUBA": str(10**6), "totalVaultCollateralWei": str(2*10**6), "totalPoolCollateralNATWei": str(3*10**18)}
r = mark_to_market(mt, xrp_usd=1.0, vault_usd=1.0, pool_usd=1.0, vault_dec=6)
check("obligation USD = minted * XRP price", r["usdObligation"], 1.0)
check("vault collateral USD", r["usdVaultCollateral"], 2.0)
check("independent vault CR %", r["indepVaultCR_pct"], 200.0)
check("independent pool CR %", r["indepPoolCR_pct"], 300.0)
# real prices scale correctly: 1 XRP @ $1.09, 2 USDT @ $0.999 => CR = 2*0.999 / 1.09 * 100
r2 = mark_to_market(mt, xrp_usd=1.09, vault_usd=0.999, pool_usd=0.0065, vault_dec=6)
check("CR uses live prices (vault)", r2["indepVaultCR_pct"], round(2*0.999/1.09*100, 2))
# zero minted => ratio undefined (no exposure), never a divide error
mt0 = {"mintedUBA": "0", "totalVaultCollateralWei": str(5*10**6), "totalPoolCollateralNATWei": "0"}
check("zero minted -> vault CR None (no divide error)", mark_to_market(mt0, 1.0, 1.0, 1.0, 6)["indepVaultCR_pct"], None)

# ---------------------------------------------------------------------------------------------------------
print("\n== (3) live-mutation of the REAL reserves.json ==")
try:
    a = json.load(open("reserves.json"))["assets"][0]
    supply = int(a["totalSupply"]); backing = int(a.get("netBacking", a["realBacking"]))
    flags = len(a["collateralFlags"]); unver = len(a.get("collateralUnverifiable", []))
    print(f"  (real FXRP: supply={supply} net_backing={backing} flagged={flags} unverifiable={unver})")
    check("real baseline matches live verdict", combine_verdict(False, backing, supply, flags, unver)[2],
          a["verdict"])
    check("inject: backing 1 UBA short",  combine_verdict(False, supply - 1, supply, flags, unver)[2], "BACKING_SHORTFALL")
    check("inject: 1 agent flagged",       combine_verdict(False, backing, supply, 1, 0)[2], "UNDER_COLLATERALIZED")
    check("inject: 1 agent unverifiable",  combine_verdict(False, backing, supply, 0, 1)[2], "CANNOT_VERIFY")
    check("inject: XRPL read failure",     combine_verdict(True, backing, supply, flags, unver)[2], "CANNOT_VERIFY")
except FileNotFoundError:
    print("  (skip live-mutation: run fassets_verify.py first to produce reserves.json)")

print("\n" + ("OK — the verifier discriminates: derivation + verdict both flag every bad case." if allok
              else "FAIL — a bad case was NOT flagged."))
sys.exit(0 if allok else 1)
