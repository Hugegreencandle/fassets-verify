#!/usr/bin/env python3
"""fassets-verify — independent Proof-of-Reserves for the Flare FAssets SYSTEM.
Auto-discovers EVERY live FAsset via AssetManagerController.getAssetManagers() (FXRP today; FBTC/FDOGE automatically
when they launch), and for each re-derives 'every unit is backed by real underlying' from raw Flare + XRPL data,
trusting no indexer. Backing = Σ agents' LIVE underlying balance + Core Vault (liquid Balance + on-ledger Escrow objects).
The Core Vault holds ~140M XRP in XRPL Escrow that a naive Balance check MISSES; we read the escrows. Fail-closed."""
import json, sys, urllib.request
from web3 import Web3
FLARE="https://flare-api.flare.network/ext/C/rpc"; XRPL="https://xrplcluster.com/"
CTRL="0x097B93eEBe9b76f2611e1E7D9665a9d7Ff5280B3"
w3=Web3(Web3.HTTPProvider(FLARE))
def xrpl(m,p):
    r=urllib.request.Request(XRPL, json.dumps({"method":m,"params":[p]}).encode(), {"Content-Type":"application/json"})
    return json.load(urllib.request.urlopen(r,timeout=30))["result"]
def underlying_backing(addr,lidx):
    ai=xrpl("account_info",{"account":addr,"ledger_index":lidx})
    if "account_data" not in ai: return None
    liquid=int(ai["account_data"]["Balance"]); locked=0; marker=None
    while True:
        p={"account":addr,"type":"escrow","ledger_index":lidx,"limit":400}
        if marker:p["marker"]=marker
        r=xrpl("account_objects",p)
        if "account_objects" not in r: return None
        locked+=sum(int(o.get("Amount","0")) for o in r["account_objects"] if o.get("Account")==addr)
        marker=r.get("marker")
        if not marker: break
    return liquid,locked
gai=json.load(open("agentinfo_abi.json")); comps=[c['name'] for c in gai[0]["outputs"][0]["components"]]
AMABI=gai+[
 {"inputs":[],"name":"fAsset","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"},
 {"inputs":[{"type":"uint256"},{"type":"uint256"}],"name":"getAllAgents","outputs":[{"type":"address[]"},{"type":"uint256"}],"stateMutability":"view","type":"function"},
 {"inputs":[],"name":"getCoreVaultManager","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"},
 # CollateralType[] — the SYSTEM-REQUIRED minimum collateral ratios (the liquidation floors). collateralClass
 # 1=POOL(NAT/FLR), 2=VAULT. Use minCollateralRatioBIPS (documented floor: pool 150% / vault 120%); NOT
 # safetyMinCollateralRatioBIPS (reads ~3 BIPS = effectively unset). Lets LEG 1 report "CR vs REQUIRED".
 {"inputs":[],"name":"getCollateralTypes","outputs":[{"type":"tuple[]","components":[
   {"type":"uint8","name":"collateralClass"},{"type":"address","name":"token"},{"type":"uint256","name":"decimals"},
   {"type":"uint256","name":"validUntil"},{"type":"bool","name":"directPricePair"},{"type":"string","name":"assetFtsoSymbol"},
   {"type":"string","name":"tokenFtsoSymbol"},{"type":"uint256","name":"minCollateralRatioBIPS"},
   {"type":"uint256","name":"ccbMinCollateralRatioBIPS"},{"type":"uint256","name":"safetyMinCollateralRatioBIPS"}]}],
  "stateMutability":"view","type":"function"}]
ERC=[{"inputs":[],"name":"symbol","outputs":[{"type":"string"}],"stateMutability":"view","type":"function"},{"inputs":[],"name":"totalSupply","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},{"inputs":[],"name":"decimals","outputs":[{"type":"uint8"}],"stateMutability":"view","type":"function"}]
CVABI=[{"inputs":[],"name":"coreVaultAddress","outputs":[{"type":"string"}],"stateMutability":"view","type":"function"}]
# FAssets AgentStatus enum — the protocol's OWN liquidation state machine (authoritative, no threshold guessing).
STATUS_NAMES={0:"NORMAL",1:"CCB",2:"LIQUIDATION",3:"FULL_LIQUIDATION",4:"DESTROYING"}
BIPS=10000  # collateral ratios are in BIPS (10000 = 100%)
from fassets_lib import combine_verdict  # shared verdict logic (single source of truth)
blk=w3.eth.block_number; lidx=xrpl("ledger",{"ledger_index":"validated"})["ledger_index"]
mgrs=w3.eth.contract(address=Web3.to_checksum_address(CTRL),abi=[{"inputs":[],"name":"getAssetManagers","outputs":[{"type":"address[]"}],"stateMutability":"view","type":"function"}]).functions.getAssetManagers().call(block_identifier=blk)
out={"pinned":{"flare_block":blk,"xrpl_ledger":lidx},"assets":[]}
for M in mgrs:
    am=w3.eth.contract(address=Web3.to_checksum_address(M),abi=AMABI)
    fa=am.functions.fAsset().call(block_identifier=blk); f=w3.eth.contract(address=Web3.to_checksum_address(fa),abi=ERC)
    sym=f.functions.symbol().call(); dec=f.functions.decimals().call(); supply=f.functions.totalSupply().call(block_identifier=blk)
    agents,_=am.functions.getAllAgents(0,1000).call(block_identifier=blk)
    # Required minimum CRs (liquidation floors) per collateral type. Fail-closed: unavailable => report
    # actual CRs with required=None (LEG 1 still verdicts off the authoritative AgentStatus signal).
    reqVault={}; reqPool=None  # token(lower)->min_bips ; pool min_bips
    try:
        for ct in am.functions.getCollateralTypes().call(block_identifier=blk):
            cls=int(ct[0]); token=ct[1]; min_bips=int(ct[7])  # [0]class [1]token [7]minCollateralRatioBIPS
            if cls==1: reqPool=min_bips
            elif cls==2: reqVault[str(token).lower()]=min_bips
    except Exception: pass
    backing_verdict="PROVEN"; backing=0; ag=[]
    # LEG 2 (XRPL backing) + LEG 1 (Flare-side over-collateralization) computed together per agent.
    coll_flags=[]  # agents the protocol's own status machine flags (CCB / liquidation / destroying)
    inflight_reserved=0; inflight_redeeming=0  # 14-day mint/redeem windows — snapshot does NOT net these
    for a in agents:
        d=dict(zip(comps,am.functions.getAgentInfo(a).call(block_identifier=blk)))
        b=underlying_backing(d["underlyingAddressString"],lidx)
        if b is None: backing_verdict="CANNOT_VERIFY"; live=None
        else: live=sum(b); backing+=live
        # LEG 1: agent over-collateralization from the AUTHORITATIVE protocol signal (status + liq timestamp),
        # not a guessed threshold. status==0 & liqStart==0 => the protocol itself considers it solvent/healthy.
        st=int(d["status"]); liq=int(d["liquidationStartTimestamp"])
        vcr=int(d["vaultCollateralRatioBIPS"]); pcr=int(d["poolCollateralRatioBIPS"])
        mvcr=int(d["mintingVaultCollateralRatioBIPS"]); mpcr=int(d["mintingPoolCollateralRatioBIPS"])
        # REQUIRED min CRs (liquidation floors) for THIS agent's collateral types.
        rv=reqVault.get(str(d["vaultCollateralToken"]).lower()); rp=reqPool
        # LEG 1 verdict: primary = authoritative AgentStatus. Secondary cross-check = current CR vs the
        # required floor (should agree with status; a NORMAL agent below floor is a discrepancy => flag).
        above_floor = ((rv is None or vcr>=rv) and (rp is None or pcr>=rp))
        healthy = (st==0 and liq==0 and above_floor)
        if not healthy: coll_flags.append({"vault":a,"status":STATUS_NAMES.get(st,st),"liqStart":liq,
            "vaultCR_pct":round(vcr/100,2),"reqVaultCR_pct":round(rv/100,2) if rv else None,
            "poolCR_pct":round(pcr/100,2),"reqPoolCR_pct":round(rp/100,2) if rp else None})
        inflight_reserved+=int(d.get("reservedUBA",0)); inflight_redeeming+=int(d.get("redeemingUBA",0))
        ag.append({"vault":a,"addr":d["underlyingAddressString"],"minted":d["mintedUBA"],"live":live,
            # LEG 1 (BIPS; /100 = percent): current CRs, the SYSTEM-REQUIRED floor, buffer, and the verdict.
            "status":STATUS_NAMES.get(st,st),"liquidationStart":liq,
            "vaultCR_pct":round(vcr/100,2),"reqVaultCR_pct":round(rv/100,2) if rv else None,
            "poolCR_pct":round(pcr/100,2),"reqPoolCR_pct":round(rp/100,2) if rp else None,
            "vaultBufferPP": round((vcr-rv)/100,2) if rv else None,   # percentage-points above the liquidation floor
            "poolBufferPP": round((pcr-rp)/100,2) if rp else None,
            "collateral":"HEALTHY" if healthy else "FLAGGED"})
    CVM=am.functions.getCoreVaultManager().call(block_identifier=blk)
    cvaddr=w3.eth.contract(address=Web3.to_checksum_address(CVM),abi=CVABI).functions.coreVaultAddress().call(block_identifier=blk)
    cv=underlying_backing(cvaddr,lidx)
    if cv is None: backing_verdict="CANNOT_VERIFY"
    else: backing+=sum(cv)
    # OVERALL: SOLVENT requires BOTH legs — real XRPL backing >= supply AND no agent under-collateralized.
    backing_verdict, collateral_verdict, overall = combine_verdict(
        backing_verdict=="CANNOT_VERIFY", backing, supply, len(coll_flags))
    # HONEST LABELING — never ship a verdict without its assumptions (accuracy-first / xahc-prover discipline).
    cv_escrow = cv[1] if cv else 0
    caveats=[
        "POINT-IN-TIME: verdict is pinned to the block/ledger above and decays the next ledger; re-run for a current view.",
        "IN-FLIGHT NOT NETTED: reserved={} + redeeming={} UBA are in 14-day mint/redeem windows; the backing check compares live XRPL balance vs total FXRP supply without netting these (conservative but not exact).".format(inflight_reserved,inflight_redeeming),
        "CORE-VAULT ESCROW: {} UBA of Core-Vault backing is XRPL Escrow (time-locked); it is counted as backing but the escrow release ladder / finish conditions are NOT verified here.".format(cv_escrow),
        "FDC TRUST: the mint side of FAssets trusts Flare's FDC attestation set for XRPL->Flare proofs; this tool re-derives balances directly from XRPL and does NOT re-verify FDC's attestations.",
        "CR SIGNAL: LEG 1's verdict is the protocol's own AgentStatus (NORMAL/CCB/LIQUIDATION) — authoritative. It ALSO tries to read the system-required min CR (getCollateralTypes.minCollateralRatioBIPS) to show 'CR vs floor'; if that read is unavailable on the current deployment (as it is at this AssetManager), required shows null and the verdict falls back to status-only (still sound).",
        "AGENT SET: enumerated via getAllAgents(0,1000); if the system ever exceeds 1000 agents this must paginate (currently {} agents).".format(len(agents)),
    ]
    trust_model={
        "provable_trustlessly":"XRPL 1:1 backing (agent + Core-Vault balances incl. on-ledger escrow, re-derived from raw XRPL, no indexer/oracle) and agent over-collateralization status (read from Flare mainnet).",
        "conditional_trust":"FDC attestation set (mint proofs) and the marked value / release schedule of time-locked escrow.",
        "not_claimed":"That FXRP is safe from every economic risk; this is a solvency snapshot (backing >= supply AND no agent in liquidation), not an audit of the FAssets contracts or FDC.",
    }
    out["assets"].append({"symbol":sym,"assetManager":M,"decimals":dec,"totalSupply":supply,"agents":ag,
        "coreVault":{"addr":cvaddr,"liquid":cv[0] if cv else None,"escrow":cv[1] if cv else None},
        "realBacking":backing,"surplus":backing-supply,
        "inFlight":{"reservedUBA":inflight_reserved,"redeemingUBA":inflight_redeeming},
        "backingVerdict":backing_verdict,          # LEG 2 (XRPL 1:1 backing)
        "collateralVerdict":collateral_verdict,    # LEG 1 (Flare over-collateralization)
        "collateralFlags":coll_flags,
        "verdict":overall,                         # combined
        "caveats":caveats,"trustModel":trust_model})
json.dump(out, open("reserves.json","w"), indent=2)
if "--json" in sys.argv: print(json.dumps(out,indent=2))
else:
    print(f"FAssets Proof-of-Reserves @ Flare#{blk} / XRPL#{lidx}  ({len(out['assets'])} live FAsset)")
    for a in out["assets"]:
        s=10**a["decimals"]
        print(f"\n  {a['symbol']}: supply {a['totalSupply']/s:,.2f} | real backing {a['realBacking']/s:,.2f} | surplus {a['surplus']/s:+,.2f}")
        print(f"    {len(a['agents'])} agents + Core Vault (liquid {a['coreVault']['liquid']/1e6:,.0f} + escrow {a['coreVault']['escrow']/1e6:,.0f})")
        print(f"    ===== {a['verdict']} =====")
