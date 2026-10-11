# Refonte Ansible VPS Services — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer la stack héritée par un socle Ansible utilisable et un contrat de déploiement applicatif isolé, avec admission globale vérifiable.

**Architecture:** Une collection `ny.vps` configure le serveur et fournit un rôle applicatif. Une commande locale privilégiée limitée valide les demandes, sérialise les mutations, applique Compose et les routes Caddy et expire les previews. Chaque dépôt applicatif reste propriétaire de sa stack et de son playbook.

**Tech Stack:** Debian 13, Python 3 standard library pour le contrôleur, Ansible, Docker Engine/Compose, Caddy, iptables-nft/ip6tables-nft, unittest/pytest, ansible-lint et Ruff pour les checks locaux.

**Spec:** `docs/superpowers/specs/2026-10-11-ansible-vps-design.md`

## Global Constraints

- Plafond global au VPS : deux previews actives, configurable sur l'hôte ; une instance par application/PR.
- Instance durable `prod` ou `staging`, preview `pr-<nombre>` ; réseaux, volumes, secrets et données distincts.
- Budgets applicatifs agrégés : production 1,5 vCPU / 3 GiB ; staging 0,5 vCPU / 1 GiB ; previews 1 vCPU / 2 GiB ; une preview au plus 0,5 vCPU / 1 GiB.
- Expiration preview : 72 heures depuis apply réussi ou renouvellement explicite ; pas d'expiration prod/staging.
- Déploiements manuels au début ; pas d'ancien déploiement sur push main.
- Pas de reconstruction des anciennes apps, Supabase commun, Kubernetes, daemon ou API publique de déploiement.
- Aucun commit, push, PR, mutation DNS, reset ou provisioning du vrai VPS.
- Secrets hors Git et sorties publiques, comptes CI sans docker group ou sudo général, contrôle des host keys.
- Ne pas écraser un travail concurrent du dossier original ; archive privée hors Git avant remplacement, `.git` conservé.

## Contrat commun version 1

Le processus root-owned `vpsctl request` reçoit un JSON borné par stdin. Les chemins de politique et d'état sont fixés pour le CLI privilégié, sans surcharge par environnement/arguments CI. Une API Python injectable permet les tests locaux sans droits root. Installation : `/usr/local/lib/vps-platform/vps_platform`, launcher `/usr/local/sbin/vpsctl`, politique `/etc/vps-platform/policy.json`, état `/var/lib/vps-platform`, instances `/srv/vps/apps`.

```json
{
  "protocol": 1,
  "operation": "apply",
  "application": "exemple",
  "environment": "preview",
  "pull_request": 42,
  "generation": 123,
  "compose": {"services": {}},
  "routes": [],
  "storage_budget_gib": 2
}
```

`compose` est une structure YAML/JSON rendue côté app ; les secrets autorisés sont déjà dans les environnements des seuls services concernés. Le contrôleur valide un sous-ensemble explicite : image par digest, une réplique, limites directes par service, volumes nommés propres à l'instance, ports HTTP loopback attribués par le contrôleur, healthchecks, jobs d'initialisation déclarés. Aucun `env_file`, `include`, `extends`, Docker build, socket, device, namespace host ou bind mount applicatif arbitraire. Les routes contiennent `hostname`, `service`, `port` ; aucun fragment de configuration proxy. Les opérations de lecture/suppression/renouvellement utilisent la même identité et instance ; une génération monotone protège apply et fermeture. La politique possède `accounts` associant utilisateur SSH à application/environnements, `administrators`, `domain` vide par défaut, plafonds et chemins gérés par le socle.

Sortie JSON : `changed`, `instance`, `status`, `reason` et diagnostics non sensibles. Pas de request brute, secrets ou Compose complet en sortie. Exceptions opérationnelles sanitaires ; journaux de conteneur explicitement demandés uniquement pour l'instance autorisée, avec avertissement que l'app doit elle-même éviter d'y écrire ses secrets.

### Task 1: Contrôleur local, admission et cycle Compose

**Files:**
- Create: `collections/ansible_collections/ny/vps/roles/controller/files/vps_platform/{__init__,policy,compose,state,runtime,controller,cli}.py`
- Create: `collections/ansible_collections/ny/vps/roles/controller/files/{launcher.py,vpsctl}`
- Test: `tests/test_controller.py`, `tests/test_compose.py`, `tests/test_runtime.py`, `tests/helpers.py`

**Interfaces:**
- Consumes: contrat JSON version 1 ci-dessus et politique hôte JSON ; identité effective transmise par le CLI, jamais depuis la requête.
- Produces: `Controller(policy, state_dir, runtime).request(payload, actor)` ; runtime Docker/Caddy et CLI `request`, `status`, `previews list`, `previews destroy --instance`, `previews renew --instance`, `cleanup`, `logs --instance --tail`.
- Le runtime est une frontière injectable ; le registre et le flock restent réels dans les tests.

- [ ] **Step 1: écrire les tests comportementaux avant le code.** Les attentes sont littérales, notamment :

```python
def test_third_preview_is_refused_without_evicting_existing_instances():
    # Deux applications distinctes ont chacune une preview déjà admise.
    # Une troisième request applique la politique réelle et doit être refusée.
    assert third_result["status"] == "refused"
    assert instance_names == {"alpha-pr-1", "beta-pr-2"}
```

Tester réellement concurrence via processus et flock, mise à jour même PR, limites par service/agrégées, identité prod/nonprod, données/noms isolés, refus des configurations dangereuses, idempotence, secrets persistés privés mais absents du registre, fermeture/génération, crash/cleanup incomplet et TTL. Les appels Docker/Caddy sont doublés uniquement lorsqu'ils exigent un daemon ou un serveur.
- [ ] **Step 2: lancer `python -m unittest discover -s tests -v` et constater l'échec des comportements encore absents.** Implémenter progressivement les modules et relancer le même groupe de tests.
- [ ] **Step 3: construire le runtime réel.** Utiliser des subprocess argv, délais bornés et stdout/stderr non sensibles ; conserver labels et checks de propriété avant suppression ; pas de prune global. JSON privé atomique, secrets échappant l'interpolation Compose, fichiers `0600`, répertoires `0700`. Réconcilier les états inconnus avec les ressources réelles sans libérer une place à l'aveugle. Des objets app non suivis bloquent les nouvelles admissions.
- [ ] **Step 4: vérifier puis relire.** Tests réels du CLI, invalid JSON et sorties JSON, chemins fixes en mode privilégié, plan sans mutation et status/cleanup. Fournir evidence RED/GREEN et contrat final précis pour le rôle Ansible.

### Task 2: Collection Ansible, serveur et exemple applicatif exécutable

**Files:**
- Create: `ansible.cfg`, `inventories/production/{hosts.yml,group_vars/all.yml}`, `playbooks/{bootstrap,platform,register-app}.yml`
- Create: `collections/ansible_collections/ny/vps/galaxy.yml`, `roles/{host,ssh,firewall,docker,ingress,controller,app}/{tasks,handlers,defaults,templates}` selon besoin
- Create: `collections/ansible_collections/ny/vps/plugins/modules/deploy_instance.py`
- Create: `examples/application/deploy/{compose.yml.j2,ansible/{deploy.yml,inventory.yml,requirements.yml,environments/{preview,staging,prod}.yml}}`
- Test: `tests/test_app_module.py`, checks syntaxe/lint et rendu local des exemples.

**Interfaces:**
- Consumes: CLI `vpsctl request` et contrat réel Task 1. Le module Ansible n'accorde pas de sudo général : subprocess fixe `sudo -n /usr/local/sbin/vpsctl request`, JSON stdin, `no_log` pour payload et `supports_check_mode=True` transformant apply en plan.
- Produces: playbooks utilisables depuis le poste, host vars sûres, collection installable/construisible ; exemple sans secrets réels ou domaine réel.

- [ ] **Step 1: écrire et lancer un test du module avant implémentation.** L'entrée apply en check mode doit transmettre `plan`, ne produire aucune réservation, conserver le JSON de sortie filtré et échouer sur erreur de protocole plutôt que déclarer un succès.

```python
def test_check_mode_requests_plan_instead_of_apply():
    assert sent_payload["operation"] == "plan"
    assert result["changed"] is False
```

- [ ] **Step 2: créer bootstrap en deux phases.** Installer les clés de l'administrateur puis tester une connexion indépendante avant durcissement/retrait d'accès initial. `sshd -t`, drop-in validé, reload ; état sûr en cas d'échec ; récupération OVH documentée. Compte administrateur non-root, comptes applicatifs explicitement enregistrés sans docker group, sudoers validé par visudo.
- [ ] **Step 3: créer platform idempotent.** APT signé Docker Debian 13 avec versions exactes vérifiées, Compose, limites logs ; SSH, règles IPv4/IPv6 INPUT et DOCKER-USER restaurées après daemon/reboot sans supprimer NAT Docker ; Caddy systemd, socket Unix admin, routes contrôlées, aucun ancien domaine. Timer cleanup/pression disque 5 min. Contrôleur installé root-owned, configuration privée et politique cohérente avec Task 1. Aucun conteneur app démarré par platform.
- [ ] **Step 4: créer le rôle app et l'exemple.** Rendu Compose depuis le dépôt app, limites et volumes isolés, base de test et fixtures synthétiques dans une image pinned ; readiness obligatoire. Référence collection locale fonctionnelle pour smoke test, plus procédure exacte de pinning à un SHA de release sans faux SHA. `no_log`, `diff: false`, secrets explicitement fournis et vérifiés ; pas de `.env` global.
- [ ] **Step 5: lancer les checks disponibles.** Build/install collection, ansible-playbook --syntax-check bootstrap/platform/register-app/app, ansible-lint, rendu app en localhost sans mutation VPS. Relire et fournir evidence avec versions réellement disponibles.

### Task 3: Remplacement de l'héritage, documentation et vérification intégrée

**Files:**
- Modify: `README.md`, `Makefile`, `.gitignore`, `docs/{ARCHITECTURE,CICD}.md`
- Remove: `docker-compose.yml`, `.env.example`, ancien `caddy/`, `volumes/`, `scripts/sync-env-*`, `docs/DATABASE-CONNECTION.md`, anciens workflows de déploiement/build couplés.
- Create: `.github/workflows/validate.yml`, `requirements-dev.txt`, `pyproject.toml` et/ou configs lint nécessaires, `docs/{APP-CONTRACT,OPERATIONS,MIGRATION}.md`, `scripts/check.sh`, `tests/integration/` si Docker local utilisable.

**Interfaces:**
- Consumes: Tasks 1 et 2, commandes et politiques effectives.
- Produces: `make setup`, `make check`, `make test`, `make plan`, `make bootstrap`, `make platform`, build collection ; CI validation seule ; guide complet en français.

- [ ] **Step 1: supprimer uniquement l'héritage remplacé.** Pas de catalogue historique ; CI sur push/PR ne fait que valider, aucun secret VPS. Épingler dépendances et Actions par versions/SHA réellement vérifiés.
- [ ] **Step 2: connecter docs et commandes réelles.** Exemple : `make check` lance lint, tests, syntaxe et build de la collection ; commandes dangereuses nécessitent cible explicite ; toutes les commandes illustrées doivent correspondre à un code créé.
- [ ] **Step 3: intégration locale disponible.** Docker local : deux apps/previews, troisième refusée, données distinctes, limites effectives, mise à jour et cleanup ciblé. Utiliser uniquement ressources de test marquées, sans toucher aux conteneurs/volumes existants. Si daemon ou VM indisponible, conserver un script reproductible opt-in et rapporter les gates non exécutés sans prétendre une validation réelle.
- [ ] **Step 4: relire l'ensemble et vérifier `git diff --check`.** Distinguer tests du contrôleur, rendu/syntaxe Ansible, daemon local, VM Debian 13 et VPS réel.

### Task 4: Revue finale, corrections et bascule locale protégée

**Files:**
- Modify: uniquement fichiers des Tasks 1–3 pour corriger les findings reproduits.
- External optional: dossier original `/Users/nrandriantsarafara/Works/sandbox/vps-services` après archive privée et vérification de concurrence ; aucun changement GitHub ou `.git`.

**Interfaces:**
- Consumes: diff complet non commité, spec, evidence tests, contrat et guides.
- Produces: findings traités et état final honnête, implémentation worktree prête et statut distinct du dossier original.

- [ ] **Step 1: revue spec + qualité par un agent distinct puis revue finale des interactions.** Diff non commité empaqueté incluant nouveaux fichiers ; pas de faux range HEAD..HEAD. Corriger les défauts vérifiés avec régression ciblée.
- [ ] **Step 2: exécuter les gates affectés après corrections.** Pas de multiplication de suites identiques sans nouvelles raisons.
- [ ] **Step 3: recontrôler le dossier original.** Si HEAD/status et fichiers sont inchangés, préparer une archive privée complète de l'ancien working tree hors Git (`.env` inclus), garder `.git` en place puis remplacer uniquement fichiers du périmètre par les nouveaux fichiers vérifiés, sans copier cache/.venv/état/secrets. Préserver worktrees et remote. Si travail concurrent ou permissions non résolues, ne pas forcer ; rapporter exactement la bascule restante.
- [ ] **Step 4: rapporter les chemins et preuves.** Aucun commit/push/PR/deploy. Indiquer les gates manquants, l'accès VPS bloqué et la sélection future d'une app/domaine réel.
