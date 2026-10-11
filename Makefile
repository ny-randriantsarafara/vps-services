.PHONY: help setup check test integration collection plan bootstrap platform register-app
.DEFAULT_GOAL := help

PYTHON ?= python3
VENV := .venv
INVENTORY := inventories/production/hosts.yml
ANSIBLE := $(VENV)/bin/ansible
ANSIBLE_PLAYBOOK := $(VENV)/bin/ansible-playbook

# Les commandes qui touchent un serveur exigent TARGET, un nom d'hôte exact de l'inventaire.
define require_target
	@test -n "$(TARGET)" && $(ANSIBLE) -i $(INVENTORY) all --list-hosts | sed 1d | tr -d ' ' \
		| grep -qxF -- '$(TARGET)' \
		|| { echo "Cible explicite requise : make $@ TARGET=<hôte de $(INVENTORY)>" >&2; exit 2; }
endef

help: ## Afficher les commandes
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup: ## Créer .venv et installer les outils épinglés, hashes vérifiés
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install --require-hashes -r requirements-dev.lock

check: ## Lint, tests, syntaxe Ansible, build de la collection et git diff --check
	scripts/check.sh

test: ## Tests du contrôleur, du module Ansible et des rendus
	$(VENV)/bin/python -m unittest discover -s tests -v

integration: ## Test opt-in sur le Docker local (ressources vpsitest-* uniquement)
	cd tests/integration && VPS_INTEGRATION=1 ../../$(VENV)/bin/python -m unittest -v test_local_docker

collection: ## Construire la collection ny.vps dans dist/
	$(VENV)/bin/ansible-galaxy collection build collections/ansible_collections/ny/vps --output-path dist --force

plan: ## Simuler platform.yml sur TARGET (--check --diff), sans mutation
	$(require_target)
	$(ANSIBLE_PLAYBOOK) -i $(INVENTORY) playbooks/platform.yml --limit '$(TARGET)' --check --diff

bootstrap: ## Créer l'administrateur et durcir SSH sur TARGET (docs/OPERATIONS.md)
	$(require_target)
	$(ANSIBLE_PLAYBOOK) -i $(INVENTORY) playbooks/bootstrap.yml --limit '$(TARGET)'

platform: ## Appliquer le socle sur TARGET, sans démarrer d'application
	$(require_target)
	$(ANSIBLE_PLAYBOOK) -i $(INVENTORY) playbooks/platform.yml --limit '$(TARGET)'

register-app: ## Enregistrer les comptes de déploiement de vps_deploy_accounts sur TARGET
	$(require_target)
	$(ANSIBLE_PLAYBOOK) -i $(INVENTORY) playbooks/register-app.yml --limit '$(TARGET)'
