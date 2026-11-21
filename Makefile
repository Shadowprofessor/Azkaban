# Azkaban v1. Windows users without make: every target is a one-liner, see V1.md.
PY ?= python

.PHONY: security test test-agent test-rag test-ext build-ext package capture dashboard check nim-check rag-check install

## ---- setup
install:
	$(PY) -m pip install -e "azkaban-agent[dev]"
	cd azkaban-extension && npm install
	cd dashboard && npm install

## ---- verification
# Security gate: static egress check + agent tests (incl. "pull the cable" proof).
security:
	bash azkaban-agent/scripts/check_egress.sh
	$(PY) -m pytest -q azkaban-agent/tests

test-agent:
	$(PY) -m pytest -q azkaban-agent/tests

test-rag:
	$(PY) -m pytest -q rag/tests

test-ext:
	cd azkaban-extension && npm run typecheck && npm run test:score && npm run test:alerts && npm run test:bridge

test: test-agent test-rag test-ext

# Everything the release checklist asks for.
check: security test-rag
	node scripts/check-extension-egress.mjs
	cd azkaban-extension && npm run typecheck && npm run build
	cd dashboard && npm run build

## ---- build
build-ext:
	cd azkaban-extension && npm run build

package:
	bash scripts/package-extension.sh

## ---- run (real data)
capture:
	$(PY) -m azkaban_agent capture --i-own-this-device

dashboard:
	cd dashboard && npm run dev

## ---- diagnostics
nim-check:
	$(PY) -m azkaban_agent nim-check

rag-check:
	$(PY) -m azkaban_agent rag-check --tracker --cross-border --no-consent --pii gps,adid --company Google
