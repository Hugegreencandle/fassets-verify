#!/usr/bin/env python3
"""render_attestation — turn reserves.json (from fassets_verify.py) into a self-contained, point-in-time
public attestation page. Honest by construction: shows BOTH legs, the surplus, and the caveats/trust-model
prominently, pinned to the exact Flare block + XRPL ledger so anyone can re-derive it. No overclaim."""
import json, sys, html, datetime

DATA = json.load(open("reserves.json"))
GEN = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
pin = DATA["pinned"]

def esc(x): return html.escape(str(x))
def amt6(u):  # UBA / drops (6 decimals) -> human, thousands-separated
    return f"{int(u)/1_000_000:,.2f}"

VERDICT_COLOR = {"SOLVENT":"#0a7","BACKING_SHORTFALL":"#c33","UNDER_COLLATERALIZED":"#c33","CANNOT_VERIFY":"#a60"}

cards = []
for a in DATA["assets"]:
    v = a["verdict"]; col = VERDICT_COLOR.get(v, "#a60")
    supply = amt6(a["totalSupply"]); backing = amt6(a["realBacking"]); surplus = amt6(a["surplus"])
    surplus_pct = (int(a["surplus"]) / int(a["totalSupply"]) * 100) if int(a["totalSupply"]) else 0
    cv = a["coreVault"]; cv_liq = amt6(cv["liquid"] or 0)
    cv_esc = amt6(cv.get("escrow_to_custodian") or cv.get("escrow") or 0)   # renamed key; fall back for old json
    cv_cust = cv.get("custodian") or "—"; cv_cust_liq = amt6(cv.get("custodian_liquid") or 0)
    cv_excl = amt6(cv.get("escrow_excluded") or 0)
    rows = "".join(
        f"<tr><td class=mono>{esc(g['addr'])}</td><td>{esc(g['status'])}</td>"
        f"<td class=num>{g['vaultCR_pct']}%</td><td class=num>{g['poolCR_pct']}%</td>"
        f"<td class=num>{amt6(g['minted'])}</td><td class=num>{amt6(g['live']) if g['live'] is not None else '—'}</td>"
        f"<td class='{'ok' if g['collateral']=='HEALTHY' else 'bad'}'>{esc(g['collateral'])}</td></tr>"
        for g in a["agents"])
    caveats = "".join(f"<li>{esc(c)}</li>" for c in a.get("caveats", []))
    tm = a.get("trustModel", {})
    inf = a.get("inFlight", {})
    cards.append(f"""
    <section class=asset>
      <div class=verdict style="background:{col}">{esc(a['symbol'])} — {esc(v)}</div>
      <div class=legs>
        <div class=leg><h3>Leg 1 — Over-collateralization <span class=tag>Flare</span></h3>
          <p class=big>{esc(a['collateralVerdict'])}</p>
          <p class=sub>Read from the FAssets protocol's own AgentStatus (NORMAL / CCB / LIQUIDATION). {len(a['agents'])} agents, {len(a['collateralFlags'])} flagged.</p></div>
        <div class=leg><h3>Leg 2 — XRPL 1:1 backing <span class=tag>XRPL</span></h3>
          <p class=big>{esc(a['backingVerdict'])}</p>
          <p class=sub>Real XRP re-derived from raw XRPL (agents + Core Vault, incl. on-ledger escrow). No indexer, no oracle.</p></div>
      </div>
      <table class=nums>
        <tr><td>FXRP supply</td><td class=num>{supply}</td></tr>
        <tr><td>Real XRPL backing</td><td class=num>{backing}</td></tr>
        <tr><td>Surplus</td><td class=num>{surplus} ({surplus_pct:.3f}%)</td></tr>
        <tr><td>Core Vault liquid</td><td class=num>{cv_liq}</td></tr>
        <tr><td>Core Vault escrow → custodian <span class=mono>{esc(cv_cust)}</span> (condition-gated)</td><td class=num>{cv_esc}</td></tr>
        <tr><td>Custodian own balance (finished-escrow landing)</td><td class=num>{cv_cust_liq}</td></tr>
        <tr><td>Escrow excluded (pays elsewhere, not counted)</td><td class=num>{cv_excl}</td></tr>
        <tr><td>In-flight (reserved / redeeming, not netted)</td><td class=num>{amt6(inf.get('reservedUBA',0))} / {amt6(inf.get('redeemingUBA',0))}</td></tr>
      </table>
      <details open><summary>Per-agent (collateral + backing)</summary>
        <table class=agents><tr><th>XRPL underlying addr</th><th>Status</th><th>Vault CR</th><th>Pool CR</th><th>Minted</th><th>Live XRP</th><th>Collateral</th></tr>{rows}</table>
      </details>
      <div class=honest>
        <h3>What this does and does not mean</h3>
        <p><b>Provable with no trust beyond the ledgers:</b> {esc(tm.get('provable_trustlessly',''))}</p>
        <p><b>Conditional on named trust:</b> {esc(tm.get('conditional_trust',''))}</p>
        <p><b>Not claimed:</b> {esc(tm.get('not_claimed',''))}</p>
        <details><summary>Caveats ({len(a.get('caveats',[]))})</summary><ul>{caveats}</ul></details>
      </div>
    </section>""")

DOC = f"""<!doctype html><meta charset=utf-8><title>FXRP Proof-of-Solvency — independent, by Kairo Vault</title>
<style>
:root{{color-scheme:light dark}}
body{{font:15px/1.5 -apple-system,system-ui,sans-serif;max-width:920px;margin:2rem auto;padding:0 1rem;color:#222;background:#fff}}
@media(prefers-color-scheme:dark){{body{{color:#ddd;background:#111}}.asset,.leg,.honest{{background:#1a1a1a;border-color:#333}}th{{background:#222}}}}
h1{{margin:0 0 .2rem}}.meta{{color:#888;font-size:13px;margin-bottom:1.5rem}}
.asset{{border:1px solid #e3e3e3;border-radius:12px;padding:1.2rem;margin:1rem 0;background:#fafafa}}
.verdict{{color:#fff;font-weight:700;font-size:1.3rem;padding:.5rem .9rem;border-radius:8px;display:inline-block;margin-bottom:1rem}}
.legs{{display:flex;gap:1rem;flex-wrap:wrap}}.leg{{flex:1;min-width:260px;border:1px solid #e3e3e3;border-radius:10px;padding:.8rem;background:#fff}}
.leg h3{{margin:.1rem 0 .4rem;font-size:1rem}}.big{{font-weight:700;font-size:1.1rem;margin:.2rem 0}}.sub{{color:#777;font-size:13px;margin:.2rem 0 0}}
.tag{{font-size:11px;background:#eee;color:#555;padding:.1rem .4rem;border-radius:4px;vertical-align:middle}}
table{{border-collapse:collapse;width:100%;margin:.8rem 0;font-size:13px}}td,th{{border:1px solid #e3e3e3;padding:.35rem .5rem;text-align:left}}
th{{background:#f0f0f0;font-weight:600}}.num,.nums td:last-child{{text-align:right;font-variant-numeric:tabular-nums}}.mono{{font-family:ui-monospace,monospace;font-size:12px}}
.ok{{color:#0a7;font-weight:600}}.bad{{color:#c33;font-weight:700}}
.honest{{border:1px solid #e3e3e3;border-radius:10px;padding:.8rem;background:#fff;margin-top:1rem}}.honest h3{{margin:.1rem 0 .5rem}}
details summary{{cursor:pointer;font-weight:600;margin:.5rem 0}}.overflow{{overflow-x:auto}}
footer{{color:#888;font-size:12px;margin-top:2rem;border-top:1px solid #e3e3e3;padding-top:1rem}}
</style>
<h1>FXRP — Independent Proof-of-Solvency</h1>
<div class=meta>Verified by <b>Kairo Vault</b> (independent, no affiliation with Flare or the FAssets agents) ·
generated {GEN} · pinned to <b>Flare block {esc(pin['flare_block'])}</b> / <b>XRPL ledger {esc(pin['xrpl_ledger'])}</b> ·
re-derivable: run <span class=mono>fassets_verify.py</span> at these heights and reproduce this exact result.</div>
<div class=overflow>{''.join(cards)}</div>
<footer>Independent verification, not a Flare product and not on Flare's settlement path. Both legs are re-derived from raw
Flare mainnet + XRPL data with no indexer, oracle, or dashboard trusted. Numbers are on-chain-checkable at the pinned heights.
This is a solvency snapshot (backing &ge; supply AND no agent in liquidation), not an audit of the FAssets contracts or of Flare's FDC.
&mdash; Kairo Vault, the independent verification layer.</footer>
"""
open("attestation.html","w").write(DOC)
print("wrote attestation.html ({} bytes) pinned Flare {} / XRPL {}".format(len(DOC), pin['flare_block'], pin['xrpl_ledger']))
