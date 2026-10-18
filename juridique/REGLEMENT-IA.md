# Flux et le règlement européen sur l'intelligence artificielle

*Règlement (UE) 2024/1689 (« AI Act »), modifié par le règlement (UE) 2026/1744 (« Omnibus numérique sur l'IA »), publié au Journal officiel le 24 juillet 2026. État au 18 octobre 2026 : à revérifier avant chaque version 1.x, car des lignes directrices et des normes sont encore publiées.*

## Rôles

- **DMS Security** met Flux sur le marché sous son nom : c'est le **fournisseur** des fonctions d'IA de Flux.
- Le **client** qui utilise Flux dans son magasin est le **déployeur**.
- Le fait que Flux soit un logiciel libre ne suffit pas à l'exclure du règlement, parce qu'il est **vendu** (avec services) et qu'il comporte des fonctions biométriques.

## Classement des fonctions de Flux

| Fonction | Classement | Conséquences |
|---|---|---|
| Détection de personnes, véhicules, objets ; zones ; comptage | **Risque minimal** | Aucune obligation spécifique ; bonnes pratiques (supervision humaine, documentation). |
| Lecture de plaques | Risque minimal au sens de l'IA Act | Mais donnée personnelle : RGPD et loi caméras. |
| Détection de visages **sans** identification (comptage, floutage) | Risque minimal | — |
| **Reconnaissance des visages / liste noire** (comparer un visage filmé à une base de personnes) | **Identification biométrique à distance** : système **à haut risque** (annexe III, point 1 a) | Obligations du fournisseur à partir du **2 décembre 2027**, date reportée par l'Omnibus : système de gestion des risques, qualité des données, documentation technique, journaux, contrôle humain, exactitude et robustesse, évaluation de conformité, marquage CE, enregistrement dans la base de l'UE. Obligations du déployeur : contrôle humain par des personnes formées, conservation des journaux, information, analyse d'impact sur les droits fondamentaux dans certains cas. **Et surtout le RGPD (article 9)** : sans base légale, l'usage est interdit dès aujourd'hui, indépendamment de l'IA Act. |
| **Expressions du visage** (reconnaissance des émotions) | **Interdite sur le lieu de travail et dans les établissements d'enseignement** (article 5.1.f, en vigueur depuis le 2 février 2025), sauf raisons médicales ou de sécurité. **Ailleurs : haut risque** (annexe III, point 1 c) et **obligation de transparence** (article 50.3, en vigueur depuis le 2 août 2026) : informer les personnes exposées. | Ne jamais l'activer sur des caméras qui filment le personnel. Sur les clients : informer (affiche) et réaliser une AIPD. |
| Catégorisation biométrique selon la race, les opinions, la religion, l'orientation sexuelle… | **Interdite** (article 5.1.g) | Flux ne le fait pas et ne doit pas être modifié pour le faire. |
| Constitution de bases de visages par moissonnage d'Internet ou de vidéosurveillance non ciblé | **Interdite** (article 5.1.e) | La liste noire de Flux ne doit contenir que des personnes ajoutées une à une, pour des faits documentés. Jamais d'ajout automatique de tous les visages vus. |

## Ce que DMS Security fait dès maintenant

1. **Par défaut, les fonctions biométriques sont présentées comme désactivées** dans les offres. Elles ne sont activées que chez un client qui a réalisé son AIPD et dispose d'une base légale.
2. **Aucune décision automatique** : Flux alerte, un humain décide. La documentation et la formation le rappellent.
3. **Transparence** : les applications et la documentation indiquent que Flux utilise de l'IA, et que Flux a été développé avec l'aide de l'IA (`DECLARATION-IA.md`).
4. **Journaux** : Flux conserve le journal des détections et des commandes, avec leur auteur.
5. **Avant le 2 décembre 2027** :
   - soit retirer la reconnaissance des visages et les expressions des versions vendues ;
   - soit préparer la documentation technique et l'évaluation de conformité « haut risque » (annexe VI, contrôle interne, si les normes harmonisées sont appliquées).
   - Décision à prendre avec un juriste.

## Pour le client (déployeur)

- Former les personnes qui utilisent Flux (article 4, maîtrise de l'IA, en vigueur depuis février 2025).
- Informer les personnes filmées de l'analyse automatique (affiche).
- Ne pas filmer le personnel avec les expressions activées.
- Ne pas utiliser la reconnaissance des visages sans base légale RGPD et AIPD.
