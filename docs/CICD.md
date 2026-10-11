# CI/CD

## Ce dépôt : validation seulement

`.github/workflows/validate.yml` s'exécute sur push, pull request et déclenchement manuel. Il ne possède aucun secret VPS, ne se connecte à aucun serveur et ne provisionne rien.

| Étape | Commande |
| --- | --- |
| Outils | `make setup` : `.venv` et `requirements-dev.lock`, installé avec `--require-hashes` |
| Gates | `make check` |

`make check` lance `scripts/check.sh` :

1. `ruff check` et `ruff format --check` ;
2. tous les tests unitaires (`python -m unittest discover -s tests`) ;
3. `ansible-lint --offline` au profil production ;
4. `ansible-playbook --syntax-check` de `bootstrap`, `platform`, `register-app` et du playbook d'exemple ;
5. build de la collection `ny.vps` ;
6. `git diff --check` sur tous les fichiers suivis.

Les Actions sont épinglées par SHA complet (`actions/checkout` v5.1.0, `actions/setup-python` v6.3.0), avec `contents: read` et sans conserver le jeton de checkout. Les versions Python des outils sont fixées dans `requirements-dev.txt`, avec leurs hashes dans `requirements-dev.lock` :

```bash
uv pip compile requirements-dev.txt --python-version 3.13 --generate-hashes --output-file requirements-dev.lock
```

Le test Docker local (`make integration`) n'est pas exécuté en CI : il crée des conteneurs et ne se lance qu'à la demande.

Le socle se provisionne depuis le poste de l'opérateur (`make platform TARGET=...`), jamais sur un push.

## Dépôts applicatifs

Les déploiements commencent **manuellement**, depuis le poste, avec le playbook de l'application (voir [APP-CONTRACT](APP-CONTRACT.md)). Une automatisation GitHub n'est pas encore approuvée ; lorsqu'elle le sera, elle devra respecter ces règles :

- Un compte SSH de déploiement par usage : nonprod (staging et previews) et production, distincts. Sans groupe `docker` ni sudo général ; seulement `vpsctl request`.
- Clé privée et empreinte du serveur dans des secrets d'environnement GitHub restreints ; `known_hosts` vérifié, jamais `StrictHostKeyChecking=no`.
- Aucun secret pour les PR issues de forks. Un workflow privilégié n'exécute pas le code d'une PR non revue.
- Images construites en CI, publiées, puis transmises **par digest**. Aucun build sur le VPS.
- `release_generation` croissante, par exemple `github.run_id` ou un compteur de livraison. Une `concurrency` GitHub par application et PR aide à ordonner les jobs ; elle ne remplace ni le verrou du VPS ni le contrôle de génération.
- À la fermeture de la PR, `operation=destroy` avec une génération supérieure à la dernière livraison.
- La collection `ny.vps` est installée à un SHA de release revu ; chaque dépôt relit ses mises à jour.

Proposition à valider : staging après validation sur la branche principale de l'application, production par action manuelle à partir d'un digest validé en staging, previews sur les événements de PR.

Le socle ne contient aucun workflow qui reconstruit ou redéploie toutes les applications.
