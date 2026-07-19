# fassets-verify — Independent Proof-of-Solvency for Flare FAssets (FXRP)

**Flare Summer Signal — Interoperable Asset Products.** By Kairo Vault Technologies (合同会社), an
independent verification company. Unaffiliated with Flare or the FAssets agents.

**▶ Live dashboard: https://hugegreencandle.github.io/fassets-verify/** — re-derived from live Flare +
XRPL every 6 hours, pinned to the exact block/ledger, re-checkable by anyone. The dashboard is
bilingual (English / 日本語, auto-selected by browser locale) and shows a continuous solvency timeline.

![FXRP proof-of-solvency status](https://hugegreencandle.github.io/fassets-verify/status.svg)
*(live badge — regenerated every run from the real verdict)*

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

## Mark-to-market via FTSOv2 — turning a *trusted* number into a *checked* one (LEG 1.5)

The protocol reports each agent's collateral ratio. Instead of trusting that number, this tool **re-derives
it independently**: it reads each agent's raw collateral *amounts* (`totalVaultCollateralWei` USDT +
`totalPoolCollateralNATWei` FLR) and values them in USD using **Flare's own enshrined FTSOv2 oracle**
(resolved live via the Flare Contract Registry, prices pinned to the block), against the minted-XRP
obligation valued at the FTSOv2 XRP/USD feed. It then **cross-checks the independently-computed CR against
the protocol's self-reported CR** and flags any agent that diverges >20%.

Live: agent collateral marks to **~$12.06M** against a **~$2.42M** minted obligation (**~497% coverage**),
and the independent vault CR reproduces the reported CR to ~0.1% (e.g. 212.32% vs 212.54%) — 0 divergences.
This is the highest-value kind of Flare integration: it uses Flare's own price layer to *verify* a claim the
protocol makes about itself, rather than consuming a feed superficially. Fail-soft: if FTSOv2 or a feed is
unavailable/stale, LEG 1.5 is omitted and the core two-leg verdict is unaffected (it never gates SOLVENT).

## FDC attestation-layer health — checking the *other* trusted input (LEG 0)

The FAssets **mint** side trusts Flare's **FDC (Data Connector)** attestations of XRPL payments. This tool
turns that assumption into an on-chain **liveness check**: it reads the recent finalized FDC (protocol 200)
Merkle roots from the **Relay** — the same root FAssets' own `FdcVerification` checks mint proofs against —
and confirms the attestation layer is live and finalizing (latest root, round, and finalization rate; stale
if the latest finalized round falls too far behind). Live: latest FDC root finalized 2 rounds back, 9/10
recent rounds finalized. Honest scope: this verifies the FDC consensus layer is **healthy**, not each
individual mint proof (that needs the DA-layer proof, deliberately out of scope) — and LEG 2 re-derives XRPL
balances directly regardless, so the solvency verdict never depends on FDC. Fail-soft like LEG 1.5.

Together with the FTSOv2 mark-to-market, both of the trust model's named Flare assumptions (the price oracle
and the data connector) are now **checked on-chain, not just trusted** — meaningful Flare integration, not
superficial feed consumption.

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

`negative_test.py` proves the verifier discriminates across **26 cases** at three layers: the two-leg
verdict, the **derivation itself** (with a mocked XRPL: a self-returning escrow counts as backing, an
external-destination escrow is EXCLUDED, an unreadable account fails closed; an agent below its floor or
in liquidation is FLAGGED, an agent whose floor can't be read is UNVERIFIED), and live-mutations of the
real FXRP data. Drop backing 1 UBA below supply, flag an agent, make one agent's floor unverifiable, or
fail an XRPL read, and the verdict flips off SOLVENT every time. The verifier and the tests share ONE
definition (`fassets_lib`) so they can't diverge — the derivation is tested, not just the combinator.

## Adversarially hardened (fail-closed by construction)

This verifier was put through a multi-lane red-team hunting for a **false SOLVENT**, and every finding was
fixed fail-closed: agent escrows are dest-filtered to self (an escrow paying out of the system can't
inflate backing); if the system-required collateral floor can't be read, exposed agents are marked
UNVERIFIED and the verdict is forced to CANNOT_VERIFY (never a status-only green); a failed custodian read
fails closed rather than counting Core-Vault escrows unfiltered; redeeming XRP is netted out of the
solvency comparison; agent-set pagination uses the correct end-index; and `floorReadOk` +
`collateral_unverifiable` are carried into the signed attestation so a degraded verdict can't be signed
clean. Reserve/custodian-attribution/cross-chain-skew assumptions that are real-but-immaterial are
disclosed in the caveats rather than hidden.

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
.venv/bin/python negative_test.py           # prove it flags the bad cases (26: verdict + derivation + live)
.venv/bin/python render_attestation.py      # -> attestation.html (self-contained, re-derivable)
node sign_attestation.mjs                    # -> Ed25519-signed, anchor-ready attestation
```
No indexer, no API keys, no trusted middleware — just a Flare RPC and an XRPL RPC. `fassets_verify.py` is
the system-level tool (all FAssets); `fxrp_verify.py` is the FXRP-only variant. RPC endpoints **fail over**
across multiple providers and `getAllAgents` **paginates**, so a single dead node or a >1000-agent system
can't sink or silently cap a run.

**One command (no local setup):**
```sh
make verify        # re-derive the dual-leg verdict     (make test / render / attest / all also available)
docker build -t fxrp-verify . && docker run --rm fxrp-verify   # verify in a container, zero host deps
```

## Built during Summer Signal (evidence of new work)

- **v0 (pre-program):** the XRPL-side binding — agents + Core-Vault balances incl. escrow.
- **New this program:** LEG 1 over-collateralization (protocol-authoritative status + CRs); the combined
  two-leg `SOLVENT` verdict; honest labeling + the trust-model block; the negative-test harness (teeth);
  the Ed25519-signed, anchor-ready attestation; the self-contained attestation page.

## Roadmap (credible path beyond the hackathon)

- ✅ **Live hosted dashboard** *(shipped)* — a GitHub Action re-derives the verifier every 6h and publishes
  the bilingual attestation page with the last verified block/ledger.
- ✅ **Continuous monitoring + alerts** *(shipped)* — each run appends to `history.jsonl` and the dashboard
  shows a solvency timeline ("SOLVENT at N/N checks"); a non-SOLVENT verdict opens a deduped GitHub issue.
- **On-chain anchor** — write each `body_sha256` to an immutable, timestamped record (tamper-evident
  history you can't quietly restate).
- **Every FAsset** — FBTC/FDOGE auto-covered; the same engine, no new work.
- **Institutional / JP** — an independent, reproducible solvency layer is the bar SBI-grade counterparties
  and post-FTX JP compliance expect — a bar no self-reported TVL clears.

---
*Independent verification, not a Flare product and not on Flare's settlement path. Numbers are
on-chain-checkable at the pinned heights. — Kairo Vault Technologies 合同会社 · kairovault.com*
