.PHONY: help setup check test integration collection plan bootstrap platform register-app
.DEFAULT_GOAL := help

PYTHON ?= python3
VENV := .venv
INVENTORY := inventories/production/hosts.yml
ANSIBLE := $(VENV)/bin/ansible
ANSIBLE_PLAYBOOK := $(VENV)/bin/ansible-playbook

# Commands that touch a server require TARGET, an exact inventory host name.
define require_target
	@test -n "$(TARGET)" && $(ANSIBLE) -i $(INVENTORY) all --list-hosts | sed 1d | tr -d ' ' \
		| grep -qxF -- '$(TARGET)' \
		|| { echo "Explicit target required: make $@ TARGET=<host from $(INVENTORY)>" >&2; exit 2; }
endef

help: ## Show commands
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup: ## Create .venv and install pinned tools with verified hashes
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install --require-hashes -r requirements-dev.lock

check: ## Lint, tests, Ansible syntax, collection build, and git diff --check
	scripts/check.sh

test: ## Controller, Ansible module, and render tests
	$(VENV)/bin/python -m unittest discover -s tests -v

integration: ## Opt-in test on local Docker (vpsitest-* resources only)
	cd tests/integration && VPS_INTEGRATION=1 ../../$(VENV)/bin/python -m unittest -v test_local_docker

collection: ## Build the ny.vps collection into dist/
	$(VENV)/bin/ansible-galaxy collection build collections/ansible_collections/ny/vps --output-path dist --force

plan: ## Simulate platform.yml on TARGET (--check --diff), no mutation
	$(require_target)
	$(ANSIBLE_PLAYBOOK) -i $(INVENTORY) playbooks/platform.yml --limit '$(TARGET)' --check --diff

bootstrap: ## Create the administrator and harden SSH on TARGET (docs/OPERATIONS.md)
	$(require_target)
	$(ANSIBLE_PLAYBOOK) -i $(INVENTORY) playbooks/bootstrap.yml --limit '$(TARGET)'

platform: ## Apply the platform on TARGET without starting an application
	$(require_target)
	$(ANSIBLE_PLAYBOOK) -i $(INVENTORY) playbooks/platform.yml --limit '$(TARGET)'

register-app: ## Register deploy accounts from vps_deploy_accounts on TARGET
	$(require_target)
	$(ANSIBLE_PLAYBOOK) -i $(INVENTORY) playbooks/register-app.yml --limit '$(TARGET)'
