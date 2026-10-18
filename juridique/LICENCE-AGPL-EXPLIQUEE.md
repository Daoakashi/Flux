# La licence AGPL-3.0 de Flux, expliquée simplement

Le texte qui fait foi est celui du fichier `LICENSE` (en anglais), à la racine de chaque dépôt. Ce résumé l'explique ; il ne le remplace pas.

## Pourquoi l'AGPL ?

Flux utilise **Ultralytics YOLO** (détection des personnes, véhicules et plaques). YOLO est distribué sous AGPL-3.0, et un programme qui l'intègre doit l'être aussi, sauf achat d'une licence commerciale « Enterprise » chez Ultralytics.

DMS Security a choisi l'AGPL-3.0 pour tous ses programmes : Flux, FluxLite, Flux Remote, l'interface web, le relais et le site. Les règles sont ainsi les mêmes partout, sans licence payante.

## Ce que tout le monde peut faire

- Utiliser les programmes, pour n'importe quel usage, y compris commercial.
- Lire, étudier et modifier le code.
- Redistribuer les programmes, modifiés ou non, gratuitement ou contre paiement.

## Ce que la licence impose

1. **Fournir le code source** à toute personne qui reçoit le programme. C'est le cas ici : le code est public sur GitHub, et le lien figure dans « À propos ».
2. **Garder la même licence** pour les versions modifiées (« copyleft »), avec les mentions de copyright et le texte de la licence.
3. **Usage en réseau (article 13).** Une version modifiée de Flux, utilisée par d'autres personnes à travers le réseau (application FluxLite, interface web), doit leur proposer son code source. Pour les versions officielles, le lien vers GitHub suffit.
4. **Aucune garantie.** Le logiciel est fourni « en l'état » (articles 15 et 16). Les garanties commerciales viennent seulement du contrat de vente (CGV).

## Comment vendre un logiciel libre ?

C'est permis et courant. Le client ne paie pas le droit d'utiliser le code, que la licence donne déjà à tous. Il paie :
- l'installation et le paramétrage chez lui (caméras, zones, comptes, relais) ;
- la formation ;
- le support et la maintenance (réponse garantie, correction prioritaire, mises à jour suivies) ;
- les services hébergés : relais Flux dédié, sauvegardes ;
- éventuellement le matériel (PC avec carte NVIDIA, caméras), déjà configuré.

Les conditions sont dans `CONDITIONS-GENERALES-DE-VENTE.md`.

## Ce qu'un client ne peut pas faire

Retirer la licence ou les mentions de copyright. Redistribuer une version modifiée sans en publier le code. Utiliser les noms « Flux », « FluxLite », « Flux Remote » ou le logo pour sa propre version (voir les mentions légales).

## Composants tiers

Chaque composant garde sa propre licence : voir `LICENCES-TIERCES.md`.

Points à surveiller :
- **NVIDIA CUDA et cuDNN** : licence propriétaire, mais redistribution permise des bibliothèques d'exécution, non modifiées.
- **Qt / PySide6** : LGPL-3.0. Les bibliothèques doivent rester remplaçables par l'utilisateur, ce qui est le cas.
