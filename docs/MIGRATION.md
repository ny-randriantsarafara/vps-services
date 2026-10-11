# Migration depuis la stack Supabase

Ce dépôt hébergeait une stack Supabase commune (Postgres, Redis, Kong, Studio, Supavisor…) derrière Caddy, déployée par GitHub Actions à chaque push sur `main`. Le VPS a été réinstallé en Debian 13 : cet état a disparu et **n'est pas une liste d'applications à redéployer**.

## Ce qui a été retiré

| Héritage | Remplacement |
| --- | --- |
| `docker-compose.yml`, `volumes/`, `caddy/Caddyfile` | Instances Compose par application, routes validées par `vpsctl` |
| `.env.example`, `scripts/sync-env-*.sh` | Secrets privés par instance, fournis par chaque application |
| `.github/workflows/deploy.yml` (push sur `main`) | `validate.yml`, sans secret ni déploiement |
| Workflows réutilisables `build-image.yml`, `deploy-compose.yml`, `deploy-service.yml` | Rôle `ny.vps.app` installé à un SHA de release |
| `docs/DATABASE-CONNECTION.md`, tunnels SSH vers Postgres/Redis | Chaque application possède sa base, isolée par instance |
| Cibles `make up`, `up-all`, `tunnel`, `sync-env` | `make setup`, `check`, `plan`, `bootstrap`, `platform`, `register-app` |

Aucune ancienne application n'est restaurée, ni depuis Git ni depuis la sauvegarde OVH.

## Avant le premier push de cette refonte

Le retrait des fichiers ne neutralise pas les appelants existants. Avant tout push susceptible de déclencher un workflow :

1. **Inventorier les appelants** des workflows réutilisables : rechercher `ny-randriantsarafara/vps-services/.github/workflows/` dans les dépôts applicatifs. Un appelant épinglé sur un ancien SHA continue de fonctionner après la refonte.
2. **Révoquer leurs accès** au VPS : supprimer les secrets `VPS_HOST`, `VPS_HOST_KEY`, `VPS_SSH_KEY` et `VPS_USER` de ce dépôt et des appelants. Ne pas installer la clé publique correspondante sur le nouveau serveur, et vérifier qu'elle n'est pas celle injectée par OVH pour le compte `debian`.
3. **Vérifier les déclencheurs** dans GitHub : `deploy.yml` se déclenchait sur push vers `main`. Désactiver explicitement les anciens workflows si un appelant reste actif. Ne pas compter sur `chore:` ou `[skip ci]`.
4. Planifier la migration de chaque application vers le contrat (voir [APP-CONTRACT](APP-CONTRACT.md)), sans déployer pendant cette étape.

## Dossier local d'origine

Le checkout `/Users/nrandriantsarafara/Works/sandbox/vps-services` contient un `.env` ignoré (ancienne configuration Supabase) :

- Avant remplacement, l'ancien working tree complet, `.env` compris, est archivé hors Git avec des permissions privées et une somme de contrôle, sans afficher son contenu.
- `.git`, le remote et les worktrees sont conservés ; seuls les fichiers du périmètre sont remplacés.
- Le `.env` n'entre jamais dans la nouvelle histoire. Un secret encore utile est replacé par sélection explicite, dans le fichier privé de l'application concernée.

Retour arrière local : extraire l'archive dans un dossier séparé, sans relancer ses anciennes commandes de déploiement.

## Ensuite

1. Résoudre l'accès initial et vérifier l'empreinte ([OPERATIONS](OPERATIONS.md), sections 1 à 3).
2. Valider le socle sur une VM Debian 13 jetable : premier passage, second passage sans changement, reboot, nouvelles connexions SSH, ports IPv4/IPv6 depuis une autre machine.
3. Provisionner le VPS réel après accord, puis mesurer `df`, la mémoire au repos et les règles réseau ; ajuster les enveloppes si nécessaire.
4. Enregistrer une application de test explicitement nommée et dérouler un cycle complet : deux previews, troisième refusée, mise à jour, fermeture, expiration.
5. Choisir un domaine dédié et son mode TLS : `apps.nyhasinavalona.com`, wildcard DNS sans proxy, certificats obtenus par Caddy (fait le 11/10/2026).
6. Adopter le contrat application par application. Production, sauvegardes hors VPS et exercice de restauration sont propres à chaque application.

Retour arrière serveur : maintenance explicite du socle. La sauvegarde OVH est conservée, mais sa restauration réintroduirait l'ancienne stack.
