// anchor_common.cjs — shared logic for anchoring a KVT attestation's body_sha256 to Xahau (mode 1a, direct).
// The memo binds the attestation's content hash + attester kid to an on-ledger, timestamped tx. Verifying
// RE-DERIVES body_sha256 from the signed json (so a mutated body no longer matches the on-ledger memo).
// canon() is byte-identical to sign_attestation.mjs — the hash must reproduce exactly or the teeth are fake.
const { createHash } = require("node:crypto");

// deterministic canonical JSON (sorted keys) — MUST match sign_attestation.mjs exactly
const canon = (o) => o === null || typeof o !== "object" ? JSON.stringify(o)
  : Array.isArray(o) ? "[" + o.map(canon).join(",") + "]"
  : "{" + Object.keys(o).sort().map(k => JSON.stringify(k) + ":" + canon(o[k])).join(",") + "}";
const sha256 = (s) => "sha256:" + createHash("sha256").update(s).digest("hex");

// The exact key set sign_attestation.mjs put in `body` (the hashed subset). Anything outside this
// (verifier/environment/anchor/signature/attested_at) is NOT part of the hash.
// MUST stay identical to the `body` object in sign_attestation.mjs — canon() over exactly these keys
// reproduces body_sha256. If you add/remove a signed-body field there, mirror it here.
const BODY_KEYS = ["attestation_schema", "asset", "networks", "verdict", "backing_verdict",
  "collateral_verdict", "total_supply_uba", "real_backing_uba", "net_backing_uba", "surplus_uba",
  "floor_read_ok", "core_vault", "agents", "collateral_flags", "collateral_unverifiable", "in_flight",
  "method", "trust_model"];

function reconstructBody(signed) {
  const body = {};
  for (const k of BODY_KEYS) {
    if (!(k in signed)) throw new Error(`signed attestation missing body key: ${k}`);
    body[k] = signed[k];
  }
  return body;
}

// recompute body_sha256 from the signed json's own body fields (does NOT trust the stored anchor.body_sha256)
function recomputeBodySha(signed) { return sha256(canon(reconstructBody(signed))); }

const TAG = "KVT-ATTEST/1"; // memo type tag; binds the payload to this scheme

function buildPayload(signed) {
  const ctx = signed.signature.ctx;      // e.g. por.fxrp.solvency.v1
  const kid = signed.signature.kid;      // kvt-attester-1:...
  const hash = recomputeBodySha(signed); // recomputed, not trusted from the file
  return `${TAG}:${ctx}:${hash}:${kid}`;
}

// parse an on-ledger MemoData payload back to its fields (tag-checked). null if not our scheme.
function parsePayload(s) {
  // split into exactly 4 fields but the hash contains a ':' ("sha256:hex") — rejoin the middle
  const first = s.indexOf(":");
  const tag = s.slice(0, first);
  if (tag !== TAG) return null;
  const rest = s.slice(first + 1);
  const ctxEnd = rest.indexOf(":");
  const ctx = rest.slice(0, ctxEnd);
  const afterCtx = rest.slice(ctxEnd + 1);
  // hash = "sha256:<hex>"; kid follows after the hex. kid starts at the NEXT ':' after the hex.
  const m = afterCtx.match(/^(sha256:[0-9a-f]+):(.+)$/);
  if (!m) return null;
  return { tag, ctx, hash: m[1], kid: m[2] };
}

const hexEncode = (s) => Buffer.from(s, "utf8").toString("hex").toUpperCase();
const hexDecode = (h) => Buffer.from(h, "hex").toString("utf8");

module.exports = { canon, sha256, reconstructBody, recomputeBodySha, TAG, buildPayload, parsePayload, hexEncode, hexDecode };
