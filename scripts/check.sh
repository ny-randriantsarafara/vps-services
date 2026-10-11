#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$PWD/.venv/bin:$PATH"
test -x .venv/bin/python || { echo "Exécuter make setup avant les checks." >&2; exit 1; }
ruff check collections tests
ruff format --check collections tests
python -m unittest discover -s tests -v
ansible-lint --offline
for playbook in bootstrap platform register-app; do
  ansible-playbook -i inventories/production/hosts.yml "playbooks/$playbook.yml" --syntax-check
done
ansible-playbook -i examples/application/deploy/ansible/inventory.yml \
  examples/application/deploy/ansible/deploy.yml --syntax-check -e target_environment=preview
mkdir -p dist
ansible-galaxy collection build collections/ansible_collections/ny/vps --output-path dist --force
# Against the empty tree: every tracked file, including on a clean CI checkout.
git diff --check "$(git hash-object -t tree /dev/null)"
