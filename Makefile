.PHONY: up up-all down restart logs ps tunnel help

# Default VPS user — override with: make tunnel VPS_USER=ubuntu VPS_HOST=1.2.3.4
VPS_USER ?= root
VPS_HOST ?= your-vps-ip-or-hostname

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

tunnel: ## Print SSH tunnel command for PC debug access
	@echo "Run this on your PC to forward database ports:"
	@echo ""
	@echo "  ssh -L 5432:localhost:5432 \\"
	@echo "      -L 6543:localhost:6543 \\"
	@echo "      -L 6379:localhost:6379 \\"
	@echo "      $(VPS_USER)@$(VPS_HOST) -N"
	@echo ""
	@echo "Then connect:"
	@echo "  Postgres (session):      psql -h localhost -p 5432 -U postgres"
	@echo "  Postgres (transaction):  psql -h localhost -p 6543 -U postgres"
	@echo "  Redis:                   redis-cli -h localhost"
	@echo ""
	@echo "Studio and APIs are available at: https://supabase.nyhasinavalona.com"

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'
