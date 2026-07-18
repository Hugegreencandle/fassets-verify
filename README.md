# fassets-verify — Independent Proof-of-Reserves for the Flare FAssets system

**Flare Summer Signal — Interoperable Asset Products track.**

A trustless, reproducible re-checker that re-derives *"every FAsset is backed by its real underlying"* from **raw Flare + XRPL public data**, trusting no indexer, no UI, and no protocol self-report. Read the ledgers yourself; verify the peg yourself.

**It auto-discovers every live FAsset** (via `AssetManagerController.getAssetManagers()`) and verifies each — FXRP today, and **FBTC / FDOGE automatically the moment they launch**. It ships with a self-contained `dashboard.html` (opens in any browser, no server) and a `--json` attestation.

## The headline finding: the obvious reserve check is *wrong* for XRPL-escrow-backed assets

## The problem it solves

FXRP is a 1:1 XRP wrapper on Flare (FAssets). Its backing lives in **two places**: a handful of agent vaults, and — for ~99% of supply — the **v1.1 Core Vault**, a governance-run XRPL multisig.

Here's the trap: the Core Vault holds **~140M XRP in XRPL Escrow objects**, which do **not** count toward the account's `Balance`. A naive proof-of-reserves reads the Core Vault's balance (~10M), sees 150M of supply behind it, and **falsely screams "140M under-backed."** That naive check is the obvious one — and it's dangerously wrong.

`fxrp-verify` reads the **actual Escrow objects on the XRP Ledger** and reconciles the full picture.

## What it proves

```
FXRP.totalSupply()  ≤  Σ agents' live XRPL balance  +  Core-Vault (liquid Balance + Σ on-ledger Escrow amounts)
```

Fail-closed verdict, ledger-pinned:
- **PROVEN** — real XRP backing ≥ circulating FXRP.
- **FLAGGED** — under-backed (real XRP < supply).
- **CANNOT_VERIFY** — a required read failed (never a false "safe").

**Live result (mainnet):** FXRP supply ~152.08M, real XRP backing ~152.19M across 6 agents + the Core Vault (10.09M liquid + 140M escrow) → **PROVEN, ~+108k XRP surplus.** Every agent is over-reserved.

## How it works (trust nothing)

1. Resolve `AssetManagerFXRP` via the FlareContractRegistry; read `fAsset.totalSupply()`.
2. `getAllAgents` → per-agent `getAgentInfo` (minted, required, and each agent's XRPL address).
3. `getCoreVaultManager()` → `coreVaultAddress()` (the Core Vault XRPL address).
4. For every backing address, read **live XRP on the XRP Ledger** = liquid `Balance` + the sum of that account's **Escrow objects** (`account_objects`), pinned to one validated ledger.
5. Reconcile against `totalSupply`. Reproducible: same pinned ledger → same verdict.

No indexer, no API keys, no trusted middleware — just a Flare RPC and an XRPL RPC.

## Honest scope (what it does and doesn't claim)

- It proves the backing XRP **exists and is on-ledger** at the pinned moment. It does **not** claim the Core Vault's custody is trustless — the Core Vault is a **custodial multisig**, and this is disclosed, not hidden.
- It is a snapshot at a pinned ledger; production use wants a quiescent/settle-window pass to avoid in-flight noise.
- It is independent verification (proof-of-reserves), not an on-chain oracle.

## Why it's worth continuing

This is the operator/holder companion FAssets doesn't ship: anyone can verify the FXRP peg from public data without trusting Flare's own dashboards. It generalizes to a recurring **verification service** — re-prove reserves each ledger, per-agent attestations, and the same pattern extends to other FAssets.

## Run

```
python3 -m venv .venv && .venv/bin/pip install web3 xrpl-py
.venv/bin/python fassets_verify.py         # verify every live FAsset (auto-discovered); writes reserves.json
.venv/bin/python fassets_verify.py --json   # machine-readable attestation (pinned ledger + all reads)
open dashboard.html                         # self-contained visual report (embeds the latest reserves.json)
```

`fassets_verify.py` is the system-level tool (all FAssets). `fxrp_verify.py` is the FXRP-only variant. `dashboard.html` is regenerated from `reserves.json`.

Built on the same fail-closed, reproducible-from-public-data re-checker discipline as [Ward Protocol's coverage re-checker](https://github.com/wflores9/Ward-Protocol-OS)'s `--check-uniqueness`.
