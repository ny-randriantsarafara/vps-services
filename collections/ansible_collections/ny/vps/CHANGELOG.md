# Changelog de `ny.vps`

## 1.3.1

- La garde d’onboarding s’ouvre aussi quand Home Assistant a terminé toutes les étapes : il ne sert alors plus `/api/onboarding` et répond le 404 exact `404: Not Found`. Tout autre 404 reste fermé.

## 1.3.0

- Noms supplémentaires par instance autorisés uniquement par la politique administrateur ; garde privée d’onboarding fermée en cas d’erreur et blocage permanent de la création publique d’administrateur.
- `vpsctl ingress refresh` réconcilie les objets et republie les routes sous verrou, sans nouvelle génération ni redémarrage applicatif ; maintenance toutes les cinq minutes et aucun reload si la configuration reste identique.
- `stop_grace_period` accepté entre 1 et 300 secondes et contrôlé dans le runtime Docker.

## 1.2.0

- Budgets d'admission réglables depuis l'inventaire : `controller_budgets` et `controller_preview_instance_budget` (playbooks : `vps_budgets`, `vps_preview_instance_budget`). Défauts inchangés.

## 1.1.0

- Plusieurs routes par instance : le nom principal et `<préfixe>.<nom principal>`, chacun une fois ; toutes sondées avant publication et pour `http_status`. Protocole inchangé (version 1).

## 1.0.0

- Protocole de requête version 1 entre les dépôts applicatifs et `vpsctl`.
- Rôles du socle : `host`, `ssh`, `firewall`, `docker`, `ingress`, `controller`.
- Rôle applicatif `app` et module `deploy_instance`.
