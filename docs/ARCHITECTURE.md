# Architecture

Un seul VPS, sans orchestrateur. Ansible configure l'hôte depuis le poste de l'opérateur ; chaque application se déploie depuis son propre dépôt en appelant une commande locale du serveur, `vpsctl`, qui décide de l'admission et applique Compose et les routes Caddy.

```text
poste opérateur / dépôt applicatif                     VPS Debian 13
──────────────────────────────────                     ─────────────────────────────────────────────
ansible-playbook (ny.vps.app)                          sudo -n /usr/local/sbin/vpsctl request
  rend compose.yml.j2 localement      ── SSH ──▶        │  verrou flock, registre JSON
  module deploy_instance (JSON stdin)                   │  admission : places, budgets, mémoire, disque
                                                        ├─▶ docker compose (projet vps-<instance>)
                                                        └─▶ Caddy (socket Unix) : route après readiness
```

## Composants

| Composant | Rôle Ansible | Résultat sur l'hôte |
| --- | --- | --- |
| Hôte | `ny.vps.host` | Administrateur `vps-admin` par clés, mises à jour de sécurité, journal borné à 500 MiB |
| SSH | `ny.vps.ssh` | Drop-in validé par `sshd -t` : pas de root, clés seulement, pas d'authentification interactive |
| Firewall | `ny.vps.firewall` | `vps-firewall.service` : chaînes `VPS-INPUT` et `DOCKER-USER`, IPv4 et IPv6, ports 22/80/443 |
| Docker | `ny.vps.docker` | Docker Engine 29.8.2, Compose 5.5.1, dépôt APT signé, rotation `json-file` 10 Mo × 3 |
| Ingress | `ny.vps.ingress` | Caddy 2.11.7, administration par `/run/caddy/admin.sock`, configuration `/etc/caddy/vps-platform.json` |
| Contrôleur | `ny.vps.controller` | `vpsctl`, politique `/etc/vps-platform/policy.json`, comptes de déploiement, timer de maintenance |
| Application | `ny.vps.app` | Utilisé par les dépôts applicatifs ; ne s'exécute pas dans `platform.yml` |

`platform.yml` ne démarre aucun conteneur applicatif. `register-app.yml` crée les comptes de déploiement et réécrit la politique, sans lancer de stack.

## Le contrôleur `vpsctl`

Programme Python (bibliothèque standard) installé root-owned dans `/usr/local/lib/vps-platform/vps_platform`, lancé par `/usr/local/sbin/vpsctl`. Les chemins de politique et d'état sont fixes : ni la requête ni les arguments ne peuvent les changer.

- **Identité** : l'acteur vient de `SUDO_UID`/`SUDO_USER`, jamais de la requête. La politique associe chaque compte de déploiement à une application et à ses environnements ; un compte de production ne sert qu'à la production.
- **Verrou** : toute requête prend `/var/lib/vps-platform/controller.lock` (`flock`) pour l'opération entière. L'attente est bornée à `lock_timeout_seconds` (600 s) ; au-delà, la requête est refusée.
- **Registre** : `/var/lib/vps-platform/registry.json`, écrit atomiquement en `0600`. Il contient instances, générations, digests d'images, budgets réservés, ports loués, routes, échéances et tombstones. Aucune valeur secrète.
- **Fichiers privés** : `/srv/vps/apps/<application>/<env>/compose.json` (Compose normalisé, secrets inclus) et `previous-compose.json`, en `0600` dans des répertoires `0700`.
- **Audit** : `/var/lib/vps-platform/audit.jsonl`, une ligne par requête : date, acteur, opération, génération, digests, instance, statut, motif. Jamais de secret ni de Compose complet.

## Admission

Sous le verrou, dans cet ordre :

1. Valider identité, protocole, champs, images par digest, environnement requis, volumes et routes (sous-ensemble décrit dans [APP-CONTRACT](APP-CONTRACT.md)).
2. Réconcilier le registre avec les objets Docker marqués `vps.platform.*`. Un objet non suivi ou ambigu bloque les nouvelles admissions, sans suppression opportuniste.
3. Compter les places : toute preview enregistrée, quel que soit son état, occupe une place. La mise à jour de la même PR n'en consomme pas une seconde. La troisième preview est refusée avec la liste des occupants et leur échéance.
4. Additionner les budgets de l'environnement, en remplaçant l'ancienne réservation par le maximum de l'ancienne et de la nouvelle tant que les anciens conteneurs existent.
5. Vérifier la mémoire : une hausse de réservation doit laisser au moins 512 MiB de `MemAvailable`.
6. Vérifier le disque : espace libre ≥ 10 GiB de réserve + budgets de stockage déclarés + 2 GiB de croissance d'images, et au moins 5 % d'inodes libres. Après le pull, l'espace est mesuré de nouveau : il doit encore couvrir la réserve plus le budget de stockage de l'instance, sinon rien ne démarre. Une image plus grosse que prévu est ainsi refusée avant d'écrire des données.
7. Réserver dans le registre, puis seulement créer les ressources.

| Enveloppe | CPU | Mémoire |
| --- | --- | --- |
| Toutes les productions | 1,5 vCPU | 3 GiB |
| Tous les stagings | 1 vCPU | 1 GiB |
| Toutes les previews | 2 vCPU | 2 GiB |
| Une preview | 1 vCPU | 1 GiB |

Ces plafonds sont des règles d'admission : ils ne réservent pas matériellement le CPU et ne garantissent pas les performances. Le disque est surveillé, pas soumis à des quotas : une base peut dépasser son budget déclaré.

## Livraison

`pull` → réserve disque → services démarrés dans l'ordre des dépendances (`up --no-deps --wait`), jobs d'initialisation en `run --rm` → contrôle des valeurs effectives par `docker inspect` (limites, `cap_drop: ALL`, `no-new-privileges`, réseau de l'instance, montages, ports loopback) → santé Docker → probe HTTP loopback de chaque route → publication des routes Caddy → probe public. Les conteneurs de services retirés de la livraison sont supprimés.

Une mise à jour remplace les conteneurs : une interruption est possible, aucun zéro downtime n'est promis. Un échec laisse l'instance en `failed` avec sa réservation, sans restauration automatique.

## Isolation

| Ressource | Règle |
| --- | --- |
| Projet Compose | `vps-<instance>`, pas de `container_name` |
| Réseau | Bridge `vps-<instance>`, jamais partagé |
| Volumes | `vps-<instance>-<nom>`, déclarés par l'instance ; aucun bind mount |
| Conteneurs | `cap_drop: ALL`, `no-new-privileges`, limites CPU/mémoire/swap/PID, pas de privilège ni namespace hôte |
| Ports | `127.0.0.1:<port loué>` uniquement, plage 20000–29999 attribuée par le contrôleur |
| HTTP | Nom principal dérivé de l'instance et noms d'un label au-dessous (`cms.<instance>…`) ; route inconnue : 404 neutre |

Caddy écoute les applications sur `:443` seulement. Le port 80 reste à son HTTPS automatique : défis ACME et redirection vers HTTPS. Aucune application n'est servie en clair.

Docker partage le noyau du VPS : ce modèle convient à des applications et contributeurs de confiance, pas à l'exécution de PR hostiles.

## Cycle de vie

| Statut | Signification | Place de preview |
| --- | --- | --- |
| `preparing` | Réservation écrite, livraison en cours (bail de 15 min) | Occupée |
| `ready` | Livraison saine localement | Occupée |
| `failed` | Livraison ou suppression incomplète, réservation conservée | Occupée |
| `deleting` | Suppression en cours | Occupée |

Le timer `vps-platform-maintenance.timer` lance `vpsctl status` puis `vpsctl cleanup` toutes les cinq minutes. Le nettoyage ne concerne que les previews expirées, abandonnées en `preparing`/`failed` après leur bail, ou restées en `deleting`. Production et staging ne sont jamais supprimés par ce cycle.

## Hors périmètre

Pas de Kubernetes, de Supabase commun, de daemon ou d'API HTTP de déploiement, de build sur le VPS, ni de restauration automatique des anciennes applications. Les sauvegardes applicatives appartiennent à chaque application.
