# Déclaration sur l'utilisation de l'intelligence artificielle

## Développement

Flux, FluxLite, Flux Remote, l'interface web, le relais Flux et le site ont été conçus et développés **avec l'aide d'outils d'intelligence artificielle** (assistant de programmation conversationnel). L'IA a servi notamment à :
- écrire et réviser du code ;
- rédiger des textes, dont la documentation et ces modèles juridiques ;
- concevoir les interfaces.

L'auteur, pour DMS Security :
- définit les fonctions ;
- relit, teste et valide chaque version avant sa publication ;
- reste responsable du logiciel.

Les textes juridiques produits avec l'aide de l'IA sont des modèles, à faire relire par un professionnel du droit.

## Droits d'auteur et licence

- **Rôle de l'auteur** : DMS Security conçoit Flux, choisit les fonctions, dirige l'écriture, relit, corrige, teste et
  valide chaque version. L'historique Git du code en garde la trace.
- **Assistant utilisé** : une partie du code et des textes a été écrite avec l'assistant d'IA **Claude (Anthropic)**.
  Les conditions d'utilisation d'Anthropic cèdent à l'utilisateur tous les droits éventuels d'Anthropic sur ce que
  l'assistant produit : rien n'empêche donc de publier ce code sous licence libre ou de le vendre.
- **Limite du droit d'auteur** : en droit européen et belge, seule une création reflétant des choix libres et créatifs
  d'un humain est protégée. La licence GNU AGPL-3.0 couvre l'apport humain (conception, choix, organisation,
  modifications). Les parties produites uniquement par l'IA peuvent ne pas être protégées par le droit d'auteur.
- **Pourquoi l'AGPL-3.0** : Flux utilise Ultralytics YOLO, lui-même sous AGPL-3.0, ce qui impose cette licence à
  l'ensemble, indépendamment de l'usage de l'IA.
- Ce point évolue encore : il est à faire confirmer par un juriste en propriété intellectuelle avant la vente.

## Fonctionnement

Flux utilise lui-même des modèles d'IA pour analyser les images : détection de personnes et de véhicules, visages, plaques, expressions (voir `LICENCES-TIERCES.md` pour leur origine et `REGLEMENT-IA.md` pour leur cadre légal). Ces modèles :
- tournent **sur le PC Flux du client** ;
- n'envoient **aucune image, aucun son et aucune donnée** à un service d'IA externe ;
- ne prennent **aucune décision** à la place d'un humain : ils signalent des situations à vérifier.
