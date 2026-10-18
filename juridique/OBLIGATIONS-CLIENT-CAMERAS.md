# Vos obligations quand vous utilisez Flux

*Checklist à remettre à chaque client. Belgique : loi du 21 mars 2007 réglant l'installation et l'utilisation de caméras de surveillance (modifiée en 2018) et RGPD. Repères pour la France en fin de document.*

Vous (l'entreprise qui installe les caméras) êtes le **responsable du traitement**. Flux vous donne les outils ; c'est à vous de les utiliser dans le respect de la loi.

## Avant la mise en service

- [ ] **Déclarer chaque caméra** sur **www.declarationcamera.be** (gratuit), au plus tard la veille de la mise en service. La déclaration est à mettre à jour chaque année et à chaque changement.
- [ ] **Désigner un responsable** : la personne ou le service qui décide des finalités et répond aux demandes. Ses coordonnées s'affichent dans FluxLite : Réglages › FluxLite › Responsable du traitement et Contact.
- [ ] **Choisir des finalités précises** : prévenir et constater les vols, les agressions, les dégradations ; identifier les auteurs. Toute autre utilisation (surveillance du personnel, marketing…) demande une analyse à part et souvent l'information ou la consultation des travailleurs (CCT n° 68 sur la surveillance par caméras).
- [ ] **Orienter les caméras** sur votre seul espace :
  - pas de voie publique, sauf l'accès immédiat à l'entrée ;
  - pas de propriétés voisines ;
  - pas de toilettes ni de vestiaires.
  - Les **zones de détection** et le **floutage** de Flux (Réglages › Confidentialité) aident à limiter ce qui est analysé.
- [ ] **Tenir le registre des activités de traitement d'images** prévu par la loi caméras, ainsi que le registre RGPD : modèle dans `MODELE-REGISTRE-DES-TRAITEMENTS.md`.
- [ ] **Analyse d'impact (AIPD)** : obligatoire si vous activez la reconnaissance des visages ou des expressions, et conseillée dans tous les cas pour un système « intelligent ». Modèle : `MODELE-AIPD.md`.

## Informer les personnes filmées

- [ ] **Pictogramme réglementaire** à chaque entrée du lieu filmé (arrêté royal du 10 février 2008), téléchargeable sur **www.besafe.be**, avec :
  - le nom du responsable ;
  - ses coordonnées ;
  - le lien vers l'information complète.
- [ ] **Information complète** disponible : affiche ou page web. Modèle de texte : `MODELE-AFFICHE-INFORMATION.md`. Mentionnez clairement si un **système d'analyse automatique** (détection de personnes, de véhicules, de plaques) est utilisé.
- [ ] Caméras **jamais cachées**.

## Pendant l'utilisation

- [ ] **Conservation** : un mois au maximum, sauf si les images servent de preuve d'une infraction, d'un dommage ou d'une incivilité, ou à identifier un auteur. Dans Flux :
  - Réglages › Vidéos › Conservation (vidéos des passages) ;
  - Réglages › FluxLite › Conserver les alertes ;
  - la purge de la base des personnes.
- [ ] **Accès limité** : seules les personnes autorisées voient les images. Dans FluxLite :
  - un compte par personne ;
  - une entreprise par client, avec seulement ses caméras ;
  - le pilotage autorisé au cas par cas.
- [ ] **Remettre les images à la police** sur demande, dans le cadre d'une enquête. Utilisez l'export du Lecteur ou du Journal.
- [ ] **Droit d'accès** : une personne filmée peut demander à voir les images où elle apparaît. Répondez dans un délai d'un mois en floutant les autres personnes (Réglages › Confidentialité).
- [ ] **Sécurité** :
  - PC Flux dans un local fermé ;
  - session Windows ou Linux avec mot de passe ;
  - mises à jour du système et de Flux ;
  - mode kiosque sous Linux pour un écran en libre vue.

## Fonctions sensibles de Flux

| Fonction | Ce qu'il faut savoir |
|---|---|
| Détection de personnes et de véhicules, comptage, zones | Couvertes par la loi caméras et le RGPD comme toute vidéosurveillance. |
| **Lecture des plaques** | Donnée personnelle. Justifiée pour un parking ou un accès de livraison ; à limiter à ces zones. Liste noire de plaques : seulement pour des faits constatés et documentés. |
| **Reconnaissance des visages / liste noire de personnes** | **Donnée biométrique** (RGPD, article 9) : **interdite par principe**. Pour un commerce, l'APD considère qu'il n'existe en pratique pas de base légale pour identifier les clients par leur visage. Le consentement explicite est très difficile à obtenir de façon valable. **Laissez cette fonction désactivée** sauf avis juridique contraire et AIPD. Voir `REGLEMENT-IA.md`. |
| **Expressions du visage** | Reconnaissance des émotions : **interdite sur le lieu de travail et dans l'enseignement** (règlement IA, article 5). Ne l'activez pas sur des caméras qui filment votre personnel. Ailleurs, informez les personnes. |
| Floutage des visages | Mesure de protection recommandée, notamment pour les écrans visibles par le public et les exports. |

## France (repères)

- Lieu ouvert au public : autorisation préfectorale (Code de la sécurité intérieure, art. L.251-1 et suivants).
- Lieu non ouvert au public : RGPD seul.
- Conservation : un mois au maximum en principe.
- Information par panneau.
- La CNIL considère la reconnaissance faciale des clients comme non conforme sans cadre légal spécifique.

*Ces informations sont générales et ne remplacent pas un avis juridique. Sources : police.be, besafe.be, autoriteprotectiondonnees.be, cnil.fr.*
