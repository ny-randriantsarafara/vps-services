# Contrat applicatif — protocole version 1

Une application se déploie depuis son propre dépôt avec le rôle `ny.vps.app`. Le rôle rend le Compose de l'application sur le poste, puis le module `ny.vps.deploy_instance` transmet une requête JSON à `sudo -n /usr/local/sbin/vpsctl request` sur le VPS. Le contrôleur décide de l'admission, applique Compose et publie la route.

L'exemple complet est dans [`examples/application/deploy`](../examples/application/deploy).

## Installer la collection

Dans le dépôt applicatif, `deploy/ansible/requirements.yml` épingle une release revue par son SHA complet :

```yaml
collections:
  - name: https://github.com/ny-randriantsarafara/vps-services.git#/collections/ansible_collections/ny/vps
    type: git
    version: <SHA de 40 caractères du commit de release approuvé>
```

Jamais `main` ni une branche. Le serveur et la collection doivent parler le même protocole : une requête d'un autre protocole est refusée avant toute mutation.

## Rôle `ny.vps.app`

| Variable | Obligatoire | Description |
| --- | --- | --- |
| `app_application` | oui | Clé enregistrée sur le VPS : minuscules, chiffres, tirets, 32 caractères au plus, sans suffixe `-prod`, `-staging` ou `-pr-<n>` |
| `app_environment` | oui | `prod`, `staging` ou `preview` |
| `app_pull_request` | preview seulement | Numéro de PR ; refusé pour prod et staging |
| `app_generation` | apply, plan | Entier croissant pour une même instance |
| `app_operation` | non | `apply` (défaut), `plan`, `destroy`, `renew`, `status`, `logs` |
| `app_compose_template` | apply, plan | Modèle Jinja du Compose de l'application |
| `app_routes` | non | Routes HTTP ; `[]` par défaut |
| `app_storage_budget_gib` | apply, plan | Budget de croissance des données de l'instance, en GiB |
| `app_reopen` | non | `true` pour recréer une preview fermée |
| `app_logs_tail` | non | Lignes de journal pour `logs` (1 à 1000, défaut 100) |
| `app_render_output` | non | Fichier local `0600` où écrire la livraison rendue, pour inspection |

En mode check (`--check`), `apply` devient `plan` : aucune réservation. `destroy` et `renew` ne sont pas simulés et répondent `not_verified` sans rien envoyer.

L'identité est celle du compte SSH de déploiement : un compte nonprod pour staging et previews, un compte distinct pour la production. La requête ne choisit jamais son identité.

## Requête

| Champ | Opérations | Règle |
| --- | --- | --- |
| `protocol` | toutes | `1` |
| `operation` | toutes | `apply`, `plan`, `destroy`, `renew`, `status`, `logs` |
| `application`, `environment` | toutes | Identité de l'instance |
| `pull_request` | preview | Entier de 1 à 2147483647 |
| `generation` | apply, plan, destroy, renew | Entier positif |
| `compose`, `routes`, `storage_budget_gib`, `reopen` | apply, plan | Refusés pour les autres opérations |
| `tail` | logs | 1 à 1000 |

Le rôle remplit ces champs ; un champ inconnu ou une clé JSON dupliquée refuse la requête. Taille maximale : 1 MiB.

## Sous-ensemble Compose

Sections acceptées : `services` (1 à 16) et `volumes` (16 au plus, déclarés `{}`). Tout le reste est refusé : `build`, `include`, `extends`, `env_file`, `networks`, `ports`, `privileged`, `cap_add`, `devices`, `network_mode`, `pid`, `ipc`, `container_name`, `deploy`, etc.

| Champ de service | Règle |
| --- | --- |
| `image` | Obligatoire, par digest : `registre/image:tag@sha256:<64 hex>` |
| `cpus` | Obligatoire, > 0 et ≤ 3 |
| `mem_limit` | Obligatoire, ≤ 6 GiB (`384m`, `1g`, ou octets) |
| `memswap_limit` | Égal à `mem_limit` s'il est présent ; le contrôleur l'impose |
| `pids_limit` | Obligatoire, 1 à 1024 |
| `environment` | Dictionnaire de chaînes ; `$` est échappé, aucune interpolation Compose |
| `x-vps-required-environment` | Noms de variables qui doivent être présentes et non vides |
| `healthcheck` | Obligatoire pour un service durable : `test` en forme `CMD`/`CMD-SHELL`, `interval`, `timeout`, `start_period` (`ms`, `s`, `m`), `retries` 1 à 10 |
| `depends_on` | Forme longue : `service_healthy` vers un service, `service_completed_successfully` vers un job ; pas de cycle |
| `volumes` | `nom:/chemin[:ro]` ou forme longue `type: volume` ; uniquement les volumes déclarés par l'instance |
| `command`, `entrypoint`, `user`, `working_dir`, `read_only` | Libres dans leur type |
| `restart` | `no`, `on-failure` ou `unless-stopped` (défaut) |
| `x-vps-init` | `true` pour un job d'initialisation |

Une seule réplique par service. L'admission additionne **tous** les services, jobs compris.

Le contrôleur ajoute à chaque service : `cap_drop: [ALL]`, `security_opt: [no-new-privileges:true]`, journaux `json-file` 10 Mo × 3, labels `vps.platform.*`, réseau et volumes nommés `vps-<instance>`. Puis il vérifie ces valeurs sur les conteneurs réels avec `docker inspect` avant de déclarer l'instance prête.

### Conséquences pratiques

- Sans aucune capacité, une image qui démarre en root puis change d'utilisateur échoue. Déclarer `user:` explicitement (l'exemple lance Postgres en `70:70`).
- L'outil du healthcheck doit exister dans l'image. Pour Postgres, tester en TCP (`pg_isready --host 127.0.0.1`) : pendant l'initialisation, le serveur temporaire écoute sur le socket Unix seulement, et un test sur le socket déclarerait la base prête trop tôt.
- Chaque service a 120 s pour devenir sain, chaque job 300 s pour se terminer.

### Jobs d'initialisation

Un service `x-vps-init: true` s'exécute avec `docker compose run --rm` avant les services qui l'attendent, **à chaque livraison**. Il doit donc être idempotent, par exemple charger les fixtures seulement dans une base vide. Il n'a pas besoin de healthcheck et ne reçoit pas de route.

## Routes et noms

Tant que `vps_domain` est vide sur le VPS, toute route est refusée : l'instance reste accessible par ses seuls ports loopback, et `http_status` vaut `unconfigured`.

Une instance a au plus une route, de nom imposé :

| Instance | Nom |
| --- | --- |
| `exemple-prod` | `exemple.<domaine>` |
| `exemple-staging` | `exemple-staging.<domaine>` |
| `exemple-pr-42` | `exemple-pr-42.<domaine>` |

```yaml
app_routes:
  - {hostname: exemple-pr-42.apps.example.net, service: web, port: 3000}
```

`port` est le port du conteneur. Le contrôleur loue un port `127.0.0.1` dans 20000–29999, le conserve aux mises à jour et ne le partage jamais. La route est publiée après la readiness locale, en HTTPS seulement.

## Générations

- Chaque `apply` porte une génération plus grande que la précédente de l'instance. Une génération plus ancienne est refusée (`stale delivery generation`).
- Rejouer la même génération avec la même livraison ne change rien (`delivery already current`). La même génération avec une livraison différente est refusée.
- `destroy` laisse un tombstone. Une preview fermée ne se recrée qu'avec `app_reopen: true` et une génération supérieure au tombstone : une livraison en retard ne ressuscite pas une PR fermée.

## Réponse

Le rôle affiche les champs publics : `instance`, `status`, `reason` et, selon le cas, `local_health`, `http_status`, `disk_warning`, `runtime_present`, `logs`, `occupants`, `audit`. Jamais la requête, le Compose ni les secrets.

| Statut | Signification |
| --- | --- |
| `ready` | Livraison saine localement ; `http_status` indique l'accessibilité publique |
| `planned` | Admissible maintenant ; `apply` revérifie sous le verrou |
| `refused` | Refus avant mutation ; `reason` explique, la tâche échoue |
| `failed` | Échec après réservation ; la place reste réservée jusqu'à intervention ou expiration |
| `destroyed` | Ressources de la preview vérifiées absentes |
| `renewed` | Expiration de la preview repoussée de 72 h |
| `logs` | Journaux de l'instance, bornés à 256 KiB |
| `not_verified` | Mode check : `destroy` ou `renew` non simulé |

Pour `status`, `status` reprend l'état enregistré (`preparing`, `ready`, `failed`, `deleting`) ou `absent`, avec `runtime_present`.

Refus de la troisième preview :

```json
{
  "status": "refused",
  "reason": "global preview limit reached; no existing preview is evicted",
  "occupants": [
    {"instance": "alpha-pr-1", "status": "ready", "expires_at": 1791800000.0},
    {"instance": "beta-pr-7", "status": "ready", "expires_at": 1791900000.0}
  ]
}
```

`expires_at` est un horodatage Unix. `audit: unavailable` signale que la décision a été appliquée mais que sa ligne d'audit n'a pas pu être écrite.

## Previews

- Expiration 72 h après la dernière livraison réussie ou le dernier `renew`. Un échec ne renouvelle pas.
- `renew` n'accepte qu'une preview `ready`, avec une génération au moins égale à sa génération courante.
- À la fermeture de la PR, le dépôt applicatif lance `destroy` : route retirée, conteneurs, réseau et volumes de l'instance supprimés, puis place libérée.
- Une nouvelle preview part d'un volume neuf ; une mise à jour de la même PR garde ses données.

## Secrets et journaux

- Les valeurs viennent d'un fichier privé hors Git (`-e @/chemin/prive.yml`), jamais d'un `.env` global.
- Le rôle masque le rendu et la requête (`no_log`, `diff: false`). Le Compose normalisé, qui contient les valeurs, reste privé sur le VPS (`0600`).
- `logs` renvoie ce que l'application écrit : une application qui journalise ses secrets les expose. Le contrôleur le rappelle dans `reason`.

## Commandes

Depuis la racine d'un dépôt applicatif :

```bash
ansible-galaxy collection install -r deploy/ansible/requirements.yml

ansible-playbook -i deploy/ansible/inventory.yml deploy/ansible/deploy.yml \
  -e target_environment=preview -e pull_request_number=42 -e release_generation=7 \
  -e exemple_web_image=registry.example.net/exemple/web@sha256:<digest> \
  -e @/chemin/prive/exemple-preview.yml

# Plan sans réservation
ansible-playbook ... --check

# Fermeture de la PR
ansible-playbook -i deploy/ansible/inventory.yml deploy/ansible/deploy.yml \
  -e target_environment=preview -e pull_request_number=42 -e release_generation=8 -e operation=destroy
```

L'inventaire de l'application vérifie l'empreinte du serveur (`StrictHostKeyChecking=yes` et `known_hosts` du dépôt), comme celui du socle.
