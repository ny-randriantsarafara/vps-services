.PHONY: up up-all down restart logs ps tunnel sync-env help

# VPS connection — reads from .env if present, override with: make tunnel VPS_USER=ubuntu VPS_HOST=1.2.3.4
VPS_USER ?= $(or $(shell grep -s '^VPS_USER=' .env 2>/dev/null | cut -d= -f2),root)
VPS_HOST ?= $(shell grep -s '^VPS_HOST=' .env 2>/dev/null | cut -d= -f2)

up: ## Start core services (postgres + redis)
	docker compose up -d

up-all: ## Start all services including Supabase stack
	docker compose --profile supabase up -d

down: ## Stop all services
	docker compose --profile supabase down

restart: down up-all ## Restart everything

logs: ## Follow logs for all running services
	docker compose --profile supabase logs -f

ps: ## Show service status
	docker compose --profile supabase ps

tunnel: ## Open SSH tunnel for local database access (Ctrl+C to stop)
	@if [ -z "$(VPS_HOST)" ] || [ "$(VPS_HOST)" = "your-vps-ip-or-hostname" ]; then \
		echo "Error: VPS_HOST not configured. Set it in .env or run: make tunnel VPS_HOST=x.x.x.x"; \
		exit 1; \
	fi
	@echo "Opening SSH tunnel to $(VPS_USER)@$(VPS_HOST)..."
	@echo "  Postgres:  localhost:5432"
	@echo "  PgBouncer: localhost:6543"
	@echo "  Redis:     localhost:6379"
	@echo "Press Ctrl+C to stop."
	@ssh -L 5432:localhost:5432 \
	     -L 6543:localhost:6543 \
	     -L 6379:localhost:6379 \
	     $(VPS_USER)@$(VPS_HOST) -N

sync-env: ## Pull GitHub repo variables to local .env
	@scripts/sync-env-from-gh.sh

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'
