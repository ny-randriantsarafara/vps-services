# Refonte de VPS Services avec Ansible

Date : 11 octobre 2026. Statut : **proposition de conception à relire**.

Ce document définit le futur socle VPS et le contrat que chaque dépôt applicatif pourra utiliser. Il ne constitue pas une autorisation d'implémenter, de supprimer, de publier ou de déployer. Les exemples sont illustratifs : les fichiers, rôles et commandes futurs décrits ici n'existent pas encore.

## 1. Résultat attendu et décisions confirmées

Le dépôt `vps-services` initialise et configure le serveur. Chaque dépôt applicatif possède sa configuration Ansible pour provisionner et déployer son application. Le socle fournit des outils communs ; il ne contient pas de manifeste qui déploie toutes les applications.

Décisions humaines acquises :

- Un compte administrateur non-root, des clés SSH, un durcissement SSH, un firewall et Docker constituent la base.
- Production et staging sont deux environnements dédiés sur le même VPS.
- Chaque PR dispose de sa propre preview, lorsque l'admission la permet.
- Le plafond de previews est **global au VPS**, initialement deux et configurable.
- Une preview avec base de données utilise ses propres données de test, distinctes du staging et de la production.
- Le système doit rester adapté aux capacités du VPS, simple à comprendre et à débugger.
- Aucune ancienne application n'est restaurée automatiquement. Kubernetes et une stack Supabase commune ne sont pas requis.

Les choix techniques recommandés ci-dessous, notamment Compose, la distribution des rôles, l'admission et le cycle de vie automatique, restent à valider avec cette spécification. Leur présence dans le document ne les transforme pas en décisions déjà approuvées.

## 2. État de départ et limites de preuve

Les informations serveur et DNS suivantes ont été vérifiées dans le cadrage du 11 octobre et transmises à cette rédaction. Elles n'ont pas été revérifiées par connexion serveur pendant la rédaction.

| Élément | État transmis |
| --- | --- |
| VPS OVH | `vps-d9d9aca9.vps.ovh.net` |
| IPv4 / IPv6 | `51.210.10.127` / `2001:41d0:404:200::74ec` |
| Capacité annoncée | 4 vCPU, 8 GiB RAM, 75 Go de disque |
| OS | Réinstallation Debian 13 terminée, opération OVH `done`, 100 % |
| Accès initial | Clé publique locale `~/.ssh/id_ed25519.pub` injectée ; changement obligatoire du mot de passe initial bloque actuellement SSH avec `debian` |
| Sauvegarde OVH | Automatique activée, point disponible de la veille ; à conserver |
| Portfolio | `nyhasinavalona.com` et `www` sur GitHub Pages, HTTP 200 vérifié après nettoyage |
| DNS | Sept anciens noms applicatifs supprimés avec autorisation ; neuf entrées restantes, notamment les emails, préservées |

L'ancien serveur contenait des applications et une stack Supabase, avec environ 62 Go utilisés sur 74. La réinstallation a effacé cet état ; il n'est pas une liste de services à redéployer. La capacité réellement disponible du nouveau système de fichiers et la charge au repos restent à mesurer.

Lecture locale actuelle : dépôt distant `https://github.com/ny-randriantsarafara/vps-services`, HEAD `aa5f98ff82f7cab074b2fb0c3381aae4250bb242`. Le checkout de rédaction est en HEAD détaché. Aucun fetch, changement de branche ou publication n'a été effectué. Les fichiers existants confirment : Compose global Supabase, routes fixes Caddy et workflow `.github/workflows/deploy.yml` déclenché par push sur `main`.

Le dossier original `/Users/nrandriantsarafara/Works/sandbox/vps-services` contient, d'après l'inspection de cadrage, un `.env` ignoré. Son contenu privé n'a pas été lu. Ce fichier doit être sauvegardé hors Git avant tout remplacement local. Le checkout de rédaction n'en contient pas : l'absence ici ne dispense pas de protéger celui du dossier original.

**Preuve disponible à ce stade : conception et inspection de fichiers. Aucun provisioning, test d'idempotence, déploiement, scan réseau ou test de restauration sur le VPS n'est validé.**

## 3. Approches et recommandation

| Approche | Intérêt | Coût ou limite |
| --- | --- | --- |
| **Ansible + Compose par instance + outils communs versionnés** — recommandée | Serveur reproductible, applications autonomes, fichiers et commandes inspectables ; compatible avec un VPS unique | Petit mécanisme commun d'admission et de nettoyage à construire et vérifier |
| Ansible hôte + scripts Compose copiés dans chaque application | Premier démarrage rapide | Duplication du déploiement ; admission globale facile à contourner ou oublier ; corrections à reporter dans chaque dépôt |
| Plateforme centrale qui décrit et déploie toutes les applications | Vue centralisée des déploiements | Contredit la séparation demandée ; chaque livraison applicative dépend du dépôt VPS |

La recommandation garde une seule machine et aucun orchestrateur de cluster. Le mécanisme commun est une commande locale courte et testable, pas un service HTTP de déploiement ni une nouvelle base centrale. Si ce mécanisme devient disproportionné, il faudra réduire le contrat applicatif plutôt que construire une plateforme générale.

## 4. Responsabilités et limites des dépôts

| Sujet | Dépôt VPS | Dépôt applicatif |
| --- | --- | --- |
| Inventaire et accès | Adresse du serveur, empreintes SSH vérifiées, administrateurs | Inventaire minimal pointant vers le même serveur, utilisateur de déploiement autorisé |
| OS, SSH, firewall, Docker | Configure et maintient | Consomme ; ne modifie pas le socle |
| HTTP commun | Installe et configure Caddy ; contrôle les domaines autorisés | Déclare les routes et besoins HTTP de ses instances |
| Admission | Fixe les plafonds, installe le contrôleur commun et son état local | Demande un déploiement ; ne choisit pas son propre quota global |
| Images et services | Aucun catalogue d'images applicatives | Dockerfile, build externe, images par digest, Compose, santé et dépendances |
| Données | Fournit isolation, chemins et règles de conservation | Choisit sa base, migrations, données de test, sauvegarde et restauration |
| Secrets | Protège les accès hôte et les secrets du proxy | Possède ses secrets de production, staging et preview |
| Livraison | Publie des versions des rôles et du protocole commun | Choisit une version compatible ; déclenche ses propres opérations |

Une liste technique d'identités autorisées peut associer un compte SSH à une application, à des environnements et à une enveloppe maximale. Elle ne contient ni image, ni stack, ni instruction pour déployer les applications. Ajouter une identité est une opération explicite du socle, qui ne lance aucun conteneur applicatif.

Le [glossaire](../../../GLOSSARY.md) distingue application, service, instance, staging et preview. Aucun ADR séparé n'est nécessaire avant validation : les alternatives et leur justification sont déjà consignées ici.

### Structure proposée, sans création des fichiers correspondants

```text
vps-services/
  inventories/production/        # VPS unique ; variables non secrètes
  playbooks/bootstrap.yml        # accès initial et administrateur
  playbooks/platform.yml         # socle, sans déploiement applicatif
  playbooks/register-app.yml      # identité/permissions ; aucune stack
  collections/ansible_collections/ny/vps/
    roles/                       # host, ssh, firewall, docker, ingress, app
    plugins/                     # interface commune de déploiement
  docs/                          # exploitation, contrat, conception
  Makefile                       # commandes fines, sans action cachée

un-depot-applicatif/
  Dockerfile
  deploy/ansible/deploy.yml
  deploy/ansible/requirements.yml
  deploy/ansible/inventory.yml
  deploy/ansible/environments/    # prod, staging, preview ; hors secrets
  deploy/compose.yml.j2           # services propres à cette app
  deploy/data/                   # migrations et fixtures propres à l'app
```

### Distribution et versions

Recommandation : une collection `ny.vps` construite dans ce dépôt. Les apps l'installent depuis Git à un **SHA complet approuvé**, via leur `requirements.yml`, en ciblant le sous-dossier de la collection. Les tags de release rendent les versions lisibles ; le SHA assure la reproductibilité. Pas de dépendance à `main`, de téléchargement `latest` ou de copie manuelle des rôles. Ansible permet une collection Git ciblée par sous-dossier et commit. [Documentation Ansible](https://docs.ansible.com/projects/ansible/latest/collections_guide/collections_installing.html)

Le serveur conserve le numéro de protocole accepté par sa commande commune ; la collection applicative déclare celui qu'elle émet. Une incompatibilité est rejetée **avant mutation**. Une mise à jour du socle garde le protocole précédent le temps d'une migration explicite ; elle ne redéploie pas les apps. Les versions Ansible, collections tierces, Docker, Compose et Caddy seront fixées et testées ensemble à l'implémentation, sans inventer ici des numéros de paquets non vérifiés sur Debian 13.

## 5. Socle et accès sans perte de SSH

Ansible s'exécute depuis le poste ou un runner de confiance. Le serveur n'a pas besoin de cloner les dépôts applicatifs, d'héberger un runner GitHub ni de compiler les images.

Le provisioning se déroule en deux phases :

1. **Accès initial** : résolution humaine du changement obligatoire de mot de passe via le canal OVH prévu ; vérification de la nouvelle empreinte hôte par un canal indépendant ; connexion `debian` par clé. Aucun secret n'est demandé ni lu pendant la conception.
2. **Accès définitif** : création d'un administrateur non-root, proposition de nom `vps-admin`, installation des clés publiques autorisées, sudo contrôlé, connexion indépendante réussie avec cet administrateur. Valider `sshd -t`, puis appliquer le durcissement et refaire une connexion complète. Garder la session initiale et une voie de récupération OVH jusqu'à réussite.

Ne pas désactiver le compte initial ni l'accès par mot de passe avant ce test. Durcissement cible : pas de login SSH root, authentification par clés, mots de passe et authentification interactive désactivés après vérification, pas de port SSH exotique pour masquer le service. Maintenir l'accès console/rescue comme procédure de récupération. Les changements de firewall suivent le même ordre : permettre la session d'administration, appliquer les règles puis tester une nouvelle connexion.

Les comptes de déploiement sont séparés de l'administrateur : un accès nonprod pour staging/previews, et un accès production distinct par application. Ils n'ont ni sudo général ni accès au socket Docker. Ils peuvent déposer une requête pour leur identité et appeler uniquement la commande commune prévue. L'administrateur reste une personne de confiance ayant la capacité de modifier le système ; le plafond ne prétend pas résister à un administrateur root.

Docker Engine et le plugin Compose viennent du dépôt APT officiel, qui prend en charge Debian 13. Les mises à jour de sécurité OS sont prévues ; redémarrages OS et changements majeurs Docker restent des opérations de maintenance explicites. [Installation Debian](https://docs.docker.com/engine/install/debian/)

### Firewall et publication Docker

Politique externe cible, IPv4 **et** IPv6 : SSH 22, HTTP 80 et HTTPS 443 seulement ; connexions établies, loopback et ICMP nécessaires au réseau restent autorisés. Les bases et services internes n'ont aucun port public.

Recommandation : backend Docker `iptables`, avec outils `iptables-nft` / `ip6tables-nft`, règles d'entrée hôte et filtrage du trafic Docker dans `DOCKER-USER`. Conserver les règles NAT de Docker et éviter un mélange de backends non testé. Une règle INPUT ou UFW seule ne protège pas les ports publiés par Docker. Le filtre de forwarding doit traiter l'interface publique, les connexions établies et, lorsque nécessaire, le port de destination original avant DNAT ; il doit survivre à un redémarrage de Docker. [Firewall Docker](https://docs.docker.com/engine/network/packet-filtering-firewalls/), [chaînes iptables](https://docs.docker.com/engine/network/firewall-iptables/)

Seul Caddy, exécuté sur l'hôte via systemd dans l'approche recommandée, écoute sur 80/443. Les apps publient uniquement des upstreams HTTP sur `127.0.0.1`, à des ports attribués par le socle. La commande commune refuse `0.0.0.0`, `::`, le réseau host et toute autre publication. L'administration Caddy utilise un socket Unix avec permissions restreintes, inaccessible aux conteneurs et comptes applicatifs. Les accès nécessaires à ce socket sont accordés au contrôleur commun. [Options d'administration Caddy](https://caddyserver.com/docs/caddyfile/options#admin)

Les routes sont des données validées, pas des fragments Caddyfile arbitraires fournis par les apps. Le contrôleur assemble la configuration à partir de l'état accepté, la valide puis recharge Caddy sous le même verrou. Une route inconnue renvoie une réponse neutre ; aucun wildcard ne dirige toutes les requêtes vers une application par défaut. Les certificats et la configuration de Caddy restent persistants et protégés lors du nettoyage des previews.

La validation sur VM puis VPS doit aussi publier temporairement un port interdit dans un test contrôlé d'administrateur et vérifier son inaccessibilité depuis une autre machine. Tester séparément IPv4 et IPv6, ainsi que l'impossibilité d'atteindre directement une IP de conteneur depuis l'extérieur. Un contrôle de fichier ne remplace pas ces essais.

## 6. Isolation des instances et HTTP

Une instance est identifiée par `application + environnement`, par exemple `exemple-prod`, `exemple-staging`, `exemple-pr-42`. La clé d'application est unique sur le VPS, enregistrée explicitement et liée au dépôt canonique. Les noms acceptés sont normalisés et validés ; aucune valeur de PR ne devient directement un chemin ou une commande shell.

| Ressource | Règle |
| --- | --- |
| Projet Compose | Nom unique par instance ; pas de `container_name` fixe |
| Réseau | Bridge propre à l'instance ; aucun réseau applicatif partagé entre apps ou environnements |
| Base/cache | Conteneurs et volumes propres à l'instance par défaut |
| Volumes | Préfixés par projet ; aucun volume externe commun ni montage d'un autre environnement |
| Répertoire | `/srv/vps/apps/<app>/<env>/` ; état actif contrôlé par le socle |
| Secrets | Fichiers et credentials distincts par instance ; aucun accès aux secrets d'une autre instance |
| HTTP | Route de domaine validée vers un port loopback loué à l'instance |

L'approche Caddy sur l'hôte évite un réseau Docker commun entre toutes les apps. Seuls les services HTTP explicitement déclarés ont un port loopback ; leurs bases restent sur le réseau de l'instance. L'isolation doit être testée, notamment l'accès à un autre bridge et aux ports hôte depuis un conteneur. Un bridge séparé ne suffit pas à démontrer toute la politique réseau.

Les conteneurs applicatifs ont des droits réduits : pas de socket Docker, conteneur privilégié, namespaces hôte, devices ou capacités supplémentaires arbitraires. Pas d'accès aux métadonnées/secrets du socle via un montage hôte. Les montages autorisés sont limités aux fichiers de configuration et volumes propres à l'instance. Docker partage le noyau du VPS : ce design convient à des applications et contributeurs de confiance ; il ne promet pas l'isolation d'une VM pour exécuter des PR hostiles. Donner accès au daemon Docker équivaut à donner un contrôle puissant sur l'hôte. [Sécurité Docker](https://docs.docker.com/engine/security/)

Domaines illustratifs : `app.apps.example.net`, `app-staging.apps.example.net`, `app-pr-42.apps.example.net`. **Aucun de ces domaines n'est configuré.** Le domaine réel, ses DNS et le mode TLS devront être approuvés séparément. Proposition : wildcard A/AAAA sur un sous-domaine dédié et certificat wildcard via DNS-01, avec token Cloudflare restreint à la zone concernée. Cela évite une mutation DNS à chaque PR ; le certificat reste au niveau du socle. Le choix d'un wildcard suppose un build Caddy avec le module DNS adapté et sa version vérifiée. [HTTPS et challenge DNS Caddy](https://caddyserver.com/docs/automatic-https)

Sans wildcard approuvé, utiliser des enregistrements explicitement autorisés et TLS par nom. Aucun ancien nom supprimé n'est recréé. Portfolio, `www`, emails et autres domaines restent hors de cette refonte. Un nom HTTP doit appartenir au namespace autorisé de l'application et ne pas écraser la route d'une autre instance.

Staging et previews : accès HTTP restreint par défaut proposé, sans indexation et avec comptes de test. Le mécanisme précis — authentification au proxy ou dans l'app — sera fixé par app ; `robots.txt` seul n'est pas une protection. Les emails, paiements et intégrations externes utilisent des modes de test, sans credentials production.

## 7. Capacités, plafonds et admission vérifiable

Deux previews constituent un plafond, **pas une promesse que toutes les applications tiendront**. Une preview peut comprendre plusieurs services ; elle consomme une seule place mais additionne tous leurs besoins, bases et tâches de migration incluses.

### Enveloppe initiale proposée

| Usage global | CPU maximal déclaré | RAM maximale déclarée |
| --- | --- | --- |
| OS, Docker, Caddy et marge hôte | Marge de 1 vCPU | Marge de 2 GiB |
| Productions de toutes les apps | 1,5 vCPU | 3 GiB |
| Stagings de toutes les apps | 0,5 vCPU | 1 GiB |
| Toutes les previews | 1 vCPU | 2 GiB |
| Une preview | Au plus 0,5 vCPU | Au plus 1 GiB |

Les catégories applicatives totalisent au plus 3 vCPU / 6 GiB, réservant de la marge sur le VPS annoncé. Ce sont des plafonds d'admission configurables ; ils ne réservent pas matériellement du CPU aux applications et ne garantissent pas leurs performances. L'OS, le cache disque, le daemon, les I/O et les pics de déploiement doivent aussi être observés. Une application trop lourde est refusée ou doit réduire sa stack ; elle n'est pas admise sur la seule base d'une consommation instantanée faible.

Chaque service déclare `cpus`, `mem_limit`, `memswap_limit` égal à `mem_limit` et `pids_limit`. Le rendu normalisé est vérifié et les valeurs effectives sont contrôlées avec `docker inspect`. Réplicas et jobs temporaires comptent dans les sommes ; première version proposée : une seule réplique par service, pas de blue/green doublant implicitement les besoins. Les limites directes des services Compose sont préférées à une hypothèse sur l'application de `deploy.resources`. [Référence Compose](https://docs.docker.com/reference/compose-file/services/)

Le contrat déclare aussi un budget de croissance des données et un besoin de téléchargement d'images. Proposition disque en **GiB**, à confirmer après `df` sur la nouvelle installation : 18 pour toutes les productions, 6 pour tous les stagings, 5 par preview, 8 pour les images partagées, 8 pour OS/configuration/logs et une réserve libre de 10. Soit une enveloppe de 60 GiB, à comparer à la capacité réellement utilisable ; 75 Go commerciaux ne sont pas 75 GiB.

Ces budgets de disque sont des **seuils suivis**, pas des quotas physiques de volumes Docker. Sans filesystem et quotas dédiés, une base peut dépasser son budget et remplir le disque. La première version proposée limite les logs, surveille l'espace, refuse de nouvelles admissions et alerte ; elle ne garantit pas une isolation dure du disque. Des quotas ou un volume séparé deviendraient un projet explicite si cette garantie était requise.

### Contrôle commun sur le VPS

Le socle installe une commande root-owned, nom proposé `vpsctl`, et un registre JSON root-owned dans `/var/lib/vps-platform/`. Les rôles Ansible applicatifs lui transmettent une requête structurée. Elle réalise le cycle Compose et les routes HTTP ; aucune API publique, file d'attente ou base supplémentaire n'est requise.

Les comptes CI n'appartiennent pas au groupe Docker. Leur règle sudo autorise uniquement cette commande avec une interface fixe ; l'identité et les environnements autorisés sont déduits du compte effectif, pas acceptés aveuglément depuis la requête. Le contrôleur prend un instantané privé de l'entrée avant validation, refuse les chemins arbitraires, liens symboliques et champs inconnus, et ne lance pas de commandes shell hôte fournies par l'app. Le fichier Compose normalisé est soumis à une liste explicite de champs autorisés ; `build`, `include`, `extends`, bind mounts arbitraires et références externes ne contournent pas le contrat.

Le registre est un **état d'exploitation**, pas un manifeste applicatif central. Il conserve identité, environnement, génération de livraison, images/digests, ressources réservées, ports loués, timestamps, santé et labels Docker. Il ne contient pas les valeurs des secrets. Les fichiers privés Compose/secrets nécessaires à l'exécution sont stockés séparément avec permissions strictes.

Admission et mutations sont sérialisées par un `flock` local au VPS. Pour la première version, le verrou couvre l'opération entière, avec délai maximal proposé de dix minutes ; accepter cette attente est plus simple que gérer plusieurs déploiements simultanés. Sous ce verrou :

1. Vérifier identité, protocole, entrée complète, images par digest, secrets requis, chemins et configuration Compose normalisée.
2. Réconcilier registre et objets Docker marqués ; un état inconnu est signalé et bloque les admissions ambiguës, sans effacement opportuniste.
3. Compter toutes les previews : `preparing`, `running`, `unhealthy` et `deleting` consomment une place. Production/staging n'en consomment aucune. Une mise à jour de la même PR ne consomme pas une deuxième place.
4. Calculer la somme des plafonds après remplacement de l'ancienne réservation par la nouvelle, catégorie et VPS compris. Les anciennes ressources restent comptées tant qu'elles existent ; tout chevauchement ou job additionnel doit être budgété.
5. Contrôler RAM disponible et espace/inodes : refuser si la hausse de RAM ne laisse pas une marge instantanée de 512 MiB, ou si téléchargement, données initiales et fichiers temporaires risquent de passer sous 10 GiB libres. Après pull, mesurer de nouveau avant démarrage. Si la taille d'une image ne peut être estimée avec prudence, refuser plutôt que supposer qu'elle tient.
6. Réserver place, budgets et ports avant création ; écrire l'état atomiquement. Créer les ressources, migrer/initialiser si nécessaire, vérifier la santé et publier la route seulement après succès.
7. Écrire le résultat et relâcher le verrou. Sur échec, retirer uniquement les objets créés par cette opération lorsque c'est sûr ; sinon conserver état, place et diagnostics jusqu'à réconciliation.

Deux demandes concurrentes de dépôts différents, pour la dernière place disponible, doivent produire une seule admission. Une troisième preview est refusée avec un message indiquant les deux occupants, le motif et l'expiration ; **aucune preview existante n'est évincée automatiquement**. Pas de nouvelle admission tant qu'une suppression incomplète occupe encore la place. La limite configurable vit sur l'hôte ; une variable d'un dépôt app ne peut pas la relever.

Réduire `max_active_previews` sous le nombre actuel bloque les créations jusqu'à libération, sans supprimer les previews. Augmenter ce nombre ne relève pas implicitement CPU, RAM ou disque. Une panne ou intervention d'administrateur peut nécessiter une réparation du registre : cette commande montre le plan puis applique un périmètre identifié, jamais un `docker system prune --volumes` global.

### Disque et visibilité

Rotation Docker proposée : `json-file`, `max-size: "10m"`, `max-file: "3"` ; journal système également borné. Les réglages du daemon concernent les nouveaux conteneurs, donc vérifier chaque instance après création. [Rotation Docker](https://docs.docker.com/engine/logging/drivers/json-file/)

Un timer du socle vérifie espace, inodes, consommation par instance et état des previews. Seuil d'avertissement proposé : moins de 15 GiB libres ; sous 10 GiB, admissions gelées. L'état apparaît dans `vpsctl status`, le journal système et les sorties de déploiement. Un canal d'alerte externe reste à choisir ; aucune notification tierce n'est configurée par cette spec. La fréquence proposée est cinq minutes, pas une garantie contre une écriture massive entre deux mesures. Ne jamais supprimer des données prod/staging pour faire de la place.

## 8. Contrat applicatif et données

Chaque application fournit un playbook Ansible, ses variables d'environnement, son modèle Compose et son protocole de santé. Elle construit les images sur le poste ou en CI, publie au registre puis transmet leurs digests. Le socle ne fait pas `git pull`, `npm install` ni de build applicatif sur le VPS.

Le rôle commun `ny.vps.app` possède les opérations `plan`, `apply`, `status`, `logs`, `destroy-preview`. L'application fournit :

- Clé enregistrée, dépôt canonique, environnement `prod`, `staging` ou `preview`, numéro de PR pour preview et génération de livraison.
- Images immuables, services et limites par service ; un total de ressources vérifiable, sans plafond implicite illimité.
- Routes HTTP, ports internes et test de readiness ; une simple présence du conteneur ne vaut pas succès.
- Secrets requis et leur injection privée ; absence d'un secret = échec avant mutation.
- Volumes persistants, besoins disque, migrations et initialisation des données, exécutées dans un conteneur de l'instance avec limites.
- Pour prod/staging avec données durables : procédure de sauvegarde/restauration et compatibilité des migrations avec un retour d'image.

Les formats génériques ne supposent ni Postgres ni Supabase. Par défaut, une app avec base déploie une base propre à chaque instance. Une base externe ne serait admise qu'avec des endpoints, credentials et données distincts démontrés pour chaque environnement ; aucun accès à une base production en preview.

Une nouvelle preview initialise un volume neuf à partir de fixtures synthétiques versionnées dans l'app. Une mise à jour de cette même PR conserve ses données de test et applique des migrations compatibles. Proposition : réinitialisation des données uniquement sur commande explicite de l'app/opérateur ; pas à chaque push. À la suppression définitive de la preview, ses données de test sont supprimées avec elle. Une sauvegarde de production ne sert jamais de fixture par défaut.

Les credentials de base sont uniques par instance, et différents des credentials SSH. Les identifiants nonprod ne possèdent aucun privilège de production. La suppression d'une PR n'exécute aucun SQL sur staging ou prod. Le socle ne crée pas de base via un conteneur `supabase-db` global.

### Exemple illustratif dans un dépôt applicatif

Ce playbook montre la forme de l'interface proposée ; il n'est pas exécutable avant création et validation de la collection. `app_image_digest`, `database_image_digest`, `release_generation` et les secrets doivent être fournis par le contexte de livraison. Les empreintes/digests ne sont pas inventés dans cette spec.

```yaml
# deploy/ansible/deploy.yml — application fictive « exemple »
- name: Livrer une instance de l'application
  hosts: vps
  gather_facts: false
  become: false
  vars_files:
    - "environments/{{ target_environment }}.yml"
  roles:
    - role: ny.vps.app
      vars:
        vps_app:
          protocol: 1
          key: exemple
          repository: organisation/exemple
          environment: "{{ target_environment }}"
          pull_request: "{{ pull_request_number | default(omit) }}"
          generation: "{{ release_generation }}"
          operation: apply
          compose_template: "{{ playbook_dir }}/../compose.yml.j2"
          images:
            web: "{{ app_image_digest }}"
            db: "{{ database_image_digest }}"
            seed: "{{ app_image_digest }}"
          limits: "{{ instance_limits }}"
          storage_budget_gib: "{{ instance_storage_budget_gib }}"
          readiness: {service: web, port: 3000, path: /health/ready}
          secret_file: "{{ lookup('env', 'APP_SECRETS_FILE') }}"
          data:
            mode: "{{ instance_data_policy }}"
            initializer_service: seed
```

Par exemple, le fichier `environments/preview.yml` déclare le profil ci-dessous. Prod/staging possèdent leurs propres fichiers de variables et politiques de données ; ils n'héritent pas d'une initialisation par fixtures.

```yaml
instance_limits:
  web: {cpus: 0.2, memory_mib: 384, pids: 128}
  db: {cpus: 0.2, memory_mib: 384, pids: 128}
  seed: {cpus: 0.1, memory_mib: 128, pids: 64}
instance_storage_budget_gib: 2
instance_data_policy: fixtures_on_first_creation
```

Le job `seed`, si nécessaire, doit avoir image, droits et limites déclarés dans le Compose. Il s'exécute avant le web. Par simplicité, l'admission additionne conservativement tous les services déclarés, jobs temporaires inclus : ici 0,5 vCPU / 896 MiB. Ce profil respecte le plafond d'une preview même si les services se chevauchent ; aucun job additionnel ne peut être lancé sans ressources déclarées. Le rôle rend Compose localement, transmet une requête au contrôleur et attend son résultat ; il ne reçoit pas de sudo général. Le fichier privé des secrets n'est ni un manifeste central ni un fichier commité.

Dans `requirements.yml`, la source prévue est le Git de `vps-services`, sous-dossier `collections/ansible_collections/ny/vps/`, type `git`, version = SHA complet de la release choisie. La référence exacte sera inscrite lorsque cette release existera. Chaque dépôt applicatif relit ses mises à jour de collection indépendamment.

### Secrets et audit

Fichiers de valeurs, clés privées, tokens GHCR/DNS et `.env` restent hors Git. Première version locale proposée : fichiers privés à permissions `0600`, référencés par chemin ; éventuelle CI : secrets d'environnement GitHub strictement limités. `no_log: true` et `diff: false` sur le transfert et les tâches sensibles. Pas d'assemblage de toutes les variables/secrets du dépôt sans liste explicite.

Les credentials générés pour une instance sont conservés lors d'une relance idempotente ; leur rotation est explicite. Les fichiers transférés sont installés atomiquement avec permissions `0600` et dossiers privés ; les zones temporaires sont nettoyées même après échec. Une configuration Compose normalisée contenant des valeurs d'environnement est un fichier privé et ne doit pas être jointe aux logs de CI. L'audit enregistre acteur technique, instance, digest, génération, décision d'admission et résultat, jamais valeurs secrètes.

## 9. Livraison, santé et retour arrière

Une livraison suit : validation locale → build externe → publication image → plan d'admission → pull → préparation privée → migration éventuelle → Compose → readiness → route HTTP → contrôle HTTP final → statut.

`plan` et `--check` ne réservent aucune place ; une admission positive au moment du plan peut devenir négative au moment d'`apply`. Le résultat final indique séparément santé locale de l'app et accessibilité HTTP/TLS. Si le domaine/TLS n'est pas prêt, ne pas annoncer la preview publiquement disponible.

Pour une première instance, la route est ajoutée après readiness. Pour une mise à jour, conserver la dernière configuration de livraison et des diagnostics bornés ; une interruption est possible avec Compose sur une seule instance. Aucun zéro downtime n'est promis. Si readiness échoue, revenir à l'image précédente uniquement lorsque les migrations sont compatibles. Sinon maintenir l'état d'échec pour intervention, sans masquer le problème par une restauration automatique de données.

La production est proposée comme promotion manuelle d'un digest validé en staging, avec une identité SSH distincte. La politique de migrations, la tolérance à l'interruption et le besoin de retour automatique seront décidés pour chaque application avant sa première production.

## 10. Previews : cycle de vie proposé, à valider

| Événement | Comportement proposé |
| --- | --- |
| PR ouverte / mise à jour | Build sans secret prod ; demande de création/mise à jour pour cette PR |
| Deux places occupées | Refus lisible ; pas d'éviction ni de file d'attente implicite ; relance explicite après libération |
| Nouveau push sur la même PR | Remplacement sérialisé ; mêmes volumes ; génération plus récente requise |
| Livraison ancienne arrivant après une nouvelle | Rejet par génération monotone par instance ; le digest seul ne définit pas l'ordre |
| Annulation CI ou perte de SSH | Contrôleur borné par timeout ; réconciliation avant nouvelle admission ; pas de place libérée à l'aveugle |
| PR fermée ou fusionnée | Suppression de la seule preview concernée par son dépôt applicatif |
| Fermeture pendant un déploiement | Demande de suppression sérialisée, tombstone de génération empêchant une relance ancienne ; relance neuve seulement après réouverture explicite |
| Nettoyage CI manqué | Expiration locale proposée après 72 h depuis le dernier déploiement réussi ou renouvellement explicite |
| État `preparing` après crash | Lease proposée de 15 min ; réconciliation des objets avant cleanup, sans supposer que rien n'a été créé |

Production et staging ne sont jamais concernés par le timer d'expiration. Les états en échec continuent de compter tant que des ressources subsistent. Un échec ne renouvelle pas le TTL de l'instance. Une opération de suppression retire la route, stoppe les conteneurs, supprime uniquement réseaux/volumes/secrets marqués pour cette instance, vérifie leur absence puis libère la place et les ports. Les labels et le registre doivent être cohérents ; en cas d'ambiguïté, le timer alerte sans supprimer.

Les workflows appartiennent aux apps. Une `concurrency` GitHub par app/PR aide à ordonner les jobs, mais ne remplace pas le verrou global VPS ni le contrôle de génération. Le socle peut publier des workflows réutilisables épinglés ; aucune logique ne reconstruit toutes les apps depuis `vps-services`.

Automatisation GitHub proposée : staging après validation sur la branche de référence de l'app, production par action manuelle, previews sur événements PR et cleanup à la fermeture. Ces déclencheurs **ne sont pas encore approuvés**. Première version recommandée : commandes manuelles du même contrat, puis automatisation après démonstration du cycle complet.

Pas de secrets de déploiement pour PR issues de forks. Un workflow privilégié ne doit pas exécuter directement le code d'une PR non approuvée. Les mises à jour de playbooks/deploy doivent être revues avant utilisation avec une clé CI, et l'accès prod reste distinct. Le registre local peut expirer une preview sans token GitHub ; vérifier lui-même si toutes les PR sont fermées ajouterait une intégration non nécessaire à cette version.

## 11. Exploitation et sauvegardes

Les commandes suivantes sont des interfaces futures proposées, **pas des commandes exécutées ni disponibles aujourd'hui** :

```bash
# Dans le dépôt VPS : aucune app démarrée par platform.yml
make plan
ansible-playbook -i inventories/production playbooks/bootstrap.yml
ansible-playbook -i inventories/production playbooks/platform.yml

# Dans un dépôt applicatif : environnement et identité explicites
ansible-galaxy collection install -r deploy/ansible/requirements.yml
ansible-playbook -i deploy/ansible/inventory.yml deploy/ansible/deploy.yml \
  -e target_environment=preview -e pull_request_number=42 \
  -e release_generation=123 -e @/chemin/prive/images.yml

# Via l'administrateur, lecture de l'état global
ssh vps-admin@51.210.10.127 sudo vpsctl status
ssh vps-admin@51.210.10.127 sudo vpsctl previews list
ssh vps-admin@51.210.10.127 sudo vpsctl logs --instance exemple-pr-42 --tail 100

# Nettoyage ciblé explicite, destructif pour les seules données de cette preview
ssh vps-admin@51.210.10.127 sudo vpsctl previews destroy --instance exemple-pr-42
```

Le futur Makefile expose les opérations et les paramètres, sans `up-all` qui restaure une stack par défaut. Les diagnostics incluent `journalctl` des composants hôte, configuration firewall, `docker compose ps`, `docker inspect`, journaux bornés par instance, ressources déclarées/effectives et dernière décision d'admission. Les commandes opérateur utilisent SSH avec vérification d'empreinte ; pas de `StrictHostKeyChecking=no`.

La sauvegarde automatique OVH existante reste activée et son point disponible est conservé. Elle ne démontre pas une restauration cohérente d'une base applicative. Le socle ne restaure aucune application depuis cette sauvegarde.

Pour une app avec données durables, la première production exige : destination hors VPS choisie, chiffrement, secrets de sauvegarde distincts, export cohérent adapté à la base, rétention, espace temporaire déclaré et exercice de restauration dans une instance de test. Proposition initiale à valider avec l'app : sauvegarde quotidienne, sept quotidiennes et quatre hebdomadaires, objectif de perte maximale de 24 h et restauration en quatre heures. Ces objectifs ne sont pas garantis tant que l'exercice et la capacité ne les confirment pas. Les previews sont jetables et ne sont pas sauvegardées par défaut.

## 12. Validation avant utilisation

Aucun code ou test n'est créé à cette étape. Les critères suivants guideront l'implémentation et sa preuve.

### Local, sans VPS

- Lint et syntaxe Ansible/YAML ; installation reproductible des collections depuis leurs SHA.
- Rendu Compose sans secrets réels ; schéma et limites vérifiés ; absence d'images flottantes et de configurations hors contrat.
- Tests du contrôleur : admission concurrente venant de deux apps, comptage par PR, budgets agrégés, hausse/baisse du plafond, reprise après crash, refus des champs et chemins dangereux.
- Tests de génération : ancien déploiement après nouveau, close pendant apply, événements dupliqués et suppression répétée sans effet supplémentaire.
- Tests secrets : secret manquant refusé, fichiers privés, absence de fuite dans logs et sorties diff.

### VM Debian 13 jetable

Utiliser une VM complète, pas seulement un conteneur : systemd, SSH, firewall et Docker doivent être réels. Premier run du socle, deuxième run sans changement attendu, reboot, nouveau run, nouvelles connexions SSH. `--check` aide à relire les changements mais reste une simulation ; les tâches sensibles doivent supporter ce mode ou annoncer explicitement une vérification non réalisée, sans mutation cachée. [Mode check Ansible](https://docs.ansible.com/projects/ansible/latest/playbook_guide/playbooks_checkmode.html)

Scénario intégration : une app fictive avec web + base en prod et staging, deux previews réparties sur deux apps, troisième preview refusée. Modifier une fixture dans une preview et vérifier que l'autre, le staging et la prod restent identiques. Vérifier réseau, volumes, credentials, limites effectives, healthcheck, ports publics IPv4/IPv6 et nettoyage ciblé. Après fermeture manquée et TTL accéléré de test, seule la preview expirée disparaît. Rejouer une livraison identique ne régénère ni secrets, ni données, ni conteneurs inutilement.

### VPS réel, après résolution de l'accès

Mesurer `df`, RAM au repos, versions/cgroups et règles réseau ; adapter les enveloppes. Provisionner uniquement le socle après validation humaine. Refaire les vérifications SSH/firewall depuis une autre machine puis un cycle complet sur une app de test explicitement nommée. Tester la sauvegarde/restauration de l'app avant toute donnée utile.

Une réussite locale n'est pas un déploiement validé ; une connexion SSH n'est pas une preuve de readiness ; une readiness locale n'est pas une preuve DNS/TLS. Chaque étape possède son résultat distinct. L'accès initial bloqué aujourd'hui empêche de conclure sur tous les critères VPS.

## 13. Remplacement local et migration, sans déclencher l'ancienne CI

Séquence proposée pour une phase ultérieure autorisée :

1. Faire valider cette conception et ses politiques proposées. Aucun reset supplémentaire du VPS.
2. Réinspecter le dossier original : branche, upstream, changements suivis/non suivis, fichiers ignorés et remotes. Protéger tout travail local.
3. Sauvegarder le dossier original et son `.env` dans une archive privée hors Git, permissions restrictives, avec vérification d'intégrité sans afficher le contenu. Ne pas compter sur un stash pour sauver les fichiers ignorés. Ne jamais copier le `.env` dans la nouvelle histoire.
4. Préparer le remplacement dans un dossier voisin propre. Confirmer séparément le choix GitHub : refonte du dépôt existant recommandée pour préserver le remote et l'historique ; un nouveau dépôt exigerait une décision explicite. Aucun dépôt GitHub n'est supprimé.
5. Si une branche devient nécessaire, utiliser `feat/ansible-vps` à partir de la vraie base vérifiée, jamais `codex/`. Lors de l'implémentation, remplacer les anciens workflows de déploiement par de la validation sans déploiement automatique du socle, avant tout chemin de publication sur `main`.
6. Avant publication ultérieure, identifier aussi les dépôts qui appellent les anciens workflows réutilisables ; retirer ou désactiver leurs accès VPS et planifier leur migration, sans déployer leurs apps. Une branche ou un nouveau dépôt de conception seul ne neutralise pas ces appelants.
7. Ne pas compter sur `chore:` ou `[skip ci]` comme mesure de sûreté. Vérifier concrètement les triggers GitHub et suspendre explicitement les anciens déploiements avec autorisation avant le premier push susceptible de les déclencher. La nouvelle CI ne provisionne pas le VPS sur chaque push.
8. Après validation locale de l'implémentation, basculer le dossier local par renommage contrôlé, en gardant l'ancien dossier privé récupérable. Replacer uniquement des secrets encore nécessaires, par sélection explicite, pas l'ancien `.env` Supabase entier.
9. Résoudre l'accès initial, provisionner le socle et démontrer son idempotence. Enregistrer ensuite une app fictive de test pour vérifier le contrat ; aucune restauration des apps historiques.
10. Adopter le contrat dans chaque futur dépôt applicatif séparément. Production, domaines réels et sauvegardes nécessitent une configuration et une validation propres à cette app.

Retour arrière local : réouvrir le dossier sauvegardé sans activer ses anciennes commandes de déploiement. Retour arrière serveur : maintenance explicite du socle, sans restauration OVH automatique susceptible de réintroduire l'ancienne stack. Ne pas supprimer la sauvegarde OVH existante.

**Cette rédaction n'exécute aucune de ces opérations : seul ce document et le glossaire sont ajoutés.**

## 14. Points à présenter pour validation finale

| Proposition | Décision matérielle attendue |
| --- | --- |
| Ansible + Compose, collection Git épinglée, contrôleur commun local | Valider ce niveau de réutilisation et le coût du contrôle global |
| Caddy sur l'hôte, upstreams loopback par instance | Valider la stratégie HTTP ; nommer plus tard le domaine dédié et le mode TLS |
| Enveloppes 3 vCPU / 6 GiB pour les apps, preview ≤ 0,5 vCPU / 1 GiB | Valider les plafonds de départ, à recalibrer après mesure ; accepter des refus si une app est trop lourde |
| Disque surveillé, sans quotas durs | Accepter cette limite ou demander un chantier quotas séparé |
| Refus de la troisième preview, TTL 72 h, suppression des données à expiration/fermeture | Valider refus, conservation et suppression automatique des previews |
| Mise à jour PR conservant ses données de test | Valider ce comportement plutôt qu'une remise à zéro à chaque push |
| Première version manuelle, staging automatique ensuite, prod manuelle | Valider la politique de déclenchement GitHub, sans la confondre avec l'autorisation de déployer maintenant |
| Refonte du dépôt GitHub existant, archive privée du dossier original | Confirmer lors de la migration le devenir du dépôt et la neutralisation de l'ancienne CI |

Le plafond global de deux previews, la séparation des dépôts, prod/staging dédiés et les données de test isolées sont déjà confirmés. Les lignes ci-dessus précisent leur mise en œuvre proposée ; elles n'ouvrent pas un nouveau questionnaire dans ce document.
