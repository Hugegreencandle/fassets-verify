# fassets-verify — Independent Proof-of-Solvency for Flare FAssets (FXRP)

**Flare Summer Signal — Interoperable Asset Products.** By Kairo Vault Technologies (合同会社), an
independent verification company. Unaffiliated with Flare or the FAssets agents.

**▶ Live dashboard: https://hugegreencandle.github.io/fassets-verify/** — re-derived from live Flare +
XRPL every 6 hours, pinned to the exact block/ledger, re-checkable by anyone.

A trustless, reproducible re-checker that re-derives whether **FXRP is fully solvent** from **raw Flare
mainnet + XRP Ledger public data** — trusting no indexer, no dashboard, and no protocol self-report. It
spans both chains an interoperable asset actually lives on: the wrapper accounting on **Flare**, the real
reserves on **XRPL**. Read the ledgers yourself; verify the peg yourself.

Auto-discovers every live FAsset via `AssetManagerController.getAssetManagers()` — FXRP today, FBTC/FDOGE
the moment they launch.

## The two legs (SOLVENT requires both)

FXRP solvency has two independent conditions, on two chains. Most tools check at most one.

**LEG 1 — Over-collateralization (Flare side).** Every FAsset agent must hold collateral above the
liquidation floor. We read each agent's status from the FAssets protocol's **own liquidation state
machine** (`AgentStatus`: NORMAL / CCB / LIQUIDATION) plus its live vault/pool collateral ratios — the
authoritative signal, no guessed thresholds.

**LEG 2 — 1:1 underlying backing (XRPL side — the scarce skill).** The circulating FXRP must be backed by
real XRP locked on the XRP Ledger. We bind `FXRP.totalSupply()` (Flare) to the **actual XRP** at each
agent's XRPL address **and** the Core Vault — including its **on-ledger Escrow objects**. The Core-Vault
escrows are **verified to pay the on-chain `custodianAddress()`** (not just counted by sender), any that
pay elsewhere are **excluded**, and the custodian's own balance is included so a *finished* escrow stays
counted — the escrow→custodian transition is backing-neutral. LEG 1 flags any agent **below the
system-required collateral floor** (`getCollateralTypes`: pool 150% / vault 120%) even before the protocol
triggers liquidation.

```
verdict = SOLVENT  ⟺  (no agent flagged by the protocol)  AND  (real XRPL backing ≥ FXRP supply)
```
Fail-closed: `SOLVENT` / `UNDER_COLLATERALIZED` / `BACKING_SHORTFALL` / `CANNOT_VERIFY` — never a false "safe."

## The headline finding: the obvious reserve check is *wrong* here

~99% of FXRP backing sits behind the v1.1 **Core Vault**, which holds **~140M XRP in XRPL Escrow objects**
that do **not** count toward the account `Balance`. A naive proof-of-reserves reads the ~10M liquid
balance, sees ~150M of supply, and **falsely screams "140M under-backed."** `fassets-verify` reads the
real Escrow objects and reconciles the full picture. Reading the XRPL side correctly is the differentiator
— Flare is EVM-native; XRPL depth is rare there.

**Live result (mainnet):** FXRP ~151.7M supply; real XRP backing ~151.8M across 6 agents (all NORMAL, CR
181–648%) + Core Vault (~9.5M liquid + 140M escrow) → **SOLVENT**, ~0.07% surplus. Pinned to one Flare
block + one XRPL ledger; re-run at those heights and reproduce it exactly.

## Honesty is a feature (the trust model ships in the output)

Every verdict carries its assumptions — no green check without its scope:
- **Provable with no trust beyond the ledgers:** the XRPL backing (agents + Core Vault incl. escrow,
  re-derived from raw XRPL) and agent over-collateralization (from Flare mainnet).
- **Conditional on named trust:** Flare's FDC attestation set (mint proofs); the release schedule of the
  time-locked Core-Vault escrow.
- **Not claimed:** that FXRP is safe from every economic risk. This is a solvency snapshot, not an audit
  of the FAssets contracts or of FDC.

Plus honest caveats in the output: point-in-time decay, in-flight mint/redeem not netted, escrow-ladder
unverified, agent-set pagination. We never launder an unverifiable claim into a PASS.

## It has teeth (it flags the bad cases, not just green-lights)

`negative_test.py` proves the verifier discriminates: 7 unit cases + 4 **live-mutations of the real
FXRP data** — drop backing 1 UBA below supply, flag one agent into liquidation, or fail an XRPL read, and
the verdict flips off SOLVENT every time (11/11 PASS). The verifier and the test share one verdict
definition (`fassets_lib.combine_verdict`) so they can't diverge.

## Signed, anchor-ready attestation

`sign_attestation.mjs` turns the verdict into an **Ed25519-signed** attestation over a domain-separated
envelope (KVT attester `kid kvt-attester-1`), emitting `body_sha256` — the immutable value to anchor
on-chain. `render_attestation.py` produces a self-contained public attestation page (both legs, surplus,
per-agent CR table, Core-Vault escrow breakdown, caveats), pinned to the block/ledger.

## Anchor the verdict to Xahau (tamper-evident, cross-chain)

The signed attestation's `body_sha256` can be **frozen on Xahau** so a verdict can't be quietly
restated later. `anchor_submit.cjs` writes `KVT-ATTEST/1:<ctx>:<body_sha256>:<kid>` into a Xahau tx
memo; `anchor_verify.cjs` re-fetches it, **re-derives** `body_sha256` from the attestation's own body
fields, and requires the on-ledger hash to match — mutate one byte of the body and it reports
`DIVERGED`. This binds a Flare+XRPL solvency fact to an immutable Xahau record: one artifact spanning
three chains.

```sh
node anchor_submit.cjs --json fxrp-solvency-attestation.KVT-signed.json --secret <xahau-familyseed> \
  --endpoint wss://xahau-test.net --network 21338          # 21337 for Xahau mainnet
node anchor_verify.cjs --json fxrp-solvency-attestation.KVT-signed.json --tx <tx_hash> \
  --endpoint wss://xahau-test.net                          # CONSISTENT (exit 0) / DIVERGED (exit 2)
```

**Testnet-verified (Xahau testnet, NetworkID 21338):** the live FXRP attestation above was anchored in
tx `0294BEFA4FAE412C03573FAB4622966C749C9D6A8B717F6C3D8F199DD81C1004` (validated ledger 10670034);
`anchor_verify` returns CONSISTENT against the pristine attestation and DIVERGED on a one-byte
mutation. Mainnet anchoring pins the same hash on Xahau mainnet (pending a funded anchor account).
The anchor freezes the *hash*; proof *validity* still comes from re-deriving `fassets_verify.py` at the
pinned heights. Two keys, two roles: the Ed25519 attester key signs the verdict, the Xahau account key
authorizes the anchor tx.

## Run it

```sh
python3 -m venv .venv && .venv/bin/pip install web3     # (or use the bundled .venv)
.venv/bin/python fassets_verify.py --json   # dual-leg verdict, pinned, with caveats + trust model
.venv/bin/python negative_test.py           # prove it flags the bad cases (11/11)
.venv/bin/python render_attestation.py      # -> attestation.html (self-contained, re-derivable)
node sign_attestation.mjs                    # -> Ed25519-signed, anchor-ready attestation
```
No indexer, no API keys, no trusted middleware — just a Flare RPC and an XRPL RPC. `fassets_verify.py` is
the system-level tool (all FAssets); `fxrp_verify.py` is the FXRP-only variant.

## Built during Summer Signal (evidence of new work)

- **v0 (pre-program):** the XRPL-side binding — agents + Core-Vault balances incl. escrow.
- **New this program:** LEG 1 over-collateralization (protocol-authoritative status + CRs); the combined
  two-leg `SOLVENT` verdict; honest labeling + the trust-model block; the negative-test harness (teeth);
  the Ed25519-signed, anchor-ready attestation; the self-contained attestation page.

## Roadmap (credible path beyond the hackathon)

- **Live hosted dashboard** — a GitHub Action re-runs the verifier on a schedule and publishes the
  attestation page; a public URL with "last verified block/ledger."
- **Continuous watcher + alerts** — solvency as a live property (not a snapshot); alert on any drop below
  backing or an agent entering liquidation.
- **On-chain anchor** — write each `body_sha256` to an immutable, timestamped record (tamper-evident
  history you can't quietly restate).
- **Every FAsset** — FBTC/FDOGE auto-covered; the same engine, no new work.
- **Institutional / JP** — an independent, reproducible solvency layer is the bar SBI-grade counterparties
  and post-FTX JP compliance expect — a bar no self-reported TVL clears.

---
*Independent verification, not a Flare product and not on Flare's settlement path. Numbers are
on-chain-checkable at the pinned heights. — Kairo Vault Technologies 合同会社 · kairovault.com*
