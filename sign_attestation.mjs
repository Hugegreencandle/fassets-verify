// sign_attestation.mjs — turn a reserves.json verdict into a KVT-signed, anchor-ready attestation.
// Ed25519 over a DOMAIN-SEPARATED envelope (so an FXRP-solvency signature can never be replayed as some
// other KVT attestation type). Produces: the canonical body, its sha256 (the value anchored on Xahau),
// and the base64 signature + kid. The private key is used but never printed.
import { readFileSync, writeFileSync } from "node:fs";
import { createPrivateKey, sign as edSign, createHash } from "node:crypto";
import os from "node:os";

// deterministic canonical JSON (sorted keys) — identical to the everagents attest algebra
const canon = (o) => o === null || typeof o !== "object" ? JSON.stringify(o)
  : Array.isArray(o) ? "[" + o.map(canon).join(",") + "]"
  : "{" + Object.keys(o).sort().map(k => JSON.stringify(k) + ":" + canon(o[k])).join(",") + "}";
const sha256 = (s) => "sha256:" + createHash("sha256").update(s).digest("hex");

const KID = "kvt-attester-1:82187d3e78386990";
const KEY = process.env.KVT_ATTESTER_PEM || (os.homedir() + "/.kvt-attester/kvt-attester-ed25519.pem");
const DOMAIN = "kvt.attestation.v1";       // envelope tag
const CTX = "por.fxrp.solvency.v1";        // context (this attestation type)
const NET = "flare-mainnet+xrpl-mainnet";  // the two chains re-derived

const R = JSON.parse(readFileSync("reserves.json"));
const a = R.assets[0];

// The BODY = the load-bearing solvency claim, pinned to both chains. This is what gets hashed + anchored.
const body = {
  attestation_schema: "kvt.fxrp-solvency-attestation.v1",
  asset: a.symbol,
  networks: { flare_block: R.pinned.flare_block, xrpl_ledger: R.pinned.xrpl_ledger },
  verdict: a.verdict,                    // SOLVENT / UNDER_COLLATERALIZED / BACKING_SHORTFALL / CANNOT_VERIFY
  backing_verdict: a.backingVerdict,     // LEG 2 (XRPL 1:1 backing)
  collateral_verdict: a.collateralVerdict, // LEG 1 (Flare over-collateralization)
  total_supply_uba: String(a.totalSupply),
  real_backing_uba: String(a.realBacking),
  net_backing_uba: String(a.netBacking ?? a.realBacking),   // backing net of redeeming (the solvency-comparison figure)
  surplus_uba: String(a.surplus),
  floor_read_ok: a.floorReadOk,                             // false => LEG 1 unverifiable => verdict CANNOT_VERIFY (never signed as SOLVENT blind)
  core_vault: { addr: a.coreVault.addr, liquid_drops: String(a.coreVault.liquid), escrow_drops: String(a.coreVault.escrow_to_custodian ?? a.coreVault.escrow) },
  agents: a.agents.length,
  collateral_flags: a.collateralFlags.length,
  collateral_unverifiable: (a.collateralUnverifiable || []).length,
  in_flight: a.inFlight,
  method: "dual-leg re-derivation from raw Flare mainnet + XRPL; no indexer, oracle, or dashboard trusted",
  trust_model: a.trustModel,
};
const body_sha256 = sha256(canon(body));   // <-- the value anchored on Xahau (immutable, timestamped claim)

// domain-separated message actually signed
const message = [DOMAIN, CTX, NET, canon(body)].join("\n");
const priv = createPrivateKey(readFileSync(KEY));
const signature = edSign(null, Buffer.from(message, "utf8"), priv).toString("base64");

const out = {
  ...body,
  verifier: { name: "Dane Brown", organization: "Kairo Vault Technologies (G.K.)", role: "Independent Verifier" },
  environment: `${os.type()} ${os.release()}, ${os.arch()}; Node ${process.version}. Re-derived from live Flare + XRPL RPC at the pinned heights; no privileged access.`,
  anchor: { body_sha256, chain: "xahau", memo_hint: "anchor body_sha256 + kid in a Xahau memo/Hook tx from the KVT attester account" },
  signature: { alg: "Ed25519", domain: DOMAIN, ctx: CTX, net: NET, kid: KID, sig_b64: signature },
  attested_at: new Date().toISOString(),
};
writeFileSync("fxrp-solvency-attestation.KVT-signed.json", JSON.stringify(out, null, 1));
console.log("verdict:", body.verdict, "| backing:", body.backing_verdict, "| collateral:", body.collateral_verdict);
console.log("anchor body_sha256:", body_sha256);
console.log("signature (Ed25519, kid " + KID + "):", signature.slice(0, 32) + "...");
console.log("wrote fxrp-solvency-attestation.KVT-signed.json");
