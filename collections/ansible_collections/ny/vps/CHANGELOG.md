# Changelog de `ny.vps`

## 1.2.0

- Budgets d'admission réglables depuis l'inventaire : `controller_budgets` et `controller_preview_instance_budget` (playbooks : `vps_budgets`, `vps_preview_instance_budget`). Défauts inchangés.

## 1.1.0

- Plusieurs routes par instance : le nom principal et `<préfixe>.<nom principal>`, chacun une fois ; toutes sondées avant publication et pour `http_status`. Protocole inchangé (version 1).

## 1.0.0

- Protocole de requête version 1 entre les dépôts applicatifs et `vpsctl`.
- Rôles du socle : `host`, `ssh`, `firewall`, `docker`, `ingress`, `controller`.
- Rôle applicatif `app` et module `deploy_instance`.
