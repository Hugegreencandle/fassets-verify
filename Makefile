# fassets-verify — one-command reproducibility. `make verify` re-derives the FXRP solvency verdict from
# raw Flare + XRPL; `make test` proves it flags the bad cases; `make attest` builds the signed attestation
# + public page. Uses the bundled .venv if present, else falls back to system python3.
PY := $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)

.PHONY: help verify test render attest badge history all docker clean
help:            ## show this help
	@grep -E '^[a-z].*:.*##' $(MAKEFILE_LIST) | sed 's/:.*##/ —/' | sort

verify:          ## re-derive the dual-leg verdict (writes reserves.json), print it
	$(PY) fassets_verify.py

test:            ## prove the verifier flags the bad cases (unit + live mutations)
	$(PY) negative_test.py

badge:           ## regenerate the status.svg badge from the latest verdict
	$(PY) make_badge.py

history:         ## append this run's verdict to history.jsonl (dedups by flare_block)
	$(PY) append_history.py

render:          ## build the self-contained bilingual attestation.html
	$(PY) render_attestation.py

attest:          ## Ed25519-sign the verdict (needs Node + ~/.kvt-attester key)
	node sign_attestation.mjs

all: verify test history badge render   ## full pipeline: verify -> test -> history -> badge -> page

docker:          ## build + run the reproducible container (no local Python needed)
	docker build -t fxrp-verify . && docker run --rm fxrp-verify

clean:           ## remove generated artifacts (keeps history.jsonl)
	rm -f attestation.html status.svg reserves.json fxrp-solvency-attestation.KVT-signed.json anchor-record.json
