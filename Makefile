# Development targets. `make help` lists them.
# Windows/other platforms: every recipe is a single command you can run by hand;
# see README.md for the literal equivalents.

SHELL := /bin/bash
API := api
COMPOSE := docker compose

.PHONY: help up down dev demo demo-prepare test lint typecheck migrate migration seed-demo frontend-dev \
	frontend-build frontend-test check validate-live replay-validation import-anchors review-candidates \
	collect-candidates collect-resource-evidence poll-watches monitor-demo

help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-16s %s\n", $$1, $$2}'

up: ## Start PostgreSQL and Redis (only needed when not using the SQLite default)
	$(COMPOSE) up -d --wait

down: ## Stop optional local infrastructure
	$(COMPOSE) down

dev: ## Run the API with reload
	cd $(API) && uv run uvicorn app.main:app --reload --port 8000

demo: ## Run the local read-only investigator console (needs `make demo-prepare` once)
	./scripts/run_demo.sh

demo-prepare: ## One-time: install deps, prepare the DB, build the workspace, verify demo artifacts (needs network)
	@command -v uv >/dev/null 2>&1 || { echo "error: 'uv' is required (https://docs.astral.sh/uv/)." >&2; exit 1; }
	cd $(API) && uv sync --all-groups
	@command -v npm >/dev/null 2>&1 || { echo "error: 'npm' is required (Node 22+)." >&2; exit 1; }
	cd frontend && npm ci
	cd frontend && npm run build
	cd $(API) && uv run alembic upgrade head
	cd $(API) && CFA_DATA_MODE=SYNTHETIC uv run python ../scripts/trace_demo.py
	cd $(API) && CFA_DATA_MODE=SYNTHETIC uv run python ../scripts/seed_demo.py
	@echo "Prepared. Start the demo with: make demo"

worker: ## Run the arq worker (optional; no queued work exists yet)
	cd $(API) && uv run arq app.worker.WorkerSettings

test: ## Run the test suite
	cd $(API) && uv run pytest -q

lint: ## Lint Python and TypeScript
	cd $(API) && uv run ruff check .
	cd frontend && npx oxlint src

format: ## Format Python
	cd $(API) && uv run ruff format .

typecheck: ## Type-check Python and TypeScript
	cd $(API) && uv run mypy app
	cd frontend && npx tsc --noEmit

migrate: ## Apply migrations
	cd $(API) && uv run alembic upgrade head

migration: ## Autogenerate a migration: make migration m="message"
	cd $(API) && uv run alembic revision --autogenerate -m "$(m)"

trace-demo: ## Run the stage-1 slice against the synthetic fixture and open the report
	cd $(API) && uv run python ../scripts/trace_demo.py

validate-live: ## One live TRON validation into var/live-validation (needs CFA_DATA_MODE=LIVE and a key)
	cd $(API) && uv run python ../scripts/validate_live.py $(ARGS)

replay-validation: ## Replay a saved bundle offline: make replay-validation RUN=var/live-validation/<id>
	cd $(API) && CFA_DATA_MODE=RECORDED_PUBLIC uv run python ../scripts/validate_live.py --replay ../$(RUN)

poll-watches: ## One bounded poll of every active watch, then exit: make poll-watches ARGS="--fixture ../fixtures/..."
	cd $(API) && uv run python ../scripts/poll_watches.py --once $(ARGS)

monitor-demo: ## Offline SYNTHETIC monitoring demo: one new event -> one alert, replay and restart -> none
	cd $(API) && uv run python ../scripts/monitoring_demo.py

import-anchors: ## Import a disclosure into the label sets (see data/README.md for the arguments)
	cd $(API) && uv run python ../scripts/import_anchors.py $(ARGS)

review-candidates: ## List or decide imported claims: make review-candidates ARGS="list"
	cd $(API) && uv run python ../scripts/review_candidates.py $(ARGS)

collect-candidates: ## Find deposit-address leads for one accepted anchor (see scripts/collect_candidates.py)
	cd $(API) && uv run python ../scripts/collect_candidates.py $(ARGS)

collect-resource-evidence: ## Resource-delegation/TRX-funding evidence for one candidate (see scripts/collect_resource_evidence.py)
	cd $(API) && uv run python ../scripts/collect_resource_evidence.py $(ARGS)

seed-demo: ## Load the SYNTHETIC demo fixture
	cd $(API) && uv run python ../scripts/seed_demo.py

frontend-dev: ## Run the frontend dev server
	cd frontend && npm run dev

frontend-build: ## Build the frontend
	cd frontend && npm run build

frontend-test: ## Run the frontend tests
	cd frontend && npm run test

check: lint typecheck test ## Everything CI runs
