# The lab's end-to-end flow. `make` on its own shows this list.
.DEFAULT_GOAL := help
.PHONY: help test demo-image check up demo demo-json smoke demo-ready scenarios logs down clean runloop-setup runloop-preflight runloop-mcp-setup runloop-mcp-check runloop-policy runloop-blueprint runloop-up runloop-redeploy runloop-demo runloop-status runloop-snapshot runloop-down runloop-e2e
PYTHON_ENV := PYTHONPYCACHEPREFIX=/tmp/agentdns-sentinel-pycache
RUNLOOP_PYTHON := .venv/bin/python
CODEX_CLI := $(shell if command -v codex >/dev/null 2>&1; then command -v codex; elif test -x /Applications/ChatGPT.app/Contents/Resources/codex; then printf '%s' /Applications/ChatGPT.app/Contents/Resources/codex; fi)

help: ## Show this help
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[1m%-20s\033[0m %s\n", $$1, $$2}'

## -- local flow ------------------------------------------------------------

demo-image: ## Regenerate every PNG in docs/ from its source
	python3 scripts/render_demo_image.py
	python3 scripts/render_demo_image.py --dark --output docs/agentdns-sentinel-demo-dark.png
	python3 scripts/export_svg_png.py docs/agentdns-sentinel-reference-architecture.svg --size 1800

test: ## Run the unit tests (no Docker required)
	$(PYTHON_ENV) python3 -m unittest discover -v

check: test ## Run static checks and validate the Compose model
	$(PYTHON_ENV) python3 -m compileall -q agents dashboard demo dns_manager runloop_lab scripts tests
	python3 -m json.tool config/policies.json >/dev/null
	docker compose config --quiet

scenarios: ## List the demonstration scenarios
	python3 scripts/demo.py list

up: ## Build and start the lab locally
	docker compose up --build -d
	@echo "Dashboard: http://localhost:3000   Control API (bearer protected): http://localhost:8053"

demo: ## Run every scenario inside the running lab
	docker compose exec -T dashboard python scripts/demo.py run all

demo-json: ## Run every scenario and emit machine-readable results
	docker compose exec -T dashboard python scripts/demo.py run all --json

smoke: ## Verify all scenarios in the running lab from the host
	python3 scripts/verify_demo.py

demo-ready: check up smoke ## Build, start, and verify the complete local demo

logs: ## Tail the lab's logs
	docker compose logs -f --tail=100

down: ## Stop the lab and remove its volumes
	docker compose down -v

clean: down ## Stop the lab and remove local build artefacts
	rm -rf .web artifacts .runloop
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

## -- runloop flow ----------------------------------------------------------

runloop-setup: ## Create the Runloop environment and install its SDK
	python3 scripts/setup_runloop.py
	$(RUNLOOP_PYTHON) -m pip install 'runloop-api-client>=1.31,<2'
	@echo "Next: add RUNLOOP_API_KEY to .env, then run 'make runloop-e2e'."

runloop-preflight: ## Validate the Runloop SDK, credentials, and project configuration
	@test -x $(RUNLOOP_PYTHON) || (echo "Run 'make runloop-setup' first."; exit 1)
	$(RUNLOOP_PYTHON) scripts/runloop_preflight.py

runloop-mcp-setup: ## Register Runloop MCP with the local Codex installation
	@python3 scripts/runloop_mcp.py --check
	@test -n "$(CODEX_CLI)" || (echo "Codex CLI was not found in PATH or the ChatGPT app."; exit 1)
	@"$(CODEX_CLI)" mcp get runloop >/dev/null 2>&1 || "$(CODEX_CLI)" mcp add runloop -- $(CURDIR)/scripts/runloop_mcp.py
	@echo "Runloop MCP registered. Restart Codex, then ask it to list Runloop Devboxes."

runloop-mcp-check: ## Check the Codex-to-Runloop MCP integration
	@python3 scripts/runloop_mcp.py --check
	@test -n "$(CODEX_CLI)" || (echo "Codex CLI was not found in PATH or the ChatGPT app."; exit 1)
	@"$(CODEX_CLI)" mcp get runloop

runloop-policy: runloop-preflight ## Create the Devbox egress boundary
	$(RUNLOOP_PYTHON) scripts/runloop_lab.py policy

runloop-blueprint: runloop-preflight ## Build the reusable blueprint from this repository
	$(RUNLOOP_PYTHON) scripts/runloop_lab.py blueprint

runloop-up: runloop-preflight ## Start a Devbox, sync the code and bring the lab up
	$(RUNLOOP_PYTHON) scripts/runloop_lab.py up

runloop-redeploy: runloop-preflight ## Sync changes into the current Devbox and rebuild the lab
	$(RUNLOOP_PYTHON) scripts/runloop_lab.py redeploy

runloop-demo: runloop-preflight ## Run the scenarios on the Devbox and save the evidence
	$(RUNLOOP_PYTHON) scripts/runloop_lab.py demo

runloop-status: runloop-preflight ## Show this project's Devboxes and services
	$(RUNLOOP_PYTHON) scripts/runloop_lab.py status

runloop-snapshot: runloop-preflight ## Snapshot the Devbox disk
	$(RUNLOOP_PYTHON) scripts/runloop_lab.py snapshot

runloop-down: runloop-preflight ## Shut the Devbox down
	$(RUNLOOP_PYTHON) scripts/runloop_lab.py down

runloop-e2e: runloop-preflight ## Launch, verify, and keep the Runloop demo available
	$(RUNLOOP_PYTHON) scripts/runloop_lab.py e2e --keep
