PY := .venv/bin/python
REPO ?=

.PHONY: setup dev test lint analyze

setup:
	python3 -m venv .venv
	$(PY) -m pip install -q -e ".[dev]"
	cd web && npm install

dev:
	@trap 'kill 0' INT TERM EXIT; \
	$(PY) -m uvicorn api.app.main:app --port 8000 --reload & \
	cd web && npm run dev -- --port 3000 & \
	wait

test:
	$(PY) -m pytest -q
	cd web && npx tsc --noEmit

lint:
	.venv/bin/ruff check .
	.venv/bin/mypy analyzer api llm
	cd web && npm run lint

analyze:
	@test -n "$(REPO)" || (echo "usage: make analyze REPO=<git url or path>"; exit 1)
	$(PY) -m analyzer "$(REPO)" --out out/
