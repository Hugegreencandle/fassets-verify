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
# underlying_backing / evaluate_agent / combine_verdict live in fassets_lib (pure + unit-testable); the
# xrpl() function is INJECTED into underlying_backing so the derivation can be tested with a mock.
from fassets_lib import underlying_backing, evaluate_agent, mark_to_market, combine_verdict, STATUS_NAMES
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
BIPS=10000  # collateral ratios are in BIPS (10000 = 100%)
blk=w3.eth.block_number; lidx=xrpl("ledger",{"ledger_index":"validated"})["ledger_index"]
mgrs=w3.eth.contract(address=Web3.to_checksum_address(CTRL),abi=[{"inputs":[],"name":"getAssetManagers","outputs":[{"type":"address[]"}],"stateMutability":"view","type":"function"}]).functions.getAssetManagers().call(block_identifier=blk)
out={"pinned":{"flare_block":blk,"xrpl_ledger":lidx},"assets":[]}
for M in mgrs:
    am=w3.eth.contract(address=Web3.to_checksum_address(M),abi=AMABI)
    fa=am.functions.fAsset().call(block_identifier=blk); f=w3.eth.contract(address=Web3.to_checksum_address(fa),abi=ERC)
    sym=f.functions.symbol().call(); dec=f.functions.decimals().call(); supply=f.functions.totalSupply().call(block_identifier=blk)
    # Paginate getAllAgents so coverage is COMPLETE even beyond one page. IMPORTANT: the 2nd arg is an
    # END INDEX (the call returns agents[start:end]), NOT a page size — verified live: getAllAgents(2,3)
    # returns 1 agent. So request [start, start+1000) each round. 2nd return value is the total count.
    agents=[]; _start=0
    while True:
        _chunk,_total=am.functions.getAllAgents(_start,_start+1000).call(block_identifier=blk)
        agents+=list(_chunk)
        if not _chunk or len(agents)>=int(_total): break
        _start+=len(_chunk)
    # Required minimum CRs (liquidation floors) per collateral type. Fail-closed: unavailable => report
    # actual CRs with required=None (LEG 1 still verdicts off the authoritative AgentStatus signal).
    reqVault={}; reqPool=None; floor_read_ok=False  # token(lower)->min_bips ; pool min_bips
    ftso_syms=set(); pool_sym=None; vault_sym_by_token={}; vault_dec_by_token={}; asset_sym=None
    try:
        for ct in am.functions.getCollateralTypes().call(block_identifier=blk):
            cls=int(ct[0]); token=ct[1]; cdec=int(ct[2]); asym=ct[5]; tsym=ct[6]; min_bips=int(ct[7])
            if cls==1: reqPool=min_bips; pool_sym=tsym or pool_sym                 # POOL = FLR/WNat
            elif cls==2:                                                            # VAULT collateral token(s)
                reqVault[str(token).lower()]=min_bips
                vault_sym_by_token[str(token).lower()]=tsym; vault_dec_by_token[str(token).lower()]=cdec
            if tsym: ftso_syms.add(tsym)
            if asym: asset_sym=asym                                                 # asset priced = XRP
        floor_read_ok = (reqPool is not None and len(reqVault)>0)
    except Exception as _e:
        sys.stderr.write("WARN: getCollateralTypes floor read failed (%s) — LEG 1 degrades to status-only\n" % str(_e)[:100])
    # LEG 1.5 (MARK-TO-MARKET): resolve FTSOv2 via the Flare contract registry and read USD prices for the
    # asset (XRP) + each collateral token's FTSO symbol, PINNED to the block. This lets us RE-DERIVE each
    # agent's collateral ratio from raw amounts x Flare's OWN enshrined oracle — turning the protocol's
    # self-reported CR from a trusted number into a CHECKED one. Fail-SOFT: if FTSOv2 or a feed is
    # unavailable/stale, LEG 1.5 is omitted; it NEVER gates the core two-leg verdict.
    ftso_ok=False; prices={}; ftso_stale=False; ftso_v2_addr=None; asset_sym=asset_sym or "XRP"
    try:
        reg=w3.eth.contract(address=Web3.to_checksum_address("0xaD67FE66660Fb8dFE9d6b1b4240d8650e30F6019"),
            abi=[{"inputs":[{"type":"string"}],"name":"getContractAddressByName","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"}])
        ftso_v2_addr=reg.functions.getContractAddressByName("FtsoV2").call(block_identifier=blk)
        f2=w3.eth.contract(address=Web3.to_checksum_address(ftso_v2_addr),
            abi=[{"inputs":[{"type":"bytes21"}],"name":"getFeedById","outputs":[{"type":"uint256"},{"type":"int8"},{"type":"uint64"}],"stateMutability":"payable","type":"function"}])
        btime=w3.eth.get_block(blk)["timestamp"]
        def _feed_id(name): h="01"+name.encode().hex(); return "0x"+h+"0"*(42-len(h))
        for _s in (set(ftso_syms)|{asset_sym}):
            v,dd,ts=f2.functions.getFeedById(_feed_id(_s+"/USD")).call(block_identifier=blk)
            prices[_s]=v/10**dd
            if abs(int(btime)-int(ts))>600: ftso_stale=True                        # feed older than 10 min => stale
        ftso_ok = (asset_sym in prices and not ftso_stale)
    except Exception as _e:
        sys.stderr.write("WARN: FTSOv2 mark-to-market unavailable (%s) — LEG 1.5 omitted\n" % str(_e)[:100])
    mtm_usd_collateral=0.0; mtm_usd_obligation=0.0; mtm_divergences=[]   # LEG 1.5 system accumulators
    backing_verdict="PROVEN"; backing=0; ag=[]
    # LEG 2 (XRPL backing) + LEG 1 (Flare-side over-collateralization) computed together per agent.
    coll_flags=[]           # EXPOSED agents flagged under-collateralized (status non-NORMAL OR below a known floor)
    coll_unverifiable=[]    # EXPOSED agents whose required floor could NOT be verified (fail-closed, not "healthy")
    agent_escrow_excluded=0 # agent escrows paying OUT of the system (to redeemers/elsewhere) — not counted as backing
    inflight_reserved=0; inflight_redeeming=0
    seen_addrs=set()        # guard against double-counting a repeated underlying address
    for a in agents:
        d=dict(zip(comps,am.functions.getAgentInfo(a).call(block_identifier=blk)))
        uaddr=d["underlyingAddressString"]
        # FAssets enforces unique agent underlying addresses; if one ever repeats, refuse to double-count (fail-closed).
        if uaddr in seen_addrs: backing_verdict="CANNOT_VERIFY"
        seen_addrs.add(uaddr)
        # Agent escrows are dest-filtered to the agent's OWN address: only self-returning escrows count as backing;
        # any escrow paying elsewhere (e.g. a redeemer) is EXCLUDED — that XRP leaves the system on EscrowFinish and
        # must not inflate backing. (Symmetric with the Core-Vault custodian binding.)
        b=underlying_backing(xrpl,uaddr,lidx,dest_filter=uaddr)
        if b is None: backing_verdict="CANNOT_VERIFY"; live=None
        else: live=b[0]+b[1]; backing+=live; agent_escrow_excluded+=b[2]
        ev=evaluate_agent(d, reqVault, reqPool)   # pure LEG-1 classification: HEALTHY / FLAGGED / UNVERIFIED
        minted=int(d["mintedUBA"])
        # LEG 1.5: independent mark-to-market of THIS agent via FTSOv2 (recompute CR from raw amounts x oracle).
        vtok=str(d["vaultCollateralToken"]).lower(); vsym=vault_sym_by_token.get(vtok); vdec=vault_dec_by_token.get(vtok,6)
        if ftso_ok and vsym in prices and pool_sym in prices:
            mtm=mark_to_market(d, prices[asset_sym], prices[vsym], prices[pool_sym], vdec)
            ev.update(mtm)
            if minted>0:
                mtm_usd_collateral+=mtm["usdTotalCollateral"]; mtm_usd_obligation+=mtm["usdObligation"]
                # cross-check: our independent vault CR vs the protocol's REPORTED vault CR — flag big divergence
                if mtm["indepVaultCR_pct"] is not None and ev["vaultCR_pct"]:
                    dvg=abs(mtm["indepVaultCR_pct"]-ev["vaultCR_pct"])/ev["vaultCR_pct"]
                    if dvg>0.20:
                        mtm_divergences.append({"vault":a,"reportedVaultCR_pct":ev["vaultCR_pct"],
                            "indepVaultCR_pct":mtm["indepVaultCR_pct"],"divergence_pct":round(dvg*100,1)})
        # SYSTEM verdict scoped by EXPOSURE (mintedUBA>0): a zero-minted distressed agent carries no FXRP-holder
        # obligation and must not flip a fully-backed system — still surfaced per-agent below.
        if minted>0:
            if ev["collateral"]=="FLAGGED":
                coll_flags.append({"vault":a,"status":ev["status"],"liqStart":ev["liquidationStart"],"mintedUBA":str(minted),
                    "vaultCR_pct":ev["vaultCR_pct"],"reqVaultCR_pct":ev["reqVaultCR_pct"],
                    "poolCR_pct":ev["poolCR_pct"],"reqPoolCR_pct":ev["reqPoolCR_pct"]})
            elif ev["collateral"]=="UNVERIFIED":
                coll_unverifiable.append({"vault":a,"mintedUBA":str(minted),
                    "reason":"required collateral floor unknown for this agent (token not in floor map, or floor read failed)"})
        inflight_reserved+=int(d.get("reservedUBA",0)); inflight_redeeming+=int(d.get("redeemingUBA",0))
        ag.append({"vault":a,"addr":uaddr,"minted":d["mintedUBA"],"live":live, **ev})
    CVM=am.functions.getCoreVaultManager().call(block_identifier=blk)
    cvm=w3.eth.contract(address=Web3.to_checksum_address(CVM),abi=CVABI)
    cvaddr=cvm.functions.coreVaultAddress().call(block_identifier=blk)
    # The Core Vault's designated on-chain custodian. Escrows count as backing ONLY if they pay HERE; the
    # custodian's OWN balance is added so a FINISHED escrow (delivered to the custodian) stays counted. If the
    # custodian address CANNOT be read, we cannot apply the dest-filter — FAIL CLOSED (never count CV escrows
    # unfiltered), rather than silently inflating backing.
    try: custodian=cvm.functions.custodianAddress().call(block_identifier=blk)
    except Exception: custodian=None
    if custodian is None:
        backing_verdict="CANNOT_VERIFY"; cv=None; cust=None
    else:
        cv=underlying_backing(xrpl,cvaddr,lidx,dest_filter=custodian)
        cust=underlying_backing(xrpl,custodian,lidx)
        if cv is None or cust is None:
            backing_verdict="CANNOT_VERIFY"
        elif cvaddr in seen_addrs or custodian in seen_addrs:
            backing_verdict="CANNOT_VERIFY"   # CV/custodian coincides with an agent address — refuse to double-count
        else:
            backing += cv[0]+cv[1]            # CV liquid + escrows locked TO the custodian
            backing += cust[0]                # custodian's own liquid balance (finished escrows land here)
    cv_excluded_escrow = cv[2] if cv else 0
    cv_escrow = cv[1] if cv else 0
    # OVERALL: SOLVENT requires BOTH legs. LEG 2 backing is NET of redeeming UBA (that XRP is earmarked to leave to
    # redeemers, so it does not back remaining FXRP — netting it is the CONSERVATIVE direction). LEG 1 fails closed
    # if any exposed agent's floor is unverifiable.
    net_backing = backing - inflight_redeeming
    backing_verdict, collateral_verdict, overall = combine_verdict(
        backing_verdict=="CANNOT_VERIFY", net_backing, supply, len(coll_flags), len(coll_unverifiable))
    surplus = net_backing - supply
    caveats=[
        "POINT-IN-TIME: verdict is pinned to the block/ledger above and decays the next ledger; re-run for a current view.",
        "IN-FLIGHT: redeeming ({} UBA) is NETTED OUT of the solvency comparison — that XRP is earmarked to leave to redeemers, so it does not back the remaining FXRP (netting it is the conservative direction). Reserved ({} UBA, mid-mint collateral) is not netted: no FXRP is minted against it yet, so it is backing-neutral.".format(inflight_redeeming, inflight_reserved),
        ("CORE-VAULT ESCROW: {} UBA of Core-Vault backing is in XRPL Escrows — CONDITION-GATED (crypto-condition + CancelAfter, not a simple time-lock) and verified to pay ONLY the on-chain custodian {}. Escrows paying elsewhere ({} UBA) are EXCLUDED from backing. The custodian's own balance is included, so a FINISHED escrow stays counted. The custodian is a named, trusted holder — this binds the claim to its on-chain identity, it does not make custody trustless.".format(cv_escrow, custodian, cv_excluded_escrow)),
        "AGENT ESCROWS: agent underlying escrows are counted as backing ONLY if they return to the agent's own address; any agent escrow paying elsewhere is EXCLUDED ({} UBA this run) since it would leave the system on finish (symmetric with the Core-Vault custodian binding).".format(agent_escrow_excluded),
        "CUSTODIAN ATTRIBUTION: the custodian's ENTIRE liquid balance is attributed to FXRP backing; if the custodian ever holds XRP unrelated to FXRP finished-escrow proceeds this over-counts. Its holding is verified on-ledger; the full-attribution is a trusted assumption.",
        "RESERVES INCLUDED: liquid figures use the raw XRPL account Balance, which includes each account's (unspendable) base + owner reserve — a small bounded over-count of spendable backing (~1 XRP base + ~0.2 XRP per owned object, per account).",
        "FDC TRUST: the mint side of FAssets trusts Flare's FDC attestation set for XRPL->Flare proofs; this tool re-derives balances directly from XRPL and does NOT re-verify FDC's attestations.",
        ("CR FLOOR: LEG 1 flags an agent below the system-required floor (getCollateralTypes minCollateralRatioBIPS: "
         "pool 150% / vault 120%) OR whose AgentStatus is non-NORMAL — catching a below-floor agent liquidation has "
         "NOT yet been triggered against (FAssets liquidation is permissionless/trigger-driven, so status alone is "
         "insufficient)." if floor_read_ok else
         "CR FLOOR UNREAD (FAIL-CLOSED): the system-required floor read (getCollateralTypes) FAILED this run, so LEG 1 "
         "cannot verify over-collateralization; every exposed agent is marked UNVERIFIED and the verdict is forced to "
         "CANNOT_VERIFY rather than a status-only OVER_COLLATERALIZED."),
        ("MARK-TO-MARKET (LEG 1.5): each agent's collateral ratio is INDEPENDENTLY re-derived from raw collateral "
         "amounts (totalVaultCollateralWei/totalPoolCollateralNATWei) valued in USD via Flare's own FTSOv2 oracle "
         "({}), vs the minted-XRP obligation — turning the protocol's SELF-REPORTED CR into a CHECKED one. Agent "
         "collateral (USD) covers the minted obligation by {:.1f}%. {} agent(s) diverged >20% from the reported CR. "
         "This is an ADDITIVE cross-check; it does not gate the two-leg verdict.".format(
             ftso_v2_addr, (mtm_usd_collateral/mtm_usd_obligation*100) if mtm_usd_obligation>0 else 0, len(mtm_divergences))
         if ftso_ok else
         "MARK-TO-MARKET (LEG 1.5) UNAVAILABLE this run (FTSOv2 unreachable or a price feed was stale); the core two-leg verdict is unaffected."),
        "COLLATERAL SCOPE: LEG-1 flags/unverifiable are scoped to agents with mintedUBA>0 (FXRP-holder exposure); a distressed agent with zero minted FXRP owes redeemers, not holders, and is surfaced per-agent but not counted into the system verdict.",
        "CROSS-CHAIN SKEW: supply is read at the Flare block and backing at the XRPL ledger above — near-simultaneous but not identical instants; a mint/redeem completing between them is not netted (bounded by in-window volume).",
        "AGENT SET: enumerated via getAllAgents paginated by end-index (start,start+1000); complete for the current {} agents and beyond.".format(len(agents)),
    ]
    trust_model={
        "provable_trustlessly":"XRPL 1:1 backing (agent + Core-Vault balances incl. on-ledger escrow, re-derived from raw XRPL, no indexer/oracle) and agent over-collateralization VERIFIED against the system-required floor (read from Flare mainnet); fail-closed to CANNOT_VERIFY if the floor cannot be read.",
        "conditional_trust":"FDC attestation set (mint proofs); and the named on-chain custodian ("+str(custodian)+") that the Core-Vault escrows pay to and whose ENTIRE balance is attributed to FXRP backing — verified on-ledger, its honesty and full-attribution trusted.",
        "not_claimed":"That FXRP is safe from every economic risk; this is a solvency snapshot (backing net of redeeming >= supply AND every exposed agent verifiably over its floor), not an audit of the FAssets contracts or FDC.",
    }
    out["assets"].append({"symbol":sym,"assetManager":M,"decimals":dec,"totalSupply":supply,"agents":ag,
        "coreVault":{"addr":cvaddr,"liquid":cv[0] if cv else None,"escrow_to_custodian":cv[1] if cv else None,
            "escrow_excluded":cv_excluded_escrow,"custodian":custodian,
            "custodian_liquid":cust[0] if cust else None},
        "realBacking":backing,"netBacking":net_backing,"surplus":surplus,   # surplus is net of redeeming
        "agentEscrowExcluded":agent_escrow_excluded,
        "inFlight":{"reservedUBA":inflight_reserved,"redeemingUBA":inflight_redeeming},
        "backingVerdict":backing_verdict,          # LEG 2 (XRPL 1:1 backing, net of redeeming)
        "collateralVerdict":collateral_verdict,    # LEG 1 (Flare over-collateralization; CANNOT_VERIFY if a floor is unverifiable)
        "floorReadOk":floor_read_ok,               # was the system-required CR floor read live?
        "collateralFlags":coll_flags,
        "collateralUnverifiable":coll_unverifiable, # exposed agents whose floor couldn't be verified (forces CANNOT_VERIFY)
        "markToMarket":{                           # LEG 1.5 — independent FTSOv2 USD valuation (additive cross-check)
            "available":ftso_ok,"stale":ftso_stale,"ftsoV2":ftso_v2_addr,"prices_usd":prices,
            "usdCollateral":round(mtm_usd_collateral,2),"usdObligation":round(mtm_usd_obligation,2),
            "usdMargin":round(mtm_usd_collateral-mtm_usd_obligation,2),
            "coverageRatio_pct":round(mtm_usd_collateral/mtm_usd_obligation*100,2) if mtm_usd_obligation>0 else None,
            "divergences":mtm_divergences},
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
