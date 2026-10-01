PY := .venv/bin/python
REPO ?=

.PHONY: setup dev test lint analyze crosscheck

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

# make analyze REPO=<git url or path> [SCOPE="dir1 dir2"] [NAME=name]
analyze:
	@test -n "$(REPO)" || (echo "usage: make analyze REPO=<git url or path> [SCOPE=\"dir ...\"] [NAME=x]"; exit 1)
	@case "$(REPO)" in \
	  http*|git@*) d=targets/$$(basename "$(REPO)" .git); [ -d "$$d" ] || git clone --depth 1 "$(REPO)" "$$d"; \
	    $(PY) -m analyzer "$$d" $(if $(SCOPE),--scope $(SCOPE)) $(if $(NAME),--name $(NAME)) --out out/ ;; \
	  *) $(PY) -m analyzer "$(REPO)" $(if $(SCOPE),--scope $(SCOPE)) $(if $(NAME),--name $(NAME)) --out out/ ;; \
	esac

# make crosscheck REPO=<path> NAME=<name> [SCOPE="dir ..."]   (cloc + grep vs analyzer output)
crosscheck:
	$(PY) scripts/crosscheck.py "$(REPO)" out/$(NAME).json $(if $(SCOPE),--scope $(SCOPE))
