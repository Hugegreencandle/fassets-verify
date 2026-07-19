"""fassets_lib — shared verdict logic, so the verifier and the negative-test harness use ONE definition
(they can never diverge). Import-safe: no network, no side effects."""

def combine_verdict(cannot_verify, backing, supply, coll_flag_count):
    """Two-leg solvency verdict. SOLVENT requires BOTH legs — real XRPL backing >= supply (LEG 2) AND no
    agent flagged by the protocol's liquidation state machine (LEG 1). Fail-closed to CANNOT_VERIFY."""
    backing_v = "CANNOT_VERIFY" if cannot_verify else ("PROVEN" if backing >= supply else "BACKING_SHORTFALL")
    coll_v = "OVER_COLLATERALIZED" if coll_flag_count == 0 else "UNDER_COLLATERALIZED"
    if backing_v == "CANNOT_VERIFY": overall = "CANNOT_VERIFY"
    elif backing_v == "PROVEN" and coll_v == "OVER_COLLATERALIZED": overall = "SOLVENT"
    elif backing_v != "PROVEN": overall = "BACKING_SHORTFALL"   # backing shortfall dominates
    else: overall = "UNDER_COLLATERALIZED"
    return backing_v, coll_v, overall
