"""fassets_lib — PURE, import-safe accounting + verdict logic (no network, no side effects at import),
so the verifier and the negative-test harness share ONE definition AND the derivation itself is unit-testable
(the network-driving script only wires these together). Fail-closed is the rule: anything we cannot verify
becomes CANNOT_VERIFY, never a false SOLVENT."""

STATUS_NAMES = {0: "NORMAL", 1: "CCB", 2: "LIQUIDATION", 3: "FULL_LIQUIDATION", 4: "DESTROYING"}


def underlying_backing(xrpl_fn, addr, lidx, dest_filter=None):
    """Real XRP at `addr` as (liquid, locked, excluded), read via the injected `xrpl_fn(method, params)`
    (injected so this is testable with a mock). Escrows CREATED by addr (`Account==addr`) count as `locked`
    backing ONLY if `dest_filter is None` OR their Destination == dest_filter; escrows paying ELSEWHERE go
    to `excluded` (that XRP leaves the system on EscrowFinish, so it does not back FXRP). Returns None if the
    account or its objects cannot be read (fail-closed -> the caller degrades to CANNOT_VERIFY).

    NOTE: `liquid` is the raw account Balance, which INCLUDES the (unspendable) base + owner reserve — a small
    bounded over-count of spendable backing, disclosed in the caveats rather than subtracted here."""
    ai = xrpl_fn("account_info", {"account": addr, "ledger_index": lidx})
    if "account_data" not in ai:
        return None
    liquid = int(ai["account_data"]["Balance"]); locked = 0; excluded = 0; marker = None
    while True:
        p = {"account": addr, "type": "escrow", "ledger_index": lidx, "limit": 400}
        if marker:
            p["marker"] = marker
        r = xrpl_fn("account_objects", p)
        if "account_objects" not in r:
            return None
        for o in r["account_objects"]:
            if o.get("Account") != addr:
                continue
            amt = int(o.get("Amount", "0"))
            if dest_filter is not None and o.get("Destination") != dest_filter:
                excluded += amt
            else:
                locked += amt
        marker = r.get("marker")
        if not marker:
            break
    return liquid, locked, excluded


def evaluate_agent(d, reqVault, reqPool):
    """PURE LEG-1 evaluation of one agent from its getAgentInfo dict `d`, against the system-required
    collateral floors (reqVault: token(lower)->min_bips ; reqPool: min_bips or None). Returns a dict of
    display fields + a `collateral` class in {HEALTHY, FLAGGED, UNVERIFIED}:
      - FLAGGED   — the protocol's own status is non-NORMAL/liquidating, OR a KNOWN floor is breached.
      - UNVERIFIED— status is fine but a REQUIRED floor is unknown (token not in the floor map, or the
                    floor read failed) so over-collateralization CANNOT be asserted. FAIL-CLOSED: never HEALTHY.
      - HEALTHY   — status NORMAL, not liquidating, and both required floors known AND satisfied.
    The caller scopes these by exposure (mintedUBA>0) when forming the system verdict."""
    st = int(d["status"]); liq = int(d["liquidationStartTimestamp"])
    vcr = int(d["vaultCollateralRatioBIPS"]); pcr = int(d["poolCollateralRatioBIPS"])
    rv = reqVault.get(str(d["vaultCollateralToken"]).lower())
    rp = reqPool
    determinable = (rv is not None and rp is not None)
    below_known_floor = (rv is not None and vcr < rv) or (rp is not None and pcr < rp)
    status_bad = (st != 0 or liq != 0)
    if status_bad or below_known_floor:
        coll = "FLAGGED"
    elif not determinable:
        coll = "UNVERIFIED"
    else:
        coll = "HEALTHY"
    return {
        "status": STATUS_NAMES.get(st, st), "liquidationStart": liq,
        "vaultCR_pct": round(vcr / 100, 2), "reqVaultCR_pct": round(rv / 100, 2) if rv else None,
        "poolCR_pct": round(pcr / 100, 2), "reqPoolCR_pct": round(rp / 100, 2) if rp else None,
        "vaultBufferPP": round((vcr - rv) / 100, 2) if rv else None,
        "poolBufferPP": round((pcr - rp) / 100, 2) if rp else None,
        "collateral": coll,
    }


def combine_verdict(cannot_verify, backing, supply, coll_flag_count, coll_unverifiable_count=0):
    """Two-leg solvency verdict. SOLVENT requires BOTH legs:
      LEG 2 — real XRPL backing >= supply (backing passed here is already NET of redeeming XRP that is
              earmarked to leave the system), AND
      LEG 1 — every EXPOSED agent is VERIFIABLY over its required floor (no flags, none unverifiable).
    Fail-closed: unreadable backing OR any exposed agent whose floor can't be verified => CANNOT_VERIFY.
    Never returns SOLVENT on an unverifiable input."""
    backing_v = "CANNOT_VERIFY" if cannot_verify else ("PROVEN" if backing >= supply else "BACKING_SHORTFALL")
    if coll_unverifiable_count > 0:
        coll_v = "CANNOT_VERIFY"          # a required floor could not be verified -> cannot assert over-collateralized
    elif coll_flag_count > 0:
        coll_v = "UNDER_COLLATERALIZED"
    else:
        coll_v = "OVER_COLLATERALIZED"
    if backing_v == "CANNOT_VERIFY" or coll_v == "CANNOT_VERIFY":
        overall = "CANNOT_VERIFY"
    elif backing_v == "PROVEN" and coll_v == "OVER_COLLATERALIZED":
        overall = "SOLVENT"
    elif backing_v != "PROVEN":
        overall = "BACKING_SHORTFALL"     # backing shortfall dominates a collateral flag
    else:
        overall = "UNDER_COLLATERALIZED"
    return backing_v, coll_v, overall
