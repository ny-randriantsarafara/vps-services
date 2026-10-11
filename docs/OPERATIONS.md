# Exploitation

Toutes les commandes partent de la racine du dépôt, après `make setup`. Celles qui touchent le serveur exigent `TARGET=vps-d9d9aca9`.

## 1. Vérifier l'empreinte du serveur hors bande

Les inventaires imposent `StrictHostKeyChecking=yes` et le fichier `inventories/production/known_hosts`. Ansible refuse donc de se connecter tant que l'empreinte n'a pas été vérifiée et inscrite. Ne jamais contourner avec `StrictHostKeyChecking=no`.

1. Ouvrir la console KVM du VPS depuis l'espace client OVH et y lire l'empreinte réelle :

   ```bash
   ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
   ```

2. Sur le poste, récupérer la clé annoncée par le réseau et comparer les deux empreintes :

   ```bash
   ssh-keyscan -t ed25519 51.210.10.127 > /tmp/vps-host-key
   ssh-keygen -lf /tmp/vps-host-key
   ```

3. Seulement si elles sont identiques, enregistrer la clé dans l'inventaire. Une clé d'hôte est publique et peut être commitée :

   ```bash
   cp /tmp/vps-host-key inventories/production/known_hosts
   ```

Chaque dépôt applicatif fait de même dans `deploy/ansible/known_hosts`. Après une réinstallation du VPS, l'empreinte change : recommencer la vérification, ne pas supprimer la ligne à l'aveugle.

## 2. Accès initial

L'image Debian d'OVH fournit le compte `debian` avec la clé `~/.ssh/id_ed25519.pub` injectée, mais exige un changement de mot de passe qui bloque actuellement SSH. Le résoudre dans la console KVM OVH, en se connectant avec le mot de passe reçu d'OVH. Aucun mot de passe n'entre dans ce dépôt.

Renseigner ensuite les clés publiques de l'administrateur dans `inventories/production/group_vars/all.yml` :

```yaml
vps_admin_public_keys:
  - "ssh-ed25519 AAAA... poste-principal"
```

## 3. Bootstrap

Garder une session `debian` ouverte dans un autre terminal pendant toute l'opération.

```bash
make bootstrap TARGET=vps-d9d9aca9
```

Chaque étape ouvre sa propre connexion ; un échec arrête la suite avant tout retrait d'accès :

1. En `debian` : vérifier Debian 13, créer `vps-admin` (clés seulement, sudo validé par `visudo`).
2. En `vps-admin` : connexion indépendante et `sudo` effectif.
3. Durcissement SSH : `/etc/ssh/sshd_config.d/10-vps-platform.conf`, validé par `sshd -t` avant reload ; un fichier refusé est retiré sans reload.
4. Nouvelle connexion `vps-admin` après durcissement.
5. Retrait des clés du compte `debian` (`vps_revoke_initial_user_key`).

Vérifier ensuite depuis le poste : `ssh vps-admin@51.210.10.127` fonctionne, `ssh root@51.210.10.127` et l'authentification par mot de passe sont refusés.

## 4. Récupération OVH

Si SSH devient inaccessible :

- **Console KVM** (espace client OVH, VPS, KVM) : connexion locale, indépendante de SSH et du firewall. Corriger ou retirer `/etc/ssh/sshd_config.d/10-vps-platform.conf`, puis `systemctl reload ssh` ; ou arrêter le firewall avec `systemctl stop vps-firewall`.
- **Mode rescue** : redémarrer le VPS en rescue depuis l'espace client, monter le disque système, puis corriger `authorized_keys`, le drop-in SSH ou désactiver `vps-firewall.service`. Redémarrer ensuite sur le disque normal.

La sauvegarde automatique OVH reste activée. Ne pas la restaurer pour réparer un accès : elle peut réintroduire l'ancienne stack. Le socle ne restaure aucune application depuis cette sauvegarde.

## 5. Socle

```bash
make plan TARGET=vps-d9d9aca9       # simulation --check --diff
make platform TARGET=vps-d9d9aca9
make platform TARGET=vps-d9d9aca9   # deuxième passage : aucun changement attendu
```

Sur un hôte vierge, `make plan` peut signaler des tâches qui dépendent de paquets pas encore installés : c'est une aide à la relecture, pas une preuve.

`platform.yml` installe hôte, SSH, firewall, Docker, Caddy et le contrôleur, puis refait une connexion après les changements SSH et firewall. Il ne démarre aucune application.

Contrôles depuis une **autre machine**, en IPv4 puis en IPv6 :

```bash
nc -vz 51.210.10.127 22 && nc -vz 51.210.10.127 80 && nc -vz 51.210.10.127 443
nc -vz -w 3 51.210.10.127 5432    # doit échouer, comme tout autre port
nc -6 -vz 2001:41d0:404:200::74ec 443
nc -6 -vz -w 3 2001:41d0:404:200::74ec 5432
```

Pour prouver le filtrage `DOCKER-USER`, publier temporairement un conteneur de test sur un port interdit, vérifier qu'il reste injoignable de l'extérieur, puis le supprimer. Un contrôle de fichier ne remplace pas cet essai.

## 6. Enregistrer une application

Déclarer les comptes dans `vps_deploy_accounts` : un compte nonprod pour staging et previews, un compte distinct pour la production.

```yaml
vps_deploy_accounts:
  exemple-nonprod:
    application: exemple
    environments: [staging, preview]
    public_keys: ["ssh-ed25519 AAAA... ci@exemple"]
  exemple-prod:
    application: exemple
    environments: [prod]
    public_keys: ["ssh-ed25519 AAAA... release@exemple"]
```

```bash
make register-app TARGET=vps-d9d9aca9
```

Chaque compte reçoit ses clés et une seule règle sudo, `/usr/local/sbin/vpsctl request`, validée par `visudo`. Aucun groupe `docker`. La politique `/etc/vps-platform/policy.json` est réécrite ; aucun conteneur n'est lancé.

## 7. Commandes `vpsctl`

Réservées aux administrateurs (`vps-admin` et `root`) :

```bash
ssh vps-admin@51.210.10.127 sudo vpsctl status
ssh vps-admin@51.210.10.127 sudo vpsctl previews list
ssh vps-admin@51.210.10.127 sudo vpsctl logs --instance exemple-pr-42 --tail 100
ssh vps-admin@51.210.10.127 sudo vpsctl previews renew --instance exemple-pr-42
ssh vps-admin@51.210.10.127 sudo vpsctl previews destroy --instance exemple-pr-42
ssh vps-admin@51.210.10.127 sudo vpsctl cleanup
```

Toutes répondent en JSON ; code de sortie 2 pour un refus, 1 pour un échec. `status` liste les instances, les objets Docker non suivis (`untracked_instances`), l'espace libre et `disk_warning` sous 15 GiB. `previews destroy` est destructif pour les seules données de cette preview ; prod et staging sont refusés. `cleanup` supprime les previews expirées ou abandonnées, comme le timer.

Le timer `vps-platform-maintenance.timer` lance `status` puis `cleanup` toutes les cinq minutes :

```bash
systemctl list-timers vps-platform-maintenance.timer
journalctl -u vps-platform-maintenance --since today
```

## 8. Audit et état

```bash
sudo tail -n 20 /var/lib/vps-platform/audit.jsonl
sudo cat /var/lib/vps-platform/registry.json
```

L'audit contient date, acteur, opération, génération, digests, instance, statut et motif ; jamais de secret. Le registre ne contient pas de secret non plus. Les fichiers `/srv/vps/apps/<application>/<env>/compose.json` en contiennent : ne pas les copier dans un ticket ou une CI.

## 9. Politique

`/etc/vps-platform/policy.json` est généré par Ansible depuis l'inventaire : `domain` (`vps_domain`), `preview_limit` (`vps_preview_limit`), `accounts` (`vps_deploy_accounts`) et `administrators`. Une modification manuelle est écrasée au prochain `platform` ou `register-app`.

Les autres clés gardent les valeurs par défaut du contrôleur (`vps_platform/policy.py`) :

| Clé | Défaut | Effet |
| --- | --- | --- |
| `preview_ttl_seconds` | 259200 | Expiration d'une preview (72 h) |
| `preparing_lease_seconds` | 900 | Bail d'une livraison en cours avant nettoyage |
| `lock_timeout_seconds` | 600 | Attente maximale du verrou |
| `budgets` | prod 1,5/3072, staging 0,5/1024, preview 1/2048 | vCPU / MiB par environnement |
| `preview_instance_budget` | 0,5 / 1024 | Plafond d'une preview |
| `minimum_free_memory_mib` | 512 | Marge de `MemAvailable` après une hausse de réservation |
| `minimum_free_disk_gib` | 10 | Réserve disque ; en dessous, admissions gelées |
| `disk_warning_gib` | 15 | Seuil d'avertissement de `status` |
| `image_growth_reserve_gib` | 2 | Place prévue pour les pulls |
| `minimum_free_inode_ratio` | 0.05 | Part d'inodes libres exigée |
| `port_start`, `port_end` | 20000, 29999 | Ports loopback loués |

Baisser `vps_preview_limit` sous le nombre de previews présentes bloque les créations sans en supprimer. L'augmenter ne relève ni le CPU, ni la mémoire, ni le disque.

## 10. Caddy

- Les applications sont servies sur `:443` uniquement. Le port 80 reste à l'HTTPS automatique de Caddy : défis ACME et redirection 308 vers HTTPS.
- Un nom inconnu reçoit un 404 neutre.
- Administration par `/run/caddy/admin.sock`, inaccessible aux conteneurs et aux comptes de déploiement.
- `vpsctl` écrit la configuration complète dans `/etc/caddy/vps-platform.json` puis la charge ; un redémarrage de Caddy reprend donc les routes actives.

```bash
journalctl -u caddy --since "1 hour ago"
sudo cat /etc/caddy/vps-platform.json
```

## 11. Diagnostics

```bash
journalctl -u docker -u caddy -u vps-firewall --since today
sudo iptables -S VPS-INPUT && sudo ip6tables -S VPS-INPUT
sudo iptables -S DOCKER-USER && sudo ip6tables -S DOCKER-USER
sudo docker compose -p vps-exemple-pr-42 ps
sudo docker ps -a --filter label=vps.platform.instance=exemple-pr-42
sudo docker inspect <conteneur>
df -h / && df -i /
```

### Objets non suivis ou registre ambigu

Un objet Docker marqué `vps.platform.*` sans entrée de registre, ou un registre illisible, bloque les admissions (`untracked runtime objects block admission`, `registry unreadable; operator reconciliation required`). Pour réparer :

1. Sauvegarder `registry.json` hors du répertoire d'état, en `0600`.
2. Identifier le périmètre exact avec `docker ps -a`, `docker volume ls` et `docker network ls` filtrés par `label=vps.platform.instance=<instance>`.
3. Supprimer uniquement ces objets, ou corriger l'entrée du registre, puis relancer `vpsctl status`.

Jamais de `docker system prune --volumes` ni de suppression globale : les données de production et de staging seraient perdues.
