# One-command, reproducible re-derivation of the FXRP solvency verdict from raw Flare + XRPL.
# A judge (or anyone) can verify without setting up Python:
#   docker build -t fxrp-verify . && docker run --rm fxrp-verify
# Prints the dual-leg verdict pinned to a live Flare block + XRPL ledger. Read-only; no keys, no privileged access.
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir web3
# copy only what the verdict + its teeth need (no venv, no node)
COPY fassets_verify.py fassets_lib.py fxrp_verify.py negative_test.py agentinfo_abi.json ./
# default: re-derive and print the verdict. `docker run --rm fxrp-verify python negative_test.py` proves the teeth.
CMD ["python", "fassets_verify.py"]
