#!/usr/bin/env python3
"""render_attestation — turn reserves.json (from fassets_verify.py) into a self-contained, point-in-time
public attestation page. Honest by construction: shows BOTH legs, the surplus, and the caveats/trust-model
prominently, pinned to the exact Flare block + XRPL ledger so anyone can re-derive it. No overclaim.

BILINGUAL (EN / 日本語): every label + prose string is rendered in both languages; a toggle switches them.
Japanese-locale browsers default to 日本語 (Flare markets FXRP hard in Japan); everyone else gets English
(the hackathon judging language). Choice is persisted. Data values (numbers/addresses/verdict tokens) are
identical across languages — only the human text is localized. Dynamic verifier prose (trust model +
caveats) is translated via JA_MAP; any string without a JA entry falls back to English (honest, never a
mistranslation)."""
import json, sys, html, datetime

DATA = json.load(open("reserves.json"))
GEN = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
pin = DATA["pinned"]

def esc(x): return html.escape(str(x))
def amt6(u):  # UBA / drops (6 decimals) -> human, thousands-separated
    return f"{int(u)/1_000_000:,.2f}"

# --- i18n helper: emit both languages inline; CSS shows the active one -------------------------------
def L(en, ja):
    """A bilingual text run. EN shown by default; JA shown when body[data-lang=ja]. JA falls back to EN
    if not translated (pass ja=None)."""
    ja = en if ja is None else ja
    return f'<span class="l-en">{en}</span><span class="l-ja">{ja}</span>'

# JA glosses for the status/verdict enums (English token kept authoritative, JA added in parentheses)
JA_VERDICT = {
    "SOLVENT": "支払能力あり", "PROVEN": "証明済み", "OVER_COLLATERALIZED": "過剰担保",
    "HEALTHY": "健全", "BACKING_SHORTFALL": "裏付け不足", "UNDER_COLLATERALIZED": "担保不足",
    "CANNOT_VERIFY": "検証不能", "NORMAL": "正常",
}
def verdict_L(v):
    g = JA_VERDICT.get(v)
    return L(esc(v), f"{esc(v)}（{g}）" if g else esc(v))

# JA translations for the DYNAMIC verifier prose (keyed by the exact EN string; EN fallback if missing)
JA_MAP = {
  # trust model
  "XRPL 1:1 backing (agent + Core-Vault balances incl. on-ledger escrow, re-derived from raw XRPL, no indexer/oracle) and agent over-collateralization status (read from Flare mainnet).":
    "XRPL 1:1 裏付け（エージェント + コアボールト残高、オンレジャー・エスクロー含む。生のXRPLから再導出、インデクサー/オラクル不使用）およびエージェントの過剰担保状態（Flareメインネットから読み取り）。",
  "not_claimed_generic":  # placeholder key never matched; real ones below
    "",
}
# trust-model + caveat strings resolved at runtime from reserves.json (exact-match into JA_MAP)
JA_MAP.update({
  "FDC attestation set (mint proofs); and the named on-chain custodian (rMLNvZR9dascY5jtCfCv3whAp8HdUSZAQ) that the Core-Vault escrows pay to and that holds finished-escrow XRP — its holding is verified on-ledger, its honesty is trusted.":
    "FDCアテステーション・セット（発行証明）、およびコアボールトのエスクローが支払い先とし、完了エスクローのXRPを保持する指定オンチェーン・カストディアン（rMLNvZR9dascY5jtCfCv3whAp8HdUSZAQ）。その保有はオンレジャーで検証済みだが、その誠実性は信頼に依存する。",
  "That FXRP is safe from every economic risk; this is a solvency snapshot (backing >= supply AND no agent in liquidation), not an audit of the FAssets contracts or FDC.":
    "FXRPがあらゆる経済的リスクから安全であること。これは支払能力のスナップショット（裏付け ≥ 供給 かつ 清算中エージェントなし）であり、FAssetsコントラクトやFDCの監査ではない。",
  "POINT-IN-TIME: verdict is pinned to the block/ledger above and decays the next ledger; re-run for a current view.":
    "時点固定：判定は上記のブロック/レジャーに固定され、次のレジャーで陳腐化する。現在の状況は再実行のこと。",
  "IN-FLIGHT NOT NETTED: reserved=0 + redeeming=0 UBA are in 14-day mint/redeem windows; the backing check compares live XRPL balance vs total FXRP supply without netting these (conservative but not exact).":
    "処理中はネッティングなし：予約=0 + 償還=0 UBA は14日間の発行/償還ウィンドウ内。裏付けチェックはこれらをネッティングせず、実XRPL残高とFXRP総供給を比較する（保守的だが厳密ではない）。",
  "CORE-VAULT ESCROW: 140000000000000 UBA of Core-Vault backing is in XRPL Escrows — CONDITION-GATED (crypto-condition + CancelAfter, not a simple time-lock) and verified to pay ONLY the on-chain custodian rMLNvZR9dascY5jtCfCv3whAp8HdUSZAQ. Escrows paying elsewhere (0 UBA) are EXCLUDED from backing. The custodian's own balance is included, so a FINISHED escrow stays counted. The custodian is a named, trusted holder — this binds the claim to its on-chain identity, it does not make custody trustless.":
    "コアボールト・エスクロー：コアボールト裏付けのうち 140000000000000 UBA はXRPLエスクロー内 — 条件付き（crypto-condition + CancelAfter、単純なタイムロックではない）で、オンチェーン・カストディアン rMLNvZR9dascY5jtCfCv3whAp8HdUSZAQ のみへの支払いを検証済み。他所宛てのエスクロー（0 UBA）は裏付けから除外。カストディアン自身の残高は含めるため、完了したエスクローも計上され続ける。カストディアンは指定された信頼される保持者であり、これは主張をそのオンチェーン識別子に結び付けるが、カストディを無信頼にするものではない。",
  "FDC TRUST: the mint side of FAssets trusts Flare's FDC attestation set for XRPL->Flare proofs; this tool re-derives balances directly from XRPL and does NOT re-verify FDC's attestations.":
    "FDC信頼：FAssetsの発行側はXRPL→Flareの証明についてFlareのFDCアテステーション・セットを信頼する。本ツールは残高をXRPLから直接再導出し、FDCのアテステーションを再検証はしない。",
  "CR FLOOR: LEG 1 flags an agent if its live collateral ratio is BELOW the system-required floor (getCollateralTypes minCollateralRatioBIPS: pool 150% / vault 120%) OR the protocol's AgentStatus is non-NORMAL. The floor check is what catches a below-floor agent that liquidation has NOT yet been triggered against (FAssets liquidation is permissionless/trigger-driven, so status alone is not sufficient).":
    "CRフロア：レッグ1は、エージェントの実担保比率がシステム要求フロア（getCollateralTypes minCollateralRatioBIPS：プール150% / ボールト120%）を下回るか、プロトコルのAgentStatusがNORMAL以外の場合にフラグを立てる。このフロアチェックは、清算がまだトリガーされていないフロア割れエージェントを捕捉する（FAssetsの清算はパーミッションレス/トリガー駆動のため、状態だけでは不十分）。",
  "AGENT SET: enumerated via getAllAgents(0,1000); if the system ever exceeds 1000 agents this must paginate (currently 6 agents).":
    "エージェント集合：getAllAgents(0,1000) で列挙。システムが1000エージェントを超えた場合はページングが必要（現在6エージェント）。",
})
def tr(s):  # translate a dynamic verifier string (EN fallback if not in JA_MAP)
    return L(esc(s), esc(JA_MAP.get(s, s)))

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
    caveats = "".join(f"<li>{tr(c)}</li>" for c in a.get("caveats", []))
    tm = a.get("trustModel", {})
    inf = a.get("inFlight", {})
    na = len(a['agents']); nf = len(a['collateralFlags'])
    cards.append(f"""
    <section class=asset>
      <div class=verdict style="background:{col}">{esc(a['symbol'])} — {verdict_L(v)}</div>
      <div class=legs>
        <div class=leg><h3>{L('Leg 1 — Over-collateralization','レッグ1 — 過剰担保')} <span class=tag>Flare</span></h3>
          <p class=big>{verdict_L(a['collateralVerdict'])}</p>
          <p class=sub>{L(f"Read from the FAssets protocol's own AgentStatus (NORMAL / CCB / LIQUIDATION). {na} agents, {nf} flagged.", f"FAssetsプロトコル自身のAgentStatus（NORMAL / CCB / LIQUIDATION）から読み取り。エージェント {na} 件、フラグ {nf} 件。")}</p></div>
        <div class=leg><h3>{L('Leg 2 — XRPL 1:1 backing','レッグ2 — XRPL 1:1 裏付け')} <span class=tag>XRPL</span></h3>
          <p class=big>{verdict_L(a['backingVerdict'])}</p>
          <p class=sub>{L('Real XRP re-derived from raw XRPL (agents + Core Vault, incl. on-ledger escrow). No indexer, no oracle.','生のXRPLデータから再導出した実XRP（エージェント + コアボールト、オンレジャー・エスクロー含む）。インデクサーもオラクルも不使用。')}</p></div>
      </div>
      <table class=nums>
        <tr><td>{L('FXRP supply','FXRP 供給量')}</td><td class=num>{supply}</td></tr>
        <tr><td>{L('Real XRPL backing','実XRPL裏付け')}</td><td class=num>{backing}</td></tr>
        <tr><td>{L('Surplus','余剰')}</td><td class=num>{surplus} ({surplus_pct:.3f}%)</td></tr>
        <tr><td>{L('Core Vault liquid','コアボールト流動分')}</td><td class=num>{cv_liq}</td></tr>
        <tr><td>{L('Core Vault escrow → custodian','コアボールト・エスクロー → カストディアン')} <span class=mono>{esc(cv_cust)}</span> {L('(condition-gated)','（条件付き）')}</td><td class=num>{cv_esc}</td></tr>
        <tr><td>{L('Custodian own balance (finished-escrow landing)','カストディアン自身の残高（完了エスクローの着地先）')}</td><td class=num>{cv_cust_liq}</td></tr>
        <tr><td>{L('Escrow excluded (pays elsewhere, not counted)','除外エスクロー（他所宛て、非計上）')}</td><td class=num>{cv_excl}</td></tr>
        <tr><td>{L('In-flight (reserved / redeeming, not netted)','処理中（予約 / 償還、ネッティングなし）')}</td><td class=num>{amt6(inf.get('reservedUBA',0))} / {amt6(inf.get('redeemingUBA',0))}</td></tr>
      </table>
      <details open><summary>{L('Per-agent (collateral + backing)','エージェント別（担保 + 裏付け）')}</summary>
        <table class=agents><tr><th>{L('XRPL underlying addr','XRPL原資産アドレス')}</th><th>{L('Status','状態')}</th><th>{L('Vault CR','ボールトCR')}</th><th>{L('Pool CR','プールCR')}</th><th>{L('Minted','発行量')}</th><th>{L('Live XRP','実XRP')}</th><th>{L('Collateral','担保')}</th></tr>{rows}</table>
      </details>
      <div class=honest>
        <h3>{L('What this does and does not mean','本証明が意味すること・しないこと')}</h3>
        <p><b>{L('Provable with no trust beyond the ledgers:','レジャー以外の信頼を要さず証明可能：')}</b> {tr(tm.get('provable_trustlessly',''))}</p>
        <p><b>{L('Conditional on named trust:','指定された信頼を前提とする：')}</b> {tr(tm.get('conditional_trust',''))}</p>
        <p><b>{L('Not claimed:','主張しないこと：')}</b> {tr(tm.get('not_claimed',''))}</p>
        <details><summary>{L(f"Caveats ({len(a.get('caveats',[]))})", f"留意事項（{len(a.get('caveats',[]))}）")}</summary><ul>{caveats}</ul></details>
      </div>
    </section>""")

TOGGLE_JS = """
(function(){
  function setLang(l){
    document.body.dataset.lang = l;
    document.documentElement.lang = l;
    try{ localStorage.setItem('kvt-lang', l); }catch(e){}
    var b = document.querySelectorAll('.langbtn');
    for(var i=0;i<b.length;i++){ b[i].classList.toggle('active', b[i].getAttribute('data-set-lang')===l); }
  }
  var url = new URL(window.location.href);
  var q = url.searchParams.get('lang');
  var stored = null; try{ stored = localStorage.getItem('kvt-lang'); }catch(e){}
  var nav = (navigator.language||'').toLowerCase().slice(0,2)==='ja' ? 'ja' : 'en';
  var b = document.querySelectorAll('.langbtn');
  for(var i=0;i<b.length;i++){ (function(btn){ btn.addEventListener('click', function(){ setLang(btn.getAttribute('data-set-lang')); }); })(b[i]); }
  setLang((q==='ja'||q==='en') ? q : (stored || nav));
})();
"""

DOC = f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>FXRP 支払能力の独立検証 | FXRP Proof-of-Solvency — Kairo Vault</title>
<style>
:root{{color-scheme:light dark}}
body{{font:15px/1.5 -apple-system,system-ui,"Hiragino Kaku Gothic ProN","Yu Gothic",Meiryo,sans-serif;max-width:920px;margin:2rem auto;padding:0 1rem;color:#222;background:#fff}}
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
.langbar{{float:right;display:flex;gap:.3rem}}.langbtn{{font:600 12px/1 inherit;padding:.35rem .7rem;border:1px solid #ccc;border-radius:6px;background:#fff;color:#555;cursor:pointer}}
.langbtn.active{{background:#0a7;color:#fff;border-color:#0a7}}
.l-ja{{display:none}}
body[data-lang="ja"] .l-en{{display:none}}
body[data-lang="ja"] .l-ja{{display:inline}}
/* dark mode LAST so it overrides the light card/label colors above (source-order wins) */
@media(prefers-color-scheme:dark){{
  body{{color:#ececec;background:#111}}
  .asset{{background:#141414}}.leg,.honest{{background:#1b1b1b}}
  .asset,.leg,.honest{{border-color:#3a3a3a}}
  h1,.leg h3,.big,.honest h3,summary{{color:#fff}}
  .meta{{color:#a8a8a8}}.sub{{color:#b4c0cf}}
  td,th{{border-color:#3a3a3a}}th{{background:#242424}}
  .num,.nums td,.agents td{{color:#ececec}}
  .tag{{background:#333;color:#ddd}}
  .langbtn{{background:#1a1a1a;color:#cfcfcf;border-color:#3a3a3a}}
}}
</style></head><body data-lang=en>
<div class=langbar><button class=langbtn data-set-lang=en>EN</button><button class=langbtn data-set-lang=ja>日本語</button></div>
<h1>{L('FXRP — Independent Proof-of-Solvency','FXRP — 独立した支払能力の証明')}</h1>
<div class=meta>{L('Verified by','検証者：')} <b>Kairo Vault</b> {L('(independent, no affiliation with Flare or the FAssets agents)','（独立機関、FlareおよびFAssetsエージェントとは無関係）')} ·
{L('generated','生成')} {GEN} · {L('pinned to','固定：')} <b>{L('Flare block','Flareブロック')} {esc(pin['flare_block'])}</b> / <b>{L('XRPL ledger','XRPL レジャー')} {esc(pin['xrpl_ledger'])}</b> ·
{L('re-derivable: run','再現可能：')} <span class=mono>fassets_verify.py</span> {L('at these heights and reproduce this exact result.','をこれらの高さで実行すれば、この結果を完全に再現できます。')}</div>
<div class=overflow>{''.join(cards)}</div>
<footer>{L('Independent verification, not a Flare product and not on the Flare settlement path. Both legs are re-derived from raw Flare mainnet + XRPL data with no indexer, oracle, or dashboard trusted. Numbers are on-chain-checkable at the pinned heights. This is a solvency snapshot (backing &ge; supply AND no agent in liquidation), not an audit of the FAssets contracts or of the Flare FDC. &mdash; Kairo Vault, the independent verification layer.','独立した検証であり、Flareの製品でも決済経路上のものでもありません。両レッグはインデクサー・オラクル・ダッシュボードを信頼せず、生のFlareメインネット + XRPLデータから再導出しています。数値は固定した高さでオンチェーン検証可能です。これは支払能力のスナップショット（裏付け &ge; 供給 かつ 清算中エージェントなし）であり、FAssetsコントラクトやFlareのFDCの監査ではありません。&mdash; Kairo Vault、独立した検証レイヤー。')}</footer>
<script>{TOGGLE_JS}</script>
</body></html>
"""
open("attestation.html","w").write(DOC)
print("wrote attestation.html ({} bytes, bilingual EN/JA) pinned Flare {} / XRPL {}".format(len(DOC), pin['flare_block'], pin['xrpl_ledger']))
