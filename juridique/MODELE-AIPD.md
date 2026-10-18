# Modèle d'analyse d'impact (AIPD) — Vidéosurveillance intelligente avec Flux

*RGPD, article 35. Obligatoire avant d'activer la **reconnaissance des visages**, la **liste noire de personnes** ou les **expressions**. Fortement conseillée pour toute vidéosurveillance avec analyse automatique à grande échelle. À remplir par le client (responsable du traitement), avec l'aide de DMS Security si besoin. Conservez-la et mettez-la à jour à chaque changement important.*

## 1. Description

- **Lieu, nombre de caméras, zones filmées** : [ ]
- **Fonctions de Flux activées** (cocher) :
  - [ ] détection de personnes ;
  - [ ] détection de véhicules ;
  - [ ] zones et franchissements ;
  - [ ] comptage de la fréquentation ;
  - [ ] lecture des plaques ;
  - [ ] liste noire de plaques ;
  - [ ] détection des visages (sans identification) ;
  - [ ] **reconnaissance des visages / liste noire de personnes** ;
  - [ ] **expressions du visage** ;
  - [ ] floutage des visages ;
  - [ ] accès FluxLite / Flux Remote / web ;
  - [ ] accès hors site (relais).
- **Personnes ayant accès** (fonctions, nombre) : [ ]
- **Durées de conservation** : [ ]

## 2. Nécessité et proportionnalité

- Pourquoi la vidéosurveillance simple ne suffit-elle pas ? (faits constatés, statistiques de vols, agressions…) : [ ]
- Pour chaque fonction cochée en gras, quelle **base légale** de l'article 9.2 RGPD ? (consentement explicite, motif d'intérêt public important prévu par une loi…) : [ ]
  > En Belgique, aucune loi n'autorise aujourd'hui un commerce à identifier ses clients par leur visage. Le consentement des clients n'est en pratique pas valable (pas de vrai choix pour entrer dans le magasin). Sans base légale solide, **ne pas activer** la reconnaissance des visages.
- Moyens moins intrusifs envisagés (agent, antivols, détection sans identification, floutage) : [ ]
- Minimisation dans Flux :
  - zones de détection limitées à : [ ] ;
  - floutage : [oui/non] ;
  - comptes et caméras par entreprise : [ ] ;
  - conservation la plus courte possible : [ ].

## 3. Risques pour les personnes

| Risque | Gravité | Probabilité | Mesures dans Flux et dans l'organisation | Risque résiduel |
|---|---|---|---|---|
| Accès non autorisé aux images | [ ] | [ ] | Comptes personnels, mots de passe forts, sessions révocables, TLS avec clé épinglée, relais chiffré de bout en bout, PC sous clé | [ ] |
| Usage détourné (surveillance du personnel, curiosité) | [ ] | [ ] | Droits par caméra, journal des commandes, CGU acceptées, sanctions internes | [ ] |
| **Fausse identification** (personne confondue avec la liste noire) | [ ] | [ ] | Vérification humaine obligatoire avant toute action, seuil de similarité élevé, aucune décision automatique | [ ] |
| Discrimination (erreurs plus fréquentes selon l'âge, le teint, l'éclairage) | [ ] | [ ] | Pas d'action automatique, formation des agents, contrôle des erreurs | [ ] |
| Conservation excessive | [ ] | [ ] | Purges automatiques de Flux, contrôle mensuel | [ ] |
| Fuite d'un export (vidéo transmise) | [ ] | [ ] | Exports seulement sur instruction, floutage des tiers | [ ] |
| Indisponibilité (panne, vol du PC) | [ ] | [ ] | Onduleur, sauvegardes chiffrées, PC dans un local fermé | [ ] |

## 4. Avis et décision

- Avis du délégué à la protection des données (DPO), s'il existe : [ ]
- Avis des travailleurs ou de leurs représentants (si le personnel est filmé, CCT n° 68) : [ ]
- **Risque résiduel élevé ?** Si oui, **consulter l'APD avant la mise en service** (article 36 RGPD).
- Décision, nom et date : [ ]
