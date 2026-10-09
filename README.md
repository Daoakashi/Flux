# Flux

Surveillance vidéo intelligente pour Windows et Linux : détection des personnes et des véhicules (YOLO26, RT-DETR), reconnaissance des visages, lecture des plaques, zones, alertes par mail et sur téléphone, vidéos des passages, groupes de caméras.

**Version actuelle : 0.7.0 alpha** · [Notes de version](CHANGELOG.txt)

## Installation

1. Téléchargez la dernière version dans [Releases](https://github.com/Daoakashi/Flux/releases) (« Source code (zip) »), puis décompressez-la dans un dossier à vous.
2. Lancez l'installateur de votre système :
   - **Windows** : double-clic sur `installer.bat`. Il installe Python, Microsoft Visual C++, PyTorch, les dépendances, Deno, ffmpeg et les modèles, puis crée un raccourci sur le bureau.
   - **Linux** (Linux Mint, Ubuntu, Debian) : ouvrez un terminal dans le dossier et tapez `bash installer.sh`. Il installe les paquets du système et les dépendances, puis crée une icône dans le menu et sur le bureau.
3. Lancez Flux avec le raccourci, ou avec `Flux.bat` (Windows) ou `./Flux.sh` (Linux).

Guides détaillés : [LISEZMOI.txt](LISEZMOI.txt) (Windows) et [LISEZMOI-LINUX.txt](LISEZMOI-LINUX.txt) (Linux).

## Mises à jour

Flux vérifie ce dépôt au démarrage et propose les nouvelles versions : Réglages › Mises à jour. Vos réglages, votre base de données et vos modèles ne sont jamais remplacés.

## Configuration conseillée

- **Carte NVIDIA** : tous les niveaux de scan, y compris Précis et Maximum.
- **Sans carte graphique** (mini-PC, portable) : niveaux Rapide et Équilibré, avec le moteur OpenVINO choisi automatiquement.

## Données personnelles

Visages et plaques sont des données personnelles (RGPD). Informez les personnes filmées, limitez la durée de conservation et ne filmez pas au-delà de votre propriété. Flux fonctionne en local : aucune image ne quitte l'ordinateur, sauf les mails et notifications que vous configurez.
