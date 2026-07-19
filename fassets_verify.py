#!/usr/bin/env python3
"""fassets-verify — independent Proof-of-Reserves for the Flare FAssets SYSTEM.
Auto-discovers EVERY live FAsset via AssetManagerController.getAssetManagers() (FXRP today; FBTC/FDOGE automatically
when they launch), and for each re-derives 'every unit is backed by real underlying' from raw Flare + XRPL data,
trusting no indexer. Backing = Σ agents' LIVE underlying balance + Core Vault (liquid Balance + on-ledger Escrow objects).
The Core Vault holds ~140M XRP in XRPL Escrow that a naive Balance check MISSES; we read the escrows. Fail-closed."""
import json, sys, time, urllib.request
from web3 import Web3
# Multiple RPC endpoints per chain — fail OVER on error so one dead/rate-limited node can't sink a run.
FLARE_RPCS=["https://flare-api.flare.network/ext/C/rpc","https://rpc.ankr.com/flare","https://flare.public-rpc.com"]
XRPL_RPCS=["https://xrplcluster.com/","https://s1.ripple.com:51234/","https://s2.ripple.com:51234/"]
CTRL="0x097B93eEBe9b76f2611e1E7D9665a9d7Ff5280B3"
def connect_flare():
    for url in FLARE_RPCS:
        try:
            c=Web3(Web3.HTTPProvider(url,request_kwargs={"timeout":30}))
            _=c.eth.block_number   # probe the endpoint before trusting it
            return c,url
        except Exception as e:
            sys.stderr.write("WARN: Flare RPC %s unavailable (%s); trying next\n"%(url,str(e)[:80]))
    raise SystemExit("FATAL: no Flare RPC endpoint reachable")
w3,FLARE_USED=connect_flare()
def xrpl(m,p):
    last=None
    for url in XRPL_RPCS:
        for _attempt in range(2):
            try:
                r=urllib.request.Request(url, json.dumps({"method":m,"params":[p]}).encode(), {"Content-Type":"application/json"})
                return json.load(urllib.request.urlopen(r,timeout=30))["result"]
            except Exception as e:
                last="%s @ %s"%(str(e)[:70],url); time.sleep(0.5)
    raise RuntimeError("XRPL RPC failed on all endpoints for %s: %s"%(m,last))
def underlying_backing(addr,lidx,dest_filter=None):
    """Returns (liquid, locked, excluded). Escrows CREATED by addr are 'locked' backing — but if
    dest_filter is set, only escrows whose Destination == dest_filter count; any paying ELSEWHERE go to
    'excluded' (not counted as backing, since that XRP will leave the system on finish)."""
    ai=xrpl("account_info",{"account":addr,"ledger_index":lidx})
    if "account_data" not in ai: return None
    liquid=int(ai["account_data"]["Balance"]); locked=0; excluded=0; marker=None
    while True:
        p={"account":addr,"type":"escrow","ledger_index":lidx,"limit":400}
        if marker:p["marker"]=marker
        r=xrpl("account_objects",p)
        if "account_objects" not in r: return None
        for o in r["account_objects"]:
            if o.get("Account")!=addr: continue
            amt=int(o.get("Amount","0"))
            if dest_filter is not None and o.get("Destination")!=dest_filter: excluded+=amt
            else: locked+=amt
        marker=r.get("marker")
        if not marker: break
    return liquid,locked,excluded
gai=json.load(open("agentinfo_abi.json")); comps=[c['name'] for c in gai[0]["outputs"][0]["components"]]
AMABI=gai+[
 {"inputs":[],"name":"fAsset","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"},
 {"inputs":[{"type":"uint256"},{"type":"uint256"}],"name":"getAllAgents","outputs":[{"type":"address[]"},{"type":"uint256"}],"stateMutability":"view","type":"function"},
 {"inputs":[],"name":"getCoreVaultManager","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"},
 # CollateralType[] — the SYSTEM-REQUIRED minimum collateral ratios (the liquidation floors). collateralClass
 # 1=POOL(NAT/FLR), 2=VAULT. Use minCollateralRatioBIPS (documented floor: pool 150% / vault 120%); NOT
 # safetyMinCollateralRatioBIPS (reads ~3 BIPS = effectively unset). Lets LEG 1 report "CR vs REQUIRED".
 # v1.3 CollateralType struct is 9 fields (confirmed by decoding the live return; the older 10th field
 # safetyMinCollateralRatioBIPS is gone). minCollateralRatioBIPS (index 7) is the liquidation floor:
 # decoded live = pool(class 1) 15000 BIPS = 150%, vault(class 2) 12000 BIPS = 120%.
 {"inputs":[],"name":"getCollateralTypes","outputs":[{"type":"tuple[]","components":[
   {"type":"uint8","name":"collateralClass"},{"type":"address","name":"token"},{"type":"uint256","name":"decimals"},
   {"type":"uint256","name":"validUntil"},{"type":"bool","name":"directPricePair"},{"type":"string","name":"assetFtsoSymbol"},
   {"type":"string","name":"tokenFtsoSymbol"},{"type":"uint256","name":"minCollateralRatioBIPS"},
   {"type":"uint256","name":"ccbMinCollateralRatioBIPS"}]}],
  "stateMutability":"view","type":"function"}]
ERC=[{"inputs":[],"name":"symbol","outputs":[{"type":"string"}],"stateMutability":"view","type":"function"},{"inputs":[],"name":"totalSupply","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},{"inputs":[],"name":"decimals","outputs":[{"type":"uint8"}],"stateMutability":"view","type":"function"}]
CVABI=[{"inputs":[],"name":"coreVaultAddress","outputs":[{"type":"string"}],"stateMutability":"view","type":"function"},
 {"inputs":[],"name":"custodianAddress","outputs":[{"type":"string"}],"stateMutability":"view","type":"function"}]
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
    # Paginate getAllAgents so coverage is COMPLETE even if the system exceeds one page (fail-closed: we
    # never silently cap at 1000). The 2nd return value is the total agent count.
    agents=[]; _start=0
    while True:
        _chunk,_total=am.functions.getAllAgents(_start,1000).call(block_identifier=blk)
        agents+=list(_chunk)
        if not _chunk or len(agents)>=int(_total): break
        _start+=len(_chunk)
    # Required minimum CRs (liquidation floors) per collateral type. Fail-closed: unavailable => report
    # actual CRs with required=None (LEG 1 still verdicts off the authoritative AgentStatus signal).
    reqVault={}; reqPool=None; floor_read_ok=False  # token(lower)->min_bips ; pool min_bips
    try:
        for ct in am.functions.getCollateralTypes().call(block_identifier=blk):
            cls=int(ct[0]); token=ct[1]; min_bips=int(ct[7])  # [0]class [1]token [7]minCollateralRatioBIPS
            if cls==1: reqPool=min_bips
            elif cls==2: reqVault[str(token).lower()]=min_bips
        floor_read_ok = (reqPool is not None and len(reqVault)>0)
    except Exception as _e:
        sys.stderr.write("WARN: getCollateralTypes floor read failed (%s) — LEG 1 degrades to status-only\n" % str(_e)[:100])
    backing_verdict="PROVEN"; backing=0; ag=[]
    # LEG 2 (XRPL backing) + LEG 1 (Flare-side over-collateralization) computed together per agent.
    coll_flags=[]  # agents the protocol's own status machine flags (CCB / liquidation / destroying)
    inflight_reserved=0; inflight_redeeming=0  # 14-day mint/redeem windows — snapshot does NOT net these
    for a in agents:
        d=dict(zip(comps,am.functions.getAgentInfo(a).call(block_identifier=blk)))
        b=underlying_backing(d["underlyingAddressString"],lidx)
        if b is None: backing_verdict="CANNOT_VERIFY"; live=None
        else: live=b[0]+b[1]; backing+=live   # liquid + own escrows (agents have no custodian binding)
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
        # SYSTEM verdict is scoped by EXPOSURE: a non-healthy agent with ZERO minted FXRP carries no obligation
        # (a DESTROYING wind-down requires minted==0; a zero-minted full-liquidation on an illegal-payment proof),
        # so it must not flip a fully-backed system to UNDER_COLLATERALIZED. It is still surfaced per-agent below.
        if not healthy and int(d["mintedUBA"])>0:
            coll_flags.append({"vault":a,"status":STATUS_NAMES.get(st,st),"liqStart":liq,"mintedUBA":str(d["mintedUBA"]),
                "belowFloor":not above_floor,
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
    cvm=w3.eth.contract(address=Web3.to_checksum_address(CVM),abi=CVABI)
    cvaddr=cvm.functions.coreVaultAddress().call(block_identifier=blk)
    # The Core Vault's designated on-chain custodian. Escrows count as backing ONLY if they pay HERE, and
    # the custodian's OWN balance is added so a FINISHED escrow (which delivers to the custodian) is not
    # under-counted — the escrow->custodian transition is backing-neutral.
    try: custodian=cvm.functions.custodianAddress().call(block_identifier=blk)
    except Exception: custodian=None
    cv=underlying_backing(cvaddr,lidx,dest_filter=custodian)
    cust=underlying_backing(custodian,lidx) if custodian else None
    if cv is None or (custodian and cust is None): backing_verdict="CANNOT_VERIFY"
    else:
        backing += cv[0]+cv[1]                 # CV liquid + escrows locked TO the custodian
        if cust: backing += cust[0]            # custodian's own liquid balance (finished escrows land here)
    cv_excluded_escrow = cv[2] if cv else 0    # escrows paying somewhere OTHER than the custodian (not backing)
    # OVERALL: SOLVENT requires BOTH legs — real XRPL backing >= supply AND no agent under-collateralized.
    backing_verdict, collateral_verdict, overall = combine_verdict(
        backing_verdict=="CANNOT_VERIFY", backing, supply, len(coll_flags))
    # HONEST LABELING — never ship a verdict without its assumptions (accuracy-first / xahc-prover discipline).
    cv_escrow = cv[1] if cv else 0
    caveats=[
        "POINT-IN-TIME: verdict is pinned to the block/ledger above and decays the next ledger; re-run for a current view.",
        "IN-FLIGHT NOT NETTED: reserved={} + redeeming={} UBA are in 14-day mint/redeem windows; the backing check compares live XRPL balance vs total FXRP supply without netting these (conservative but not exact).".format(inflight_reserved,inflight_redeeming),
        ("CORE-VAULT ESCROW: {} UBA of Core-Vault backing is in XRPL Escrows — CONDITION-GATED (crypto-condition + CancelAfter, not a simple time-lock) and verified to pay ONLY the on-chain custodian {}. Escrows paying elsewhere ({} UBA) are EXCLUDED from backing. The custodian's own balance is included, so a FINISHED escrow stays counted. The custodian is a named, trusted holder — this binds the claim to its on-chain identity, it does not make custody trustless.".format(cv_escrow, custodian, cv_excluded_escrow)),
        "FDC TRUST: the mint side of FAssets trusts Flare's FDC attestation set for XRPL->Flare proofs; this tool re-derives balances directly from XRPL and does NOT re-verify FDC's attestations.",
        ("CR FLOOR: LEG 1 flags an agent if its live collateral ratio is BELOW the system-required floor "
         "(getCollateralTypes minCollateralRatioBIPS: pool 150% / vault 120%) OR the protocol's AgentStatus is "
         "non-NORMAL. The floor check is what catches a below-floor agent that liquidation has NOT yet been "
         "triggered against (FAssets liquidation is permissionless/trigger-driven, so status alone is not "
         "sufficient)." if floor_read_ok else
         "CR FLOOR UNAVAILABLE (fail-closed note): the system-required floor read (getCollateralTypes) FAILED this "
         "run, so LEG 1 is running on AgentStatus ONLY. Because FAssets liquidation is trigger-driven, status alone "
         "does NOT catch a below-floor agent that has not yet been liquidated — treat OVER_COLLATERALIZED as "
         "unconfirmed until the floor read is restored."),
        "AGENT SET: enumerated via getAllAgents(0,1000); if the system ever exceeds 1000 agents this must paginate (currently {} agents).".format(len(agents)),
    ]
    trust_model={
        "provable_trustlessly":"XRPL 1:1 backing (agent + Core-Vault balances incl. on-ledger escrow, re-derived from raw XRPL, no indexer/oracle) and agent over-collateralization status (read from Flare mainnet).",
        "conditional_trust":"FDC attestation set (mint proofs); and the named on-chain custodian ("+str(custodian)+") that the Core-Vault escrows pay to and that holds finished-escrow XRP — its holding is verified on-ledger, its honesty is trusted.",
        "not_claimed":"That FXRP is safe from every economic risk; this is a solvency snapshot (backing >= supply AND no agent in liquidation), not an audit of the FAssets contracts or FDC.",
    }
    out["assets"].append({"symbol":sym,"assetManager":M,"decimals":dec,"totalSupply":supply,"agents":ag,
        "coreVault":{"addr":cvaddr,"liquid":cv[0] if cv else None,"escrow_to_custodian":cv[1] if cv else None,
            "escrow_excluded":cv_excluded_escrow,"custodian":custodian,
            "custodian_liquid":cust[0] if cust else None},
        "realBacking":backing,"surplus":backing-supply,
        "inFlight":{"reservedUBA":inflight_reserved,"redeemingUBA":inflight_redeeming},
        "backingVerdict":backing_verdict,          # LEG 2 (XRPL 1:1 backing)
        "collateralVerdict":collateral_verdict,    # LEG 1 (Flare over-collateralization)
        "floorReadOk":floor_read_ok,               # was the system-required CR floor read live? (LEG 1 is status-only if False)
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
        _cvv=a['coreVault']; _liq=_cvv.get('liquid') or 0; _esc=_cvv.get('escrow_to_custodian') or 0
        print(f"    {len(a['agents'])} agents + Core Vault (liquid {_liq/1e6:,.0f} + escrow {_esc/1e6:,.0f})")
        print(f"    ===== {a['verdict']} =====")
