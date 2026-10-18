# Flux

Surveillance vidéo intelligente pour Windows et Linux : détection des personnes et des véhicules (YOLO26, RT-DETR), reconnaissance des visages, lecture des plaques, zones, alertes par mail et sur téléphone, vidéos des passages, groupes de caméras.

**Site officiel : [daoakashi.github.io](https://daoakashi.github.io/flux-web)** · **Version actuelle : 0.9.6 alpha** · [Notes de version](CHANGELOG.txt)

## Installation

1. Téléchargez la dernière version sur [le site](https://daoakashi.github.io/flux-web/telecharger.html) ou dans [Releases](https://github.com/Daoakashi/Flux/releases) : `Flux-x.y.z-windows.zip` pour Windows, `Flux-x.y.z-linux.zip` pour Linux. Décompressez-la dans un dossier à vous.
2. Lancez l'installateur de votre système :
   - **Windows** : double-clic sur `installer.bat`. Il installe Python, Microsoft Visual C++, PyTorch, les dépendances, Deno, ffmpeg et les modèles, puis crée un raccourci sur le bureau.
   - **Linux** (Linux Mint, Ubuntu, Debian) : ouvrez un terminal dans le dossier et tapez `bash installer.sh`. Il installe les paquets du système et les dépendances, puis crée une icône dans le menu et sur le bureau.
3. Lancez Flux avec le raccourci, ou avec `Flux.bat` (Windows) ou `./Flux.sh` (Linux).

Guides détaillés : [LISEZMOI.txt](LISEZMOI.txt) (Windows) et [LISEZMOI-LINUX.txt](LISEZMOI-LINUX.txt) (Linux).

## Mises à jour

Flux vérifie ce dépôt au démarrage et propose les nouvelles versions : Réglages › Mises à jour. Vos réglages, votre base de données, vos modèles et la clé FluxLite ne sont jamais remplacés.

**Publier une version** : mettez à jour `version.json`, ajoutez les notes en haut de `CHANGELOG.txt`, puis onglet **Actions › Publier une version de Flux › Run workflow**.

## FluxLite (application Android)

Vos clients voient les caméras et reçoivent les alertes sur leur téléphone. Activez le serveur dans la page **FluxLite**, puis scannez le QR code depuis l'application. Chaque entreprise ne voit que les caméras que vous lui attribuez. Les mêmes comptes ouvrent aussi l'**interface web** : `https://<adresse du PC>:47810` dans n'importe quel navigateur du même réseau (adresse affichée dans la page FluxLite ; à la première visite, acceptez le certificat créé par ce PC). Connexion chiffrée et liée à la clé de ce PC ; la clé est conservée par les mises à jour (dossier `fluxlite`, à sauvegarder).

## Configuration conseillée

- **Carte NVIDIA** : tous les niveaux de scan, y compris Précis et Maximum.
- **Sans carte graphique** (mini-PC, portable) : niveaux Rapide et Équilibré, avec le moteur OpenVINO choisi automatiquement.

## Données personnelles

Visages et plaques sont des données personnelles (RGPD). Informez les personnes filmées, limitez la durée de conservation et ne filmez pas au-delà de votre propriété. Flux fonctionne en local : aucune image ne quitte l'ordinateur, sauf les mails et notifications que vous configurez.

## Juridique, licence et IA

Flux, FluxLite, Flux Remote, l'interface web et le relais sont des logiciels libres publiés par **DMS Security** sous licence **GNU AGPL-3.0** (`LICENSE`). Tous les textes juridiques sont dans le dossier [`juridique/`](juridique/LISEZMOI.md) :
- mentions légales et conditions de vente ;
- conditions d'utilisation des applications ;
- confidentialité et accord de sous-traitance RGPD ;
- obligations du client (loi caméras), modèles de registre, d'analyse d'impact et d'affiche ;
- règlement européen sur l'IA et licences tierces.

Flux a été conçu et développé avec l'aide d'outils d'intelligence artificielle, sous la direction et la vérification de son auteur ([`juridique/DECLARATION-IA.md`](juridique/DECLARATION-IA.md)). Les analyses d'images tournent sur le PC du client ; aucune image n'est envoyée à un service d'IA.

**Feedback** : bouton « Feedback » dans chaque programme, ou dms.security.list@gmail.com, ou un ticket sur GitHub.

