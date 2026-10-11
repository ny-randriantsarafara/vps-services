# VPS Services

Vocabulaire de la plateforme qui héberge des applications sur un VPS unique.

## Langage

**Socle VPS** :
Ensemble des capacités communes du serveur dont les applications dépendent pour être hébergées.
_Éviter_ : stack applicative globale.

**Application** :
Produit identifié par son dépôt, qui possède ses propres besoins et son propre cycle de livraison.
_Éviter_ : service, lorsque l'on désigne le produit entier.

**Service applicatif** :
Composant d'une application, par exemple son interface web, son API ou sa base de données.

**Instance** :
Occurrence isolée d'une application dans un environnement donné.
_Éviter_ : application, lorsque l'on désigne seulement son occurrence en staging ou en preview.

**Production** :
Environnement durable qui fournit le produit à ses utilisateurs.

**Staging** :
Environnement durable de validation d'une application, distinct de sa production et de ses previews.
_Éviter_ : preview permanente.

**Preview** :
Environnement temporaire propre à une pull request d'une application.
_Éviter_ : staging de la PR.

**Place de preview** :
Unité du plafond commun qui limite le nombre de previews présentes sur le VPS, toutes applications confondues.
_Éviter_ : quota par dépôt.

**Admission** :
Décision d'accepter une création ou une modification d'instance au regard des capacités et des règles communes du VPS.

**Données de test** :
Données destinées à la validation d'une instance, distinctes des données de production et des autres instances.
