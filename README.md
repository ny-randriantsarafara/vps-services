# vps-services

Socle Ansible d'un VPS unique (Debian 13) et contrat de déploiement des applications.

Ce dépôt configure le serveur : administrateur non-root, SSH par clés, firewall IPv4/IPv6, Docker, Caddy et une commande locale d'admission, `vpsctl`. Il ne déploie aucune application. Chaque dépôt applicatif possède son Compose et son playbook, et passe par la collection `ny.vps` pour demander une instance `prod`, `staging` ou `preview`.

Le vocabulaire (application, instance, preview, place de preview, admission) est défini dans le [glossaire](GLOSSARY.md).

## Règles du socle

- Deux previews au plus sur le VPS, toutes applications confondues ; la troisième est refusée, aucune n'est évincée.
- Budgets agrégés (inventaire, `vps_budgets`) : productions 1,5 vCPU / 3 GiB, stagings 1 vCPU / 1 GiB, previews 2 vCPU / 2 GiB, une preview au plus 1 vCPU / 1 GiB.
- Une preview expire 72 heures après sa dernière livraison réussie ou son dernier renouvellement ; prod et staging n'expirent jamais.
- Chaque instance a son réseau, ses volumes, ses secrets et ses données. Seul Caddy écoute sur 80/443 ; les applications publient sur `127.0.0.1` uniquement.
- Les comptes de déploiement n'ont ni groupe `docker` ni sudo général : seulement `sudo -n /usr/local/sbin/vpsctl request`.
- Les déploiements partent des dépôts applicatifs (poste ou CI de l'application, voir [CI/CD](docs/CICD.md)). La CI de ce dépôt valide, elle ne déploie rien.

## Structure

```text
inventories/production/   VPS, administrateur, comptes de déploiement (aucun secret)
playbooks/                bootstrap.yml, platform.yml, register-app.yml
collections/ansible_collections/ny/vps/
  roles/                  host, ssh, firewall, docker, ingress, controller, app
  roles/controller/files/vps_platform/   contrôleur vpsctl (Python, bibliothèque standard)
  plugins/modules/        deploy_instance : requête du protocole version 1
examples/application/     application fictive « exemple » et son déploiement
tests/                    contrôleur, module, rendus Ansible ; tests/integration : Docker local
docs/                     architecture, contrat applicatif, exploitation, CI, migration
```

## Commandes

```bash
make setup                          # .venv et outils épinglés (hashes vérifiés)
make check                          # Ruff, tests, ansible-lint, syntaxe, build de la collection
make test                           # tests unitaires seuls
make integration                    # opt-in : Docker local, ressources vpsitest-* uniquement
make collection                     # construit ny.vps dans dist/

make plan TARGET=vps-d9d9aca9       # platform.yml en --check --diff
make bootstrap TARGET=vps-d9d9aca9  # administrateur puis durcissement SSH
make platform TARGET=vps-d9d9aca9   # socle, sans application
make register-app TARGET=vps-d9d9aca9
```

Les commandes qui touchent un serveur refusent de s'exécuter sans `TARGET` égal à un nom d'hôte exact de l'inventaire.

## Documentation

| Document | Contenu |
| --- | --- |
| [Architecture](docs/ARCHITECTURE.md) | Composants, admission, isolation, état local |
| [Contrat applicatif](docs/APP-CONTRACT.md) | Requête version 1, sous-ensemble Compose, routes, statuts, rôle `ny.vps.app` |
| [Exploitation](docs/OPERATIONS.md) | Empreintes SSH, bootstrap, récupération OVH, `vpsctl`, diagnostics |
| [CI/CD](docs/CICD.md) | Validation de ce dépôt, règles pour les déploiements applicatifs |
| [Migration](docs/MIGRATION.md) | Retrait de l'ancienne stack Supabase et de ses workflows |
| [Conception](docs/superpowers/specs/2026-10-11-ansible-vps-design.md) | Spécification et décisions |
| [Routes multiples](docs/superpowers/specs/2026-10-11-multi-route-design.md) | Noms secondaires d'une instance, domaine `apps`, comptes `my-media` |

## État de validation

| Niveau | État |
| --- | --- |
| Contrôleur, module et rendus (`make check`) | Exécuté localement |
| Configurations générées (sshd, dockerd, iptables-nft, Caddy) | Validées avec les outils épinglés en conteneurs |
| Docker local (`make integration`) | Exécuté : deux previews, troisième refusée, données distinctes, limites effectives, mise à jour, nettoyage ciblé |
| VM Debian 13 complète (systemd, reboot, idempotence) | Non exécuté |
| VPS réel | Provisionné : bootstrap, `platform` deux fois (second passage sans changement), reboot, seuls 22/80/443 ouverts en IPv4/IPv6, filtrage `DOCKER-USER` vérifié |

Domaine des instances : `apps.nyhasinavalona.com` (wildcard DNS `*.apps`, sans proxy Cloudflare). Application enregistrée : `my-media` (comptes `my-media-nonprod` et `my-media-prod`).
