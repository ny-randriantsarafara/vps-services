# Collection `ny.vps`

Socle d'un VPS unique et contrat de déploiement des applications.

| Élément | Rôle |
| --- | --- |
| `ny.vps.host` | Debian 13, administrateur non-root, mises à jour de sécurité, journal borné |
| `ny.vps.ssh` | Durcissement SSH validé par `sshd -t` |
| `ny.vps.firewall` | Règles IPv4/IPv6 `INPUT` et `DOCKER-USER`, restaurées au démarrage |
| `ny.vps.docker` | Docker Engine et Compose depuis le dépôt APT signé, versions épinglées |
| `ny.vps.ingress` | Caddy sur l'hôte, administration par socket Unix |
| `ny.vps.controller` | Commande `vpsctl`, politique d'admission, comptes de déploiement |
| `ny.vps.app` | Rôle des dépôts applicatifs : rendu Compose et requête au contrôleur |
| `ny.vps.deploy_instance` | Module qui transmet une requête du protocole version 1 |

Le contrat applicatif est décrit dans `docs/APP-CONTRACT.md` du dépôt `vps-services`.
