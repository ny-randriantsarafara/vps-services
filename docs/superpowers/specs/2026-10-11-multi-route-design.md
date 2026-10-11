# Routes multiples, domaine `apps` et comptes `my-media`

Date : 11 octobre 2026. Statut : approuvé ; demandé par la CI/CD de `my-media` (spec `docs/superpowers/specs/2026-10-11-cicd-design.md` du dépôt `my-media`).

## Besoin

The Media publie deux noms par instance : le site et Directus. L'aperçu des brouillons lit sur le site le cookie de session posé par Directus. Ce cookie doit donc couvrir les deux noms, sans couvrir les autres instances : une preview exécute du code non relu et ne doit jamais recevoir le cookie de la production.

## Décision

- Une instance publie son nom principal `<label>.<domaine>` et des noms secondaires `<préfixe>.<label>.<domaine>`, où `<préfixe>` est un label `[a-z][a-z0-9]{0,31}`. Chaque nom au plus une fois, 16 routes au plus.
- Deux instances ont des labels distincts : leurs ensembles de noms sont disjoints, par construction, sans liste de noms réservés.
- Un cookie `Domain=<label>.<domaine>` couvre le site et ses noms secondaires, mais aucune autre instance.
- Toutes les routes de l'instance sont sondées en loopback avant publication. `http_status` vaut `ready` seulement si toutes répondent publiquement.
- Domaine : `apps.nyhasinavalona.com`. Wildcard Cloudflare `*.apps` en A/AAAA, sans proxy : il couvre plusieurs niveaux, et Caddy obtient un certificat par nom.
- Comptes : `my-media-nonprod` (`staging`, `preview`) et `my-media-prod` (`prod`), une clé ed25519 dédiée chacun. Les clés privées sont dans les environnements GitHub de `my-media`.

## Écartés

- `<label>-<suffixe>` (`my-media-pr-42-cms`). Le seul parent commun du site et du CMS serait le domaine entier : le cookie de la production fuirait vers les previews. Il faudrait aussi réserver des suffixes dans les noms d'application pour éviter les collisions.
- Une instance par service : le site serait séparé de sa base, et une preview consommerait deux places.
