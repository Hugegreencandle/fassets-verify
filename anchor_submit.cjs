#!/usr/bin/env node
// anchor_submit.cjs — MODE 1a: anchor a KVT attestation's body_sha256 to Xahau in one tx.
// Builds a self-payment carrying a memo `KVT-ATTEST/1:<ctx>:<body_sha256>:<kid>`, signs it with the
// Xahau ANCHOR ACCOUNT key (separate from the Ed25519 attester key that signed the verdict), submits it,
// waits for validation, and records tx_hash + ledger_seq. Refuses to anchor a file whose recomputed
// body_sha256 does not match its own stored anchor (never anchor a tampered attestation).
//
// Usage: node anchor_submit.cjs --json <signed.json> --secret <familySeed> --endpoint wss://xahau-test.net --network 21338
const fs = require("node:fs");
const lib = require("xrpl-accountlib");
const { XrplClient } = require("xrpl-client");
const C = require("./anchor_common.cjs");

function arg(name, def) { const i = process.argv.indexOf(name); return i > -1 ? process.argv[i + 1] : def; }

(async () => {
  const jsonPath = arg("--json", "fxrp-solvency-attestation.KVT-signed.json");
  const secret = arg("--secret");
  const endpoint = arg("--endpoint", "wss://xahau-test.net");
  const network = parseInt(arg("--network", "21338"), 10); // 21338 testnet / 21337 mainnet
  if (!secret) { console.error("ERROR: --secret <familySeed> required (the Xahau anchor account key)"); process.exit(3); }

  const signed = JSON.parse(fs.readFileSync(jsonPath, "utf8"));

  // 1) integrity gate: recompute body_sha256 from the file's own body; must equal its stored anchor.
  const recomputed = C.recomputeBodySha(signed);
  const stored = signed.anchor && signed.anchor.body_sha256;
  if (recomputed !== stored) {
    console.error(`REFUSING TO ANCHOR: recomputed body_sha256 ${recomputed} != stored ${stored} (tampered file?)`);
    process.exit(2);
  }
  const payload = C.buildPayload(signed);
  console.log("payload   :", payload);

  const account = lib.derive.familySeed(secret);
  const address = account.address;
  console.log("anchor acct:", address, "| network:", network, "| endpoint:", endpoint);

  const client = new XrplClient(endpoint);
  await client.ready();
  try {
    const sd = await client.send({ command: "server_definitions" });
    const DEFS = new lib.XrplDefinitions(sd);
    const ai = await client.send({ command: "account_info", account: address, ledger_index: "validated" });
    if (!ai.account_data) throw new Error("account not found / not funded: " + JSON.stringify(ai.error_message || ai));
    const seq = ai.account_data.Sequence;
    const cur = await client.send({ command: "ledger_current" });
    const lastLedger = cur.ledger_current_index + 20;

    const tx = {
      TransactionType: "AccountSet",  // no-op AccountSet as a pure memo carrier (self-payment is temREDUNDANT)
      Account: address,
      NetworkID: network,             // Xahau requires NetworkID
      Fee: "5000",
      Sequence: seq,
      LastLedgerSequence: lastLedger,
      Memos: [{ Memo: { MemoType: C.hexEncode(C.TAG), MemoData: C.hexEncode(payload) } }],
    };

    const signedTx = lib.sign(tx, account, DEFS);
    const res = await client.send({ command: "submit", tx_blob: signedTx.signedTransaction });
    console.log("engine    :", res.engine_result, "-", res.engine_result_message);
    const hash = (res.tx_json && res.tx_json.hash) || signedTx.id;
    console.log("tx_hash   :", hash);

    // wait for validation (poll tx up to ~30s)
    let validated = null;
    for (let i = 0; i < 15; i++) {
      await new Promise(r => setTimeout(r, 2000));
      const t = await client.send({ command: "tx", transaction: hash });
      if (t && t.validated) { validated = t; break; }
    }
    if (!validated) { console.error("NOT VALIDATED within timeout (engine_result was " + res.engine_result + ")"); process.exit(2); }
    console.log("validated : ledger", validated.ledger_index, "| result", validated.meta && validated.meta.TransactionResult);

    const record = {
      tag: C.TAG, ctx: signed.signature.ctx, kid: signed.signature.kid,
      body_sha256: recomputed, payload,
      tx_hash: hash, ledger_seq: validated.ledger_index, network, endpoint,
      account: address, submitted_at: new Date().toISOString(),
    };
    fs.writeFileSync("anchor-record.json", JSON.stringify(record, null, 1));
    console.log("wrote anchor-record.json");
    console.log("\nANCHORED. Verify with: node anchor_verify.cjs --json " + jsonPath + " --tx " + hash + " --endpoint " + endpoint);
  } finally {
    client.close();
  }
})().catch(e => { console.error("FATAL:", e.message); process.exit(1); });
