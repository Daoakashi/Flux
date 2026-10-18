# Dossier juridique de Flux

Ce dossier regroupe tous les textes juridiques de Flux et de ses programmes compagnons (FluxLite, Flux Remote, interface web, relais Flux). Ils sont rédigés pour la **Belgique**, avec des notes pour la **France**.

> **Important.** Ces documents sont des modèles préparés avec soin, mais ils ne remplacent pas l'avis d'un avocat. Faites-les relire avant la première vente, en particulier :
> - le contrat de vente ;
> - l'accord de sous-traitance ;
> - les fonctions de **reconnaissance des visages** et d'**expressions** (voir `REGLEMENT-IA.md`).
>
> Les passages entre crochets **[À COMPLÉTER]** doivent être remplis.

## Qui est qui ?

| Rôle | Qui | Ce que ça implique |
|---|---|---|
| **Éditeur** du logiciel | **DMS Security** | Publie Flux sous licence AGPL-3.0, vend l'installation, le support et les services (relais, mises à jour). Pour le règlement européen sur l'IA, c'est le **fournisseur** du système d'IA. |
| **Client** (magasin, entreprise) | L'entreprise qui installe les caméras | **Responsable du traitement** au sens du RGPD et de la loi caméras. Pour le règlement IA, c'est le **déployeur**. C'est lui qui déclare les caméras, pose les pictogrammes et répond aux personnes filmées. |
| **Sous-traitant** | DMS Security, seulement s'il accède aux images ou aux données du client (installation sur place, maintenance à distance) | Un accord de sous-traitance (`ACCORD-SOUS-TRAITANCE-RGPD.md`) doit être signé. |
| Utilisateurs des applications | Agents, responsables, directeurs | Acceptent les conditions d'utilisation (`CONDITIONS-UTILISATION-APPLICATIONS.md`). |

Flux fonctionne **chez le client** :
- les images, la base de données et les comptes restent sur le PC Flux du client ;
- DMS Security n'y a pas accès, sauf intervention demandée par le client ;
- le relais Flux transmet seulement des données chiffrées de bout en bout, qu'il ne peut pas lire.

## Contenu

| Fichier | Pour qui | À quoi ça sert |
|---|---|---|
| `MENTIONS-LEGALES.md` | Tout le monde | Identité de l'éditeur, hébergement du site |
| `LICENCE-AGPL-EXPLIQUEE.md` | Éditeur, clients | Ce que permet et impose la licence AGPL-3.0, et comment vendre un logiciel libre |
| `../LICENSE` | Tout le monde | Texte officiel de la GNU AGPL-3.0 (à la racine, pour GitHub) |
| `LICENCES-TIERCES.md` et `licences/` | Tout le monde | Licences des composants utilisés (YOLO, Qt, PyTorch, OpenCV…) |
| `CONDITIONS-GENERALES-DE-VENTE.md` | Clients professionnels | Contrat de vente des services et abonnements |
| `CONDITIONS-UTILISATION-APPLICATIONS.md` | Utilisateurs de FluxLite, Flux Remote et de l'interface web | Conditions affichées et acceptées dans les applications |
| `POLITIQUE-DE-CONFIDENTIALITE.md` | Tout le monde | Données traitées par **DMS Security** : site, Feedback, relais, mises à jour |
| `ACCORD-SOUS-TRAITANCE-RGPD.md` | Clients | Contrat RGPD article 28, à signer quand DMS Security intervient sur les données du client |
| `OBLIGATIONS-CLIENT-CAMERAS.md` | Clients | Checklist de la loi caméras (Belgique) et repères pour la France |
| `MODELE-REGISTRE-DES-TRAITEMENTS.md` | Clients | Fiche du registre RGPD (article 30), déjà remplie pour Flux |
| `MODELE-AIPD.md` | Clients | Analyse d'impact (article 35), obligatoire pour la reconnaissance des visages |
| `MODELE-AFFICHE-INFORMATION.md` | Clients | Texte du panneau d'information à côté du pictogramme |
| `REGLEMENT-IA.md` | Éditeur, clients | Classement de chaque fonction de Flux au regard du règlement européen sur l'IA |
| `DECLARATION-IA.md` | Tout le monde | Flux a été développé avec l'aide de l'intelligence artificielle |

## Avant la première vente

1. **Mentions légales**
   - Compléter : adresse, numéro d'entreprise (BCE), TVA.
   - Si DMS Security n'est pas encore une société enregistrée, créer l'entreprise ou vendre en personne physique (indépendant).
2. **Contrat de vente**
   - Compléter `CONDITIONS-GENERALES-DE-VENTE.md` : tarifs, durée du support, conditions de paiement.
   - Le faire relire par un avocat.
3. **Assurance**
   - Assurance responsabilité civile professionnelle.
   - Conseillée pour la vente de systèmes de sécurité.
4. **Agrément sécurité (Belgique)**
   - L'installation de systèmes d'alarme ou de caméras pour des tiers peut exiger un agrément du SPF Intérieur (loi du 2 octobre 2017 réglementant la sécurité privée et particulière).
   - À vérifier avant de proposer l'installation sur place. La vente d'un logiciel seul n'est en principe pas concernée.
5. **Reconnaissance des visages**
   - Lire `REGLEMENT-IA.md`.
   - Par défaut, proposer Flux **sans** liste noire de visages. L'identification biométrique des clients d'un magasin est, en pratique, interdite par le RGPD sans base légale spécifique.
6. **Chaque nouveau client reçoit :**
   - les CGV ;
   - l'accord de sous-traitance (si DMS Security intervient sur ses données) ;
   - `OBLIGATIONS-CLIENT-CAMERAS.md` ;
   - les modèles de registre, d'AIPD et d'affiche.

## Les autres dépôts

FluxLite, Flux Remote et le site (flux-web) ont chacun un dossier `juridique/` plus court. Il contient :
- leur licence ;
- leurs licences tierces ;
- un renvoi vers ce dossier, qui fait référence.
