#!/usr/bin/env node
// anchor_verify.cjs — the round trip that makes the anchor real. Given a local signed attestation and an
// on-ledger tx hash, it: (1) fetches the Xahau tx, (2) decodes the anchor memo, (3) RE-DERIVES body_sha256
// from the local attestation's own body fields, (4) requires the on-ledger hash == the recomputed hash.
// CONSISTENT (exit 0) = the local proof matches what is frozen on-ledger. Mutate one byte of the body and
// the recomputed hash changes => DIVERGED (exit 2). Anyone can run this against just the tx hash + the
// public attestation json; it trusts the Xahau node only to return the tx (cross-check a 2nd node to remove that).
//
// Usage: node anchor_verify.cjs --json <signed.json> --tx <hash> --endpoint wss://xahau-test.net
const fs = require("node:fs");
const { XrplClient } = require("xrpl-client");
const C = require("./anchor_common.cjs");

function arg(name, def) { const i = process.argv.indexOf(name); return i > -1 ? process.argv[i + 1] : def; }
function fail(msg) { console.error("DIVERGED — " + msg); process.exit(2); }

(async () => {
  const jsonPath = arg("--json", "fxrp-solvency-attestation.KVT-signed.json");
  const txHash = arg("--tx");
  const endpoint = arg("--endpoint", "wss://xahau-test.net");
  if (!txHash) { console.error("ERROR: --tx <hash> required"); process.exit(3); }

  const signed = JSON.parse(fs.readFileSync(jsonPath, "utf8"));
  const localHash = C.recomputeBodySha(signed); // recomputed from the local file's body, not trusted from anchor field
  console.log("local body_sha256 (recomputed):", localHash);

  const client = new XrplClient(endpoint);
  await client.ready();
  try {
    const t = await client.send({ command: "tx", transaction: txHash });
    if (!t || t.error) fail("tx not found on ledger: " + (t && (t.error_message || t.error)));
    if (!t.validated) fail("tx not validated on ledger yet");
    const tr = t.meta && t.meta.TransactionResult;
    if (tr !== "tesSUCCESS") fail("anchor tx did not succeed on-ledger: " + tr);

    const memos = (t.Memos || []).map(m => m.Memo).filter(Boolean);
    let parsed = null;
    for (const m of memos) {
      if (!m.MemoData) continue;
      const p = C.parsePayload(C.hexDecode(m.MemoData));
      if (p) { parsed = p; break; }
    }
    if (!parsed) fail("no KVT-ATTEST memo found in tx " + txHash);
    console.log("on-ledger hash                :", parsed.hash, "| ledger", t.ledger_index);
    console.log("on-ledger kid                 :", parsed.kid, "| ctx", parsed.ctx);

    // the load-bearing checks
    if (parsed.hash !== localHash) fail(`on-ledger hash ${parsed.hash} != recomputed local hash ${localHash} — the attestation body was altered after anchoring`);
    if (parsed.kid !== signed.signature.kid) fail(`kid mismatch: on-ledger ${parsed.kid} != local ${signed.signature.kid}`);
    if (parsed.ctx !== signed.signature.ctx) fail(`ctx mismatch: on-ledger ${parsed.ctx} != local ${signed.signature.ctx}`);

    console.log(`\nCONSISTENT — the local attestation matches the hash frozen on Xahau at ledger ${t.ledger_index} (tx ${txHash}).`);
    console.log("Anyone re-deriving fassets_verify.py at the pinned heights reproduces this exact body, hence this hash.");
    process.exit(0);
  } finally {
    client.close();
  }
})().catch(e => { console.error("FATAL:", e.message); process.exit(1); });
