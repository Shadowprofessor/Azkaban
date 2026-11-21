# Security gate: static egress check + agent tests (incl. "pull the cable" proof).
# Without make (e.g. Windows): python azkaban-agent/scripts/security.py
.PHONY: security
security:
	bash azkaban-agent/scripts/check_egress.sh
	python -m pytest -q azkaban-agent/tests
