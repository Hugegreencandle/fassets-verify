#!/usr/bin/env python3
"""fxrp-verify — independent Proof-of-Reserves for Flare FAssets FXRP.
Re-derives "every FXRP is backed by real XRP" from raw Flare + XRPL public data, trusting no indexer/UI.
Backing = Σ agents' LIVE XRPL underlying balance + Core Vault (liquid Balance + on-ledger Escrow objects).
The Core Vault holds ~140M XRP in XRPL Escrow — a naive account-Balance check MISSES it and false-flags. We read the escrows.
Fail-closed: PROVEN / FLAGGED(under-backed) / CANNOT_VERIFY(missing data). Usage: fxrp_verify.py [--json]"""
import json, sys, urllib.request
from web3 import Web3
FLARE="https://flare-api.flare.network/ext/C/rpc"; XRPL="https://xrplcluster.com/"
AM="0x2a3Fe068cD92178554cabcf7c95ADf49B4B0B6A8"; FX="0xAd552A648C74D49E10027AB8a618A3ad4901c5bE"
w3=Web3(Web3.HTTPProvider(FLARE))
def xrpl(m,p):
    r=urllib.request.Request(XRPL, json.dumps({"method":m,"params":[p]}).encode(), {"Content-Type":"application/json"})
    return json.load(urllib.request.urlopen(r,timeout=30))["result"]
def xrp_backing(addr, lidx):
    """live XRP at an address = liquid Balance + Σ outgoing-Escrow amounts, at a pinned ledger. Returns drops or None (fail-closed)."""
    ai=xrpl("account_info",{"account":addr,"ledger_index":lidx})
    if "account_data" not in ai: return None
    liquid=int(ai["account_data"]["Balance"]); locked=0; marker=None
    while True:
        p={"account":addr,"type":"escrow","ledger_index":lidx,"limit":400}
        if marker: p["marker"]=marker
        r=xrpl("account_objects",p)
        if "account_objects" not in r: return None
        locked+=sum(int(o.get("Amount","0")) for o in r["account_objects"] if o.get("Account")==addr)  # only escrows we funded
        marker=r.get("marker")
        if not marker: break
    return liquid, locked
gai=json.load(open("agentinfo_abi.json")); comps=[c['name'] for c in gai[0]["outputs"][0]["components"]]
am=w3.eth.contract(address=Web3.to_checksum_address(AM), abi=gai+[
 {"inputs":[{"type":"uint256"},{"type":"uint256"}],"name":"getAllAgents","outputs":[{"type":"address[]"},{"type":"uint256"}],"stateMutability":"view","type":"function"},
 {"inputs":[],"name":"getCoreVaultManager","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"}])
flare_blk=w3.eth.block_number
xrpl_lidx=xrpl("ledger",{"ledger_index":"validated"})["ledger_index"]
supply=w3.eth.contract(address=Web3.to_checksum_address(FX),abi=[{"inputs":[],"name":"totalSupply","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"}]).functions.totalSupply().call(block_identifier=flare_blk)
agents,_=am.functions.getAllAgents(0,1000).call(block_identifier=flare_blk)
rep={"pinned":{"flare_block":flare_blk,"xrpl_ledger":xrpl_lidx},"fxrp_totalSupply_drops":supply,"agents":[],"core_vault":{},"verdict":None}
verdict="PROVEN"; total_backing=0
for a in agents:
    d=dict(zip(comps, am.functions.getAgentInfo(a).call(block_identifier=flare_blk)))
    xr=xrp_backing(d["underlyingAddressString"], xrpl_lidx)
    if xr is None: verdict="CANNOT_VERIFY"; live=None
    else: live=sum(xr); total_backing+=live
    rep["agents"].append({"vault":a,"xrpl":d["underlyingAddressString"],"mintedUBA":d["mintedUBA"],"requiredUBA":d["requiredUnderlyingBalanceUBA"],"live_xrp_drops":live})
CVM=am.functions.getCoreVaultManager().call(block_identifier=flare_blk)
cvaddr=w3.eth.contract(address=Web3.to_checksum_address(CVM),abi=[{"inputs":[],"name":"coreVaultAddress","outputs":[{"type":"string"}],"stateMutability":"view","type":"function"}]).functions.coreVaultAddress().call(block_identifier=flare_blk)
cvx=xrp_backing(cvaddr, xrpl_lidx)
if cvx is None: verdict="CANNOT_VERIFY"
else:
    total_backing+=sum(cvx); rep["core_vault"]={"xrpl":cvaddr,"liquid_drops":cvx[0],"escrow_drops":cvx[1]}
rep["total_real_xrp_drops"]=total_backing
if verdict!="CANNOT_VERIFY": verdict="PROVEN" if total_backing>=supply else "FLAGGED"
rep["verdict"]=verdict; rep["surplus_drops"]=total_backing-supply
if "--json" in sys.argv: print(json.dumps(rep,indent=2))
else:
    print(f"fxrp-verify @ Flare#{flare_blk} / XRPL#{xrpl_lidx}")
    for a in rep["agents"]: print(f"  agent {a['vault'][:8]} {a['xrpl']}: live={a['live_xrp_drops']/1e6 if a['live_xrp_drops'] else '?':,.2f} XRP (minted {a['mintedUBA']/1e6:,.2f})")
    cv=rep["core_vault"]; print(f"  CORE VAULT {cv['xrpl']}: liquid {cv['liquid_drops']/1e6:,.2f} + escrow {cv['escrow_drops']/1e6:,.2f} XRP")
    print(f"\n  FXRP supply = {supply/1e6:,.2f}  |  real XRP backing = {total_backing/1e6:,.2f}  |  surplus {(total_backing-supply)/1e6:+,.2f}")
    print(f"  ===== VERDICT: {verdict} =====")
