# Home Assistant sur le VPS

Objectif autorisé : instance Container sur `vps-d9d9aca9.vps.ovh.net`, domaine exact
`home-assistant.nyhasinavalona.com`, dépôt personnel privé et guide du hub.

## Contraintes

- Conserver les instances my-media, DNS voisins, trois sous-modules et données existantes.
- Configuration/runtime/secrets/sauvegardes distincts du Git applicatif.
- Aucun onboarding administrateur public : tunnel SSH initial, garde fermée en cas d'erreur.
- Aucune intégration Tapo/SmartThings annoncée connectée sans preuve ni abonnement souscrit.
- Déploiement par `ny.vps.app` ; image officielle par digest, réseau isolé, loopback seulement.

## Exécution

- [ ] Socle : tests rouges puis autorisations exactes de noms par instance, arrêt propre,
  garde d'onboarding pilotée par l'administrateur et refresh ingress sous verrou.
  Vérifier les refus hors périmètre, l'état fermé en cas d'erreur, la protection persistante
  de la création d'administrateur, les limites et `make check`.
- [ ] Application : créer le dépôt autonome, déploiement Ansible, image épinglée,
  config persistante, tunnel initial et sauvegarde/restauration ciblées.
  Déployer après revue du socle ; contrôler TLS, 403 public, onboarding privé,
  limites, redémarrage et persistance, puis état my-media.
- [ ] Documentation : guide appareils avec sources officielles, guide agents et
  référence documentaire dans le hub. Publier le dépôt privé puis vérifier sa visibilité
  et sa révision. Rapporter les dernières actions humaines sans inventer de compte.
