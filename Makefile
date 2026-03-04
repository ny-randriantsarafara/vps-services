.PHONY: up up-all down restart logs ps tunnel caddy-install caddy-reload help

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
	@echo "Run this on your PC to forward all ports:"
	@echo ""
	@echo "  ssh -L 5432:localhost:5432 \\"
	@echo "      -L 6379:localhost:6379 \\"
	@echo "      -L 3000:localhost:3000 \\"
	@echo "      -L 8000:localhost:8000 \\"
	@echo "      $(VPS_USER)@$(VPS_HOST) -N"
	@echo ""
	@echo "Then connect:"
	@echo "  Postgres:  psql -h localhost -U postgres"
	@echo "  Redis:     redis-cli -h localhost"
	@echo "  Studio:    http://localhost:3000"
	@echo "  API:       http://localhost:8000"

caddy-install: ## Install Caddy config for supabase.nyhasinavalona.com and reload
	sudo cp caddy/Caddyfile /etc/caddy/conf.d/supabase.caddyfile
	sudo systemctl reload caddy

caddy-reload: ## Reload Caddy after config changes
	sudo systemctl reload caddy

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'
