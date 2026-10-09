"""Réglages de Flux : schéma (types, valeurs par défaut, descriptions), lecture et écriture.

Chaque réglage est décrit une seule fois ici. L'éditeur de réglages, la sauvegarde et le
reste de l'application lisent tous ce schéma : un nouveau réglage ajouté ici apparaît
automatiquement dans l'éditeur.
"""

import copy
import json
import os
import shutil
import threading

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FICHIER_VERSION = os.path.join(RACINE, "version.json")


def lire_version(chemin=FICHIER_VERSION):
    """version.json : numéro de version, canal (alpha, beta, stable) et dépôt GitHub des mises à jour."""
    d = {"version": "0.3.0", "canal": "alpha", "depot": "", "date": ""}
    try:
        with open(chemin, encoding="utf-8") as f:
            lu = json.load(f)
        if isinstance(lu, dict):
            d.update({k: str(v) for k, v in lu.items() if k in d and v is not None})
    except (OSError, ValueError):
        pass
    return d


def ecrire_version(donnees, chemin=FICHIER_VERSION):
    d = lire_version(chemin)
    d.update(donnees)
    tmp = chemin + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
    os.replace(tmp, chemin)
    global APP_VERSION, APP_CANAL
    APP_VERSION, APP_CANAL = d["version"], d["canal"]
    return d


def libelle_version(version, canal=""):
    """« 0.3.0 » + « alpha » -> « 0.3 alpha »."""
    v = str(version).strip()
    if v.count(".") == 2 and v.endswith(".0"):
        v = v[:-2]
    return f"{v} {canal}".strip() if canal and canal != "stable" else v


_V = lire_version()
APP_NOM = "Flux"
APP_SOUS_TITRE = "Surveillance vidéo intelligente"
APP_VERSION = _V["version"]
APP_CANAL = _V["canal"]

FICHIER_CONFIG = os.path.join(RACINE, "config.json")
FICHIER_BASE = os.path.join(RACINE, "flux.db")
DOSSIER_MODELES = os.path.join(RACINE, "modeles")
DOSSIER_SORTIE_DEFAUT = os.path.join(RACINE, "detections")


class Reglage:
    __slots__ = ("cle", "categorie", "libelle", "type", "defaut", "description", "choix", "min", "max", "pas",
                 "suffixe", "avance", "groupe")

    def __init__(self, cle, categorie, libelle, type_, defaut, description="", choix=None, min_=None, max_=None,
                 pas=None, suffixe="", avance=False, groupe=None):
        self.cle, self.categorie, self.libelle, self.type, self.defaut = cle, categorie, libelle, type_, defaut
        self.description, self.choix, self.min, self.max, self.pas = description, choix, min_, max_, pas
        self.suffixe, self.avance, self.groupe = suffixe, avance, groupe

    def valider(self, valeur):
        """Convertit et borne une valeur ; renvoie la valeur par défaut si elle est invalide."""
        try:
            if self.type == "bool":
                return bool(valeur)
            if self.type == "int":
                v = int(round(float(valeur)))
            elif self.type == "float":
                v = float(valeur)
            elif self.type == "choix":
                cles = [c[0] for c in self.choix]
                return valeur if valeur in cles else self.defaut
            elif self.type == "couleur":
                v = str(valeur).strip()
                if len(v) == 7 and v.startswith("#") and all(c in "0123456789abcdefABCDEF" for c in v[1:]):
                    return v.upper()
                return self.defaut
            else:
                return "" if valeur is None else str(valeur)
            if self.min is not None:
                v = max(self.min, v)
            if self.max is not None:
                v = min(self.max, v)
            return v
        except (TypeError, ValueError):
            return self.defaut


R = Reglage
CATEGORIES = [
    ("apparence", "Apparence"), ("detection", "Détection"), ("basse_lumiere", "Basse lumière"),
    ("visages", "Visages et reconnaissance"), ("plaques", "Plaques"), ("base", "Base de données"),
    ("alertes", "Alertes et mail"), ("notifications", "Notifications (téléphone)"),
    ("clips", "Vidéos des passages"), ("lecteur", "Lecteur vidéo"),
    ("onvif", "Caméras ONVIF"), ("maj", "Mises à jour"), ("systeme", "Système"), ("developpeur", "Développeur"),
]
CATEGORIES_CACHEES = {"developpeur"}  # visibles seulement en mode développeur

SCHEMA = [
    # --- Apparence -------------------------------------------------------------------
    R("apparence.theme", "apparence", "Thème", "choix", "sombre", "Clair ou sombre, toujours en bleu.",
      [("sombre", "Sombre"), ("clair", "Clair")]),
    R("apparence.accent", "apparence", "Couleur d'accent", "couleur", "#2F7BFF",
      "Couleur des boutons principaux, des sélections et des repères."),
    R("apparence.police", "apparence", "Police", "choix", "systeme", "Famille de caractères de l'interface.",
      [("systeme", "Police du système"), ("Segoe UI", "Segoe UI"), ("Bahnschrift", "Bahnschrift"),
       ("Inter", "Inter"), ("Arial", "Arial"), ("Verdana", "Verdana")]),
    R("apparence.taille_police", "apparence", "Taille du texte", "int", 13, "", None, 10, 18, 1, " px"),
    R("apparence.arrondi", "apparence", "Arrondi des angles", "int", 10, "0 = angles droits.", None, 0, 20, 1, " px"),
    R("apparence.densite", "apparence", "Densité", "choix", "normale", "Espacement entre les éléments.",
      [("compacte", "Compacte"), ("normale", "Normale"), ("aeree", "Aérée")]),
    R("apparence.animations", "apparence", "Animations", "bool", True, "Désactivez pour une interface sans mouvement."),
    R("apparence.vitesse_animations", "apparence", "Vitesse des animations", "float", 1.0,
      "1 = normal, 0,5 = deux fois plus rapide, 2 = deux fois plus lent.", None, 0.4, 2.5, 0.1, " ×"),
    R("apparence.barre_compacte", "apparence", "Barre latérale réduite", "bool", False,
      "N'affiche que les icônes dans la barre de navigation."),
    R("apparence.ecran_demarrage", "apparence", "Écran de démarrage", "bool", True),
    R("apparence.opacite", "apparence", "Opacité de la fenêtre", "int", 100, "", None, 70, 100, 1, " %", True),

    # --- Détection ---------------------------------------------------------------------
    R("detection.niveau", "detection", "Niveau de scan", "choix", "equilibre",
      "Modèle et méthode d'analyse. Chaque caméra peut aussi choisir son propre niveau.",
      [("rapide", "Rapide"), ("equilibre", "Équilibré"), ("precis", "Précis"), ("maximum", "Maximum"),
       ("personnalise", "Personnalisé")]),
    R("detection.modele_personnalise", "detection", "Modèle personnalisé", "texte", "yolo11m.pt",
      "Utilisé avec le niveau Personnalisé : nom d'un modèle (yolo11x.pt, rtdetr-l.pt...) ou chemin vers "
      "un fichier .pt, .onnx ou .engine."),
    R("detection.taille_personnalisee", "detection", "Taille d'analyse (personnalisé)", "choix", "640", "",
      [("320", "320 px"), ("480", "480 px"), ("640", "640 px"), ("960", "960 px"), ("1280", "1280 px")]),
    R("detection.appareil", "detection", "Processeur de calcul", "choix", "auto",
      "Auto utilise la carte graphique NVIDIA si elle est disponible.",
      [("auto", "Automatique"), ("cuda", "Carte NVIDIA (CUDA)"), ("cpu", "Processeur (CPU)")]),
    R("detection.demi_precision", "detection", "Demi-précision (FP16)", "bool", True,
      "Sur carte NVIDIA : presque deux fois plus rapide, précision quasi identique.", avance=True),
    R("detection.confiance", "detection", "Confiance minimale", "float", 0.45, "", None, 0.10, 0.95, 0.05),
    R("detection.iou", "detection", "Fusion des cadres (IoU)", "float", 0.5,
      "Seuil au-delà duquel deux cadres qui se chevauchent sont fusionnés.", None, 0.2, 0.9, 0.05, "", True),
    R("detection.une_image_sur", "detection", "Analyser une image sur", "int", 1,
      "Augmentez pour soulager la machine avec beaucoup de caméras.", None, 1, 15, 1),
    R("detection.confirmation", "detection", "Analyses pour confirmer une personne", "int", 2,
      "Évite les fausses alertes dues à une détection isolée.", None, 1, 10, 1),
    R("detection.delai_absence", "detection", "Délai avant « départ »", "float", 3.0, "", None, 0.5, 60, 0.5, " s"),

    # --- Basse lumière -------------------------------------------------------------------
    R("basse_lumiere.mode", "basse_lumiere", "Amélioration basse lumière", "choix", "auto",
      "Automatique : activée seulement quand l'image est sombre.",
      [("auto", "Automatique"), ("toujours", "Toujours"), ("jamais", "Jamais")]),
    R("basse_lumiere.qualite", "basse_lumiere", "Qualité de l'amélioration", "choix", "auto",
      "Fine : bien meilleure dans le noir quasi total, mais environ 10 fois plus lente (calcul sur processeur). "
      "Automatique : fine pour les niveaux Précis et Maximum.",
      [("auto", "Automatique"), ("rapide", "Rapide"), ("fine", "Fine")]),
    R("basse_lumiere.seuil", "basse_lumiere", "Seuil de luminosité", "int", 40,
      "En dessous de cette luminosité moyenne (0-255), l'image est considérée comme sombre.", None, 5, 160, 1),
    R("basse_lumiere.double_passe", "basse_lumiere", "Double passe", "bool", True,
      "Analyse l'image d'origine et l'image améliorée puis fusionne : jamais moins bon que sans amélioration."),
    R("basse_lumiere.debruitage", "basse_lumiere", "Force du débruitage", "int", 10,
      "Le bruit des images de nuit gêne les petits modèles. 0 = désactivé.", None, 0, 25, 1),
    R("basse_lumiere.contraste", "basse_lumiere", "Contraste local (CLAHE)", "float", 1.8, "", None, 0.0, 4.0, 0.1, "",
      True),
    R("basse_lumiere.afficher", "basse_lumiere", "Afficher l'image améliorée", "bool", False,
      "Montre à l'écran l'image éclaircie au lieu de l'image brute."),

    # --- Visages -------------------------------------------------------------------------
    R("visages.detecteur", "visages", "Détecteur de visages", "choix", "yunet",
      "YuNet est bien plus précis ; Haar ne demande aucun téléchargement.",
      [("yunet", "YuNet (recommandé)"), ("haar", "Haar (simple)")]),
    R("visages.score_min", "visages", "Confiance minimale d'un visage", "float", 0.75, "", None, 0.4, 0.99, 0.01),
    R("visages.taille_min", "visages", "Taille minimale d'un visage", "int", 28, "", None, 12, 200, 2, " px"),
    R("visages.reconnaissance", "visages", "Reconnaître les personnes", "bool", True,
      "Compare chaque visage aux personnes de la base (modèle SFace)."),
    R("visages.seuil", "visages", "Seuil de reconnaissance", "float", 0.40,
      "Plus haut = moins d'erreurs mais plus de personnes non reconnues. Recommandé : 0,36 à 0,45.",
      None, 0.25, 0.75, 0.01),
    R("visages.inconnus_auto", "visages", "Créer les inconnus automatiquement", "bool", True,
      "Un visage jamais vu devient « Inconnu N », que vous pouvez renommer ensuite."),
    R("visages.taille_enrolement", "visages", "Taille minimale pour mémoriser", "int", 60,
      "Un visage plus petit est reconnu mais jamais enregistré, pour garder une base de qualité.",
      None, 30, 300, 5, " px", True),
    R("visages.max_par_personne", "visages", "Visages mémorisés par personne", "int", 12, "", None, 1, 50, 1, "", True),
    R("visages.lissage_expressions", "visages", "Lissage des expressions", "float", 0.45,
      "Plus bas = expression plus stable d'une image à l'autre.", None, 0.1, 1.0, 0.05, "", True),

    # --- Plaques -------------------------------------------------------------------------
    R("plaques.confiance_lecture", "plaques", "Confiance minimale de lecture", "float", 0.6, "", None, 0.3, 0.99, 0.01),
    R("plaques.relecture", "plaques", "Relire une plaque après", "float", 5.0, "", None, 1, 60, 1, " s", True),
    R("plaques.liste_noire", "plaques", "Plaques en liste noire", "texte", "",
      "Séparées par des virgules, avec ou sans tirets (1-ABC-234, AB123CD…). Nécessite « Lire les plaques » "
      "sur la caméra."),

    # --- Base de données -----------------------------------------------------------------
    R("base.actions", "base", "Enregistrer les actions", "bool", True,
      "Apparitions, identifications, entrées dans la zone, stationnements et départs."),
    R("base.miniatures", "base", "Photos dans la base", "bool", True, "Une petite photo pour chaque action."),
    R("base.stationnement", "base", "Stationnement prolongé après", "float", 30, "", None, 5, 1800, 5, " s"),
    R("base.retention", "base", "Conserver les actions", "int", 90, "0 = sans limite.", None, 0, 3650, 1, " jours"),

    # --- Alertes et mail -----------------------------------------------------------------
    R("alertes.declencheur", "alertes", "Déclencher une alerte pour", "choix", "toutes",
      "« Inconnues » attend quelques secondes pour laisser le temps à la reconnaissance. La liste noire déclenche "
      "toujours une alerte.",
      [("toutes", "Toute personne"), ("inconnues", "Personnes inconnues"), ("surveillees", "Personnes surveillées"),
       ("liste_noire", "Liste noire uniquement")], groupe="Alertes"),
    R("alertes.delai_identification", "alertes", "Délai d'identification", "float", 3.0,
      "Temps laissé à la reconnaissance faciale avant d'envoyer l'alerte, pour qu'elle contienne le nom.",
      None, 0.5, 30, 0.5, " s", True),
    R("alertes.photo", "alertes", "Photo à chaque alerte", "bool", True),
    R("alertes.liste_noire", "alertes", "Alerte prioritaire pour la liste noire", "bool", True,
      "Une personne ou une plaque en liste noire déclenche toujours une alerte, envoyée immédiatement "
      "(sans délai anti-spam) par mail et par notification."),
    R("mail.actif", "alertes", "Envoyer des mails", "bool", False, groupe="Mail"),
    R("mail.serveur", "alertes", "Serveur SMTP", "texte", "smtp.gmail.com"),
    R("mail.port", "alertes", "Port", "int", 465, "", None, 1, 65535, 1),
    R("mail.securite", "alertes", "Sécurité", "choix", "SSL", "",
      [("SSL", "SSL"), ("STARTTLS", "STARTTLS"), ("Aucune", "Aucune")]),
    R("mail.utilisateur", "alertes", "Identifiant", "texte", ""),
    R("mail.mot_de_passe", "alertes", "Mot de passe", "mdp", "",
      "Gmail : utilisez un mot de passe d'application."),
    R("mail.memoriser", "alertes", "Mémoriser le mot de passe", "bool", False,
      "Stocké en clair dans config.json : ne partagez pas ce fichier."),
    R("mail.expediteur", "alertes", "Expéditeur", "texte", "", "Facultatif."),
    R("mail.destinataire", "alertes", "Destinataire(s)", "texte", "", "Plusieurs adresses séparées par des virgules."),
    R("mail.photo", "alertes", "Joindre la photo", "bool", True),
    R("mail.delai", "alertes", "Délai entre deux mails", "float", 5.0,
      "Par caméra. Les détections pendant le délai sont comptées dans le mail suivant.", None, 0, 1440, 0.5, " min"),
    R("mail.journal_auto", "alertes", "Envoyer le journal toutes les", "float", 0, "0 = jamais.", None, 0, 10080, 10,
      " min"),

    # --- Notifications (téléphone, messageries) ------------------------------------------
    R("notif.actif", "notifications", "Envoyer des notifications", "bool", False,
      "Interrupteur général. Activez ensuite un ou plusieurs canaux ci-dessous.", groupe="Général"),
    R("notif.quand", "notifications", "Notifier", "choix", "alertes",
      "Les catégories du journal marquées « notifier » sont aussi envoyées (Journal › Catégories).",
      [("alertes", "Toutes les alertes"), ("liste_noire", "Liste noire uniquement"),
       ("categories", "Catégories du journal seulement")]),
    R("notif.delai", "notifications", "Délai entre deux notifications", "float", 2.0,
      "Par caméra. La liste noire passe toujours immédiatement.", None, 0, 1440, 0.5, " min"),
    R("notif.photo", "notifications", "Joindre la photo", "bool", True,
      "Telegram, ntfy et Discord. WhatsApp et SMS reçoivent seulement le texte."),
    R("telegram.actif", "notifications", "Telegram", "bool", False,
      "Gratuit et le plus complet (texte + photo). Créez un bot avec @BotFather.", groupe="Telegram"),
    R("telegram.jeton", "notifications", "Jeton du bot", "mdp", "", "Donné par @BotFather, ex. 123456:ABC-DEF…"),
    R("telegram.chat", "notifications", "Identifiant de discussion", "texte", "",
      "Envoyez un message à votre bot puis cliquez « Trouver mon identifiant » ci-dessus."),
    R("whatsapp.actif", "notifications", "WhatsApp", "bool", False, groupe="WhatsApp"),
    R("whatsapp.service", "notifications", "Service WhatsApp", "choix", "callmebot",
      "CallMeBot est gratuit (texte seul, pour votre propre numéro). Twilio est payant mais officiel.",
      [("callmebot", "CallMeBot (gratuit)"), ("twilio", "Twilio")]),
    R("whatsapp.numero", "notifications", "Numéro WhatsApp", "texte", "",
      "Format international, ex. +32470123456. Plusieurs numéros séparés par des virgules (Twilio)."),
    R("whatsapp.cle", "notifications", "Clé CallMeBot", "mdp", "",
      "Envoyez « I allow callmebot to send me messages » au +34 644 66 32 62 sur WhatsApp pour la recevoir."),
    R("sms.actif", "notifications", "SMS", "bool", False, "Via Twilio (payant).", groupe="SMS et appel (Twilio)"),
    R("sms.numero", "notifications", "Numéro(s) SMS", "texte", "", "Ex. +32470123456, séparés par des virgules."),
    R("appel.actif", "notifications", "Appel téléphonique", "bool", False,
      "Fait sonner le téléphone et lit l'alerte à voix haute (Twilio)."),
    R("appel.numero", "notifications", "Numéro à appeler", "texte", ""),
    R("appel.liste_noire_seulement", "notifications", "Appeler seulement pour la liste noire", "bool", True),
    R("twilio.sid", "notifications", "Twilio : Account SID", "texte", "", "Console Twilio › Account Info."),
    R("twilio.jeton", "notifications", "Twilio : Auth Token", "mdp", ""),
    R("twilio.numero", "notifications", "Twilio : numéro d'envoi", "texte", "",
      "Votre numéro Twilio (SMS, appel). Pour WhatsApp : le numéro WhatsApp Twilio (bac à sable : +14155238886)."),
    R("ntfy.actif", "notifications", "Notification push (ntfy)", "bool", False,
      "Gratuit, sans compte : installez l'application ntfy (Android, iPhone) et abonnez-vous au même sujet.",
      groupe="Notification push (ntfy)"),
    R("ntfy.sujet", "notifications", "Sujet ntfy", "texte", "",
      "Un nom difficile à deviner, ex. flux-maison-7f3k9q (toute personne qui le connaît peut lire)."),
    R("ntfy.serveur", "notifications", "Serveur ntfy", "texte", "https://ntfy.sh", "", avance=True),
    R("ntfy.jeton", "notifications", "Jeton d'accès ntfy", "mdp", "", "Seulement pour un serveur protégé.",
      avance=True),
    R("discord.actif", "notifications", "Discord", "bool", False, groupe="Discord et webhook"),
    R("discord.webhook", "notifications", "Webhook Discord", "mdp", "",
      "Paramètres du salon › Intégrations › Webhooks › Copier l'URL."),
    R("webhook.actif", "notifications", "Webhook générique", "bool", False,
      "Envoie un JSON (Home Assistant, n8n, Zapier…).", avance=True),
    R("webhook.url", "notifications", "Adresse du webhook", "texte", "", "", avance=True),

    # --- Vidéos des passages -----------------------------------------------------------
    R("clips.actif", "clips", "Enregistrer des vidéos des passages", "bool", True,
      "Flux garde en mémoire les dernières secondes de chaque caméra : la vidéo montre aussi ce qui s'est passé "
      "juste avant l'alerte."),
    R("clips.declencheur", "clips", "Enregistrer une vidéo pour", "choix", "alertes",
      "La liste noire déclenche toujours une vidéo.",
      [("alertes", "Chaque alerte"), ("passages", "Chaque passage (toute personne qui apparaît)"),
       ("liste_noire", "La liste noire uniquement")]),
    R("clips.avant", "clips", "Secondes avant l'alerte", "float", 3, "", None, 0, 10, 1, " s"),
    R("clips.apres", "clips", "Secondes après l'alerte", "float", 7,
      "Prolongé automatiquement si de nouvelles alertes arrivent pendant l'enregistrement.", None, 2, 60, 1, " s"),
    R("clips.duree_max", "clips", "Durée maximale d'une vidéo", "float", 30, "", None, 5, 120, 5, " s"),
    R("clips.delai", "clips", "Délai entre deux vidéos", "float", 1.0,
      "Par caméra, pour ne pas remplir le disque. La liste noire passe toujours.", None, 0, 60, 0.5, " min"),
    R("clips.envoyer", "clips", "Envoyer les vidéos", "bool", True,
      "Par Telegram, ntfy, Discord et webhook (s'ils sont activés dans Notifications). WhatsApp et SMS ne "
      "peuvent pas recevoir de vidéo sans la publier sur Internet : ils reçoivent l'alerte en texte.",
      groupe="Envoi"),
    R("clips.mail", "clips", "Joindre la vidéo aux mails", "bool", True,
      "Envoie un mail avec la vidéo (si les mails sont activés). Limite : 20 Mo."),
    R("clips.cadres", "clips", "Cadres de détection sur la vidéo", "bool", True, groupe="Qualité"),
    R("clips.largeur", "clips", "Largeur de la vidéo", "int", 640,
      "640 px : environ 1 Mo pour 10 s, lisible partout. Plus grand = plus net mais plus lourd.",
      None, 320, 1280, 32, " px"),
    R("clips.fps", "clips", "Images par seconde", "int", 12, "", None, 4, 25, 1, "", True),
    R("clips.conservation", "clips", "Conserver les vidéos", "int", 30, "0 = sans limite.", None, 0, 3650, 1,
      " jours"),

    # --- Lecteur ------------------------------------------------------------------------
    R("lecteur.mode", "lecteur", "Mode de lecture des liens", "choix", "direct",
      "Immédiate démarre tout de suite ; Télécharger donne la meilleure qualité (nécessite ffmpeg). "
      "Les vidéos en direct sont toujours lues immédiatement.",
      [("direct", "Lecture immédiate"), ("telecharger", "Télécharger puis lire")]),
    R("lecteur.qualite", "lecteur", "Qualité maximale", "choix", "1080", "",
      [("480", "480p"), ("720", "720p"), ("1080", "1080p"), ("max", "Maximum")]),
    R("lecteur.cookies", "lecteur", "Cookies du navigateur", "choix", "aucun",
      "Nécessaire pour Instagram et les vidéos réservées aux comptes connectés.",
      [("aucun", "Aucun"), ("chrome", "Chrome"), ("edge", "Edge"), ("firefox", "Firefox"), ("brave", "Brave"),
       ("opera", "Opera")]),
    R("lecteur.analyse", "lecteur", "Analyser les vidéos", "bool", True,
      "Applique la détection pendant la lecture."),
    R("lecteur.volume", "lecteur", "Volume", "int", 80, "", None, 0, 100, 1, " %"),

    # --- ONVIF ----------------------------------------------------------------------------
    R("onvif.delai_recherche", "onvif", "Durée de la recherche", "float", 3.0, "", None, 1, 15, 0.5, " s"),
    R("onvif.profil", "onvif", "Profil vidéo préféré", "choix", "principal",
      "Le flux secondaire est plus léger, utile avec beaucoup de caméras.",
      [("principal", "Principal (haute qualité)"), ("secondaire", "Secondaire (léger)")]),

    # --- Mises à jour --------------------------------------------------------------------
    R("maj.auto", "maj", "Vérifier au démarrage", "bool", True,
      "Cherche une nouvelle version sur GitHub à chaque lancement (quelques Ko, aucune donnée envoyée)."),
    R("maj.canal", "maj", "Versions proposées", "choix", "toutes",
      "« Stables » ignore les versions alpha et beta.",
      [("toutes", "Toutes (alpha, beta, stables)"), ("beta", "Beta et stables"), ("stables", "Stables uniquement")]),
    R("maj.depot", "maj", "Dépôt GitHub", "texte", "",
      "propriétaire/dépôt, ex. ilo-duran/flux. Vide = celui indiqué dans version.json."),
    R("maj.jeton", "maj", "Jeton GitHub", "mdp", "", "Seulement pour un dépôt privé (droit « contents: read »).",
      avance=True),
    R("maj.ignoree", "maj", "Version ignorée", "texte", "", "Vide = aucune.", avance=True),

    # --- Système ----------------------------------------------------------------------------
    R("systeme.dossier_sortie", "systeme", "Dossier des photos et vidéos", "texte", "",
      "Vide = dossier « detections » à côté de l'application."),
    R("systeme.tcp_rtsp", "systeme", "RTSP en TCP", "bool", True, "Plus stable que UDP sur la plupart des réseaux.",
      avance=True),
    R("systeme.faible_latence", "systeme", "Faible latence (RTSP, RTMP, UDP)", "bool", True,
      "Supprime la mémoire tampon réseau de FFmpeg : image plus proche du direct. Désactivez si un flux saccade "
      "ou se coupe sur un réseau instable (Wi-Fi faible)."),
    R("systeme.webcam", "systeme", "Pilote des webcams (Windows uniquement)", "choix", "auto",
      "Automatique : pilote par défaut de Windows, DirectShow en repli. Si l'image est brouillée (couleurs "
      "violettes, bandes), essayez l'autre pilote.",
      [("auto", "Automatique"), ("msmf", "Media Foundation"), ("dshow", "DirectShow")]),
    R("developpeur.actif", "systeme", "Mode développeur", "bool", False,
      "Affiche la catégorie Développeur : éléments visuels, version, éditeur de config.json. "
      "Astuce : cliquez 7 fois sur la version dans « À propos ».", avance=True),

    # --- Développeur -----------------------------------------------------------------------
    R("developpeur.nom", "developpeur", "Nom de l'application", "texte", "",
      "Vide = Flux. Affiché dans la barre latérale, le titre, l'écran de démarrage et les mails.",
      groupe="Identité visuelle"),
    R("developpeur.sous_titre", "developpeur", "Sous-titre", "texte", "", "Vide = « Surveillance vidéo intelligente »."),
    R("developpeur.version_affichee", "developpeur", "Version affichée", "texte", "",
      "Vide = version réelle (version.json). Ex. « Beta Version 0.3 alpha ». Ne change pas les mises à jour."),
    R("developpeur.titre_fenetre", "developpeur", "Titre de la fenêtre", "texte", "{nom}",
      "Variables : {nom}, {version}, {canal}."),
    R("developpeur.logo", "developpeur", "Logo personnalisé", "texte", "",
      "Chemin vers une image PNG ou JPG (carrée de préférence). Vide = logo Flux."),
    R("developpeur.badge", "developpeur", "Badge « DEV » dans la barre d'état", "bool", True),
    R("developpeur.duree_demarrage", "developpeur", "Durée minimale de l'écran de démarrage", "float", 0,
      "Pour régler l'écran de démarrage.", None, 0, 15, 0.5, " s"),
]

PAR_CLE = {r.cle: r for r in SCHEMA}
SECRETS = [r.cle for r in SCHEMA if r.type == "mdp"]


def identite(cfg=None):
    """Nom, sous-titre et version affichés (personnalisables en mode développeur)."""
    g = (lambda k: (cfg.get(k) or "").strip()) if cfg is not None and cfg.get("developpeur.actif") else (lambda k: "")
    nom = g("developpeur.nom") or APP_NOM
    version = g("developpeur.version_affichee") or libelle_version(APP_VERSION, APP_CANAL)
    titre = g("developpeur.titre_fenetre") or "{nom}"
    try:
        titre = titre.format(nom=nom, version=version, canal=APP_CANAL)
    except (KeyError, IndexError, ValueError):
        pass
    avec_mot = version if "version" in version.lower() else f"version {version}"
    return {"nom": nom, "sous_titre": g("developpeur.sous_titre") or APP_SOUS_TITRE, "version": version,
            "texte_version": avec_mot, "titre": titre, "logo": g("developpeur.logo")}

# Niveaux de scan : modèle, taille d'analyse, découpage en tuiles
NIVEAUX = {
    "rapide": {"nom": "Rapide", "modele": "yolo26n.pt", "taille": 640, "tuiles": False,
               "texte": "YOLO26n · 640 px. Temps réel partout, même sans carte graphique."},
    "equilibre": {"nom": "Équilibré", "modele": "yolo26s.pt", "taille": 640, "tuiles": False,
                  "texte": "YOLO26s · 640 px. Bon compromis pour plusieurs caméras."},
    "precis": {"nom": "Précis", "modele": "yolo26x.pt", "taille": 960, "tuiles": False,
               "texte": "YOLO26x · 960 px. Cibles lointaines et basse lumière ; carte graphique conseillée."},
    "maximum": {"nom": "Maximum", "modele": "rtdetr-x.pt", "taille": 640, "tuiles": True,
                "texte": "RT-DETR-X · 640 px + découpage 2×2. Le plus précis, surtout dans le noir ; "
                         "carte graphique requise."},
}
MODELES_CONNUS = ["yolo26n.pt", "yolo26s.pt", "yolo26m.pt", "yolo26l.pt", "yolo26x.pt", "yolo11n.pt", "yolo11s.pt",
                  "yolo11m.pt", "yolo11l.pt", "yolo11x.pt", "rtdetr-l.pt", "rtdetr-x.pt", "yolov8n.pt", "yolov8x.pt"]


def nom_modele(fichier):
    """« yolo26n.pt » -> « YOLO26n », « rtdetr-x.pt » -> « RT-DETR-X »."""
    base = os.path.splitext(os.path.basename(fichier))[0]
    if base.lower().startswith("rtdetr"):
        return "RT-DETR" + base[6:].upper()
    if base.lower().startswith("yolo"):
        return "YOLO" + base[4:]
    return base


def niveau_effectif(niveau, cfg):
    """Retourne (fichier_modele, taille, tuiles, libellé) pour un niveau."""
    if niveau == "personnalise":
        m = cfg.get("detection.modele_personnalise") or "yolo11m.pt"
        return m, int(cfg.get("detection.taille_personnalisee")), False, f"Personnalisé · {nom_modele(m)}"
    n = NIVEAUX.get(niveau, NIVEAUX["equilibre"])
    return n["modele"], n["taille"], n["tuiles"], f"{n['nom']} · {nom_modele(n['modele'])}"


INSTALLATEUR = "installer.bat" if os.name == "nt" else "installer.sh"


def profil_machine():
    """Réglages de départ adaptés à la machine, appliqués uniquement au tout premier lancement (pas de config.json).

    Petit processeur sans carte NVIDIA (mini PC type Celeron / N100, 4 coeurs ou moins) : niveau Rapide, vidéos et
    animations allégées. Sur une machine confortable, rien ne change."""
    coeurs = os.cpu_count() or 4
    nvidia = bool(shutil.which("nvidia-smi")) or os.path.exists("/proc/driver/nvidia/version")
    if nvidia or coeurs > 4:
        return {}
    return {"detection.niveau": "rapide", "detection.une_image_sur": 2, "apparence.animations": False,
            "clips.largeur": 480, "clips.fps": 8, "lecteur.qualite": "720"}


class Config:
    """Valeurs des réglages + liste des flux. Sûr entre threads ; prévient les abonnés des changements."""

    def __init__(self, chemin=FICHIER_CONFIG):
        self.chemin = chemin
        self._v = {r.cle: copy.deepcopy(r.defaut) for r in SCHEMA}
        self.flux = []
        self.groupes = []  # groupes de caméras : {nom, cameras, colonnes}
        self.fenetre = {}
        self._abonnes = []
        self._lock = threading.RLock()
        self.charger()

    # --- accès ----------------------------------------------------------------
    def get(self, cle):
        with self._lock:
            return self._v.get(cle, PAR_CLE[cle].defaut if cle in PAR_CLE else None)

    def __getitem__(self, cle):
        return self.get(cle)

    def set(self, cle, valeur, sauver=True):
        r = PAR_CLE.get(cle)
        if r is None:
            return
        v = r.valider(valeur)
        with self._lock:
            if self._v.get(cle) == v:
                return
            self._v[cle] = v
        if sauver:
            self.sauver()
        for f in list(self._abonnes):
            try:
                f(cle, v)
            except Exception:  # noqa: BLE001
                pass

    def reinitialiser(self, cle=None):
        cles = [cle] if cle else [r.cle for r in SCHEMA]
        for c in cles:
            self.set(c, PAR_CLE[c].defaut, sauver=False)
        self.sauver()

    def est_modifie(self, cle):
        return self.get(cle) != PAR_CLE[cle].defaut

    def abonner(self, fonction):
        self._abonnes.append(fonction)

    def section(self, prefixe):
        with self._lock:
            return {k.split(".", 1)[1]: v for k, v in self._v.items() if k.startswith(prefixe + ".")}

    def dossier_sortie(self):
        d = self.get("systeme.dossier_sortie").strip()
        return d or DOSSIER_SORTIE_DEFAUT

    # --- fichiers ----------------------------------------------------------------
    def charger(self):
        try:
            with open(self.chemin, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:  # premier lancement : réglages de départ adaptés à la machine
            with self._lock:
                for cle, v in profil_machine().items():
                    if cle in PAR_CLE:
                        self._v[cle] = PAR_CLE[cle].valider(v)
            return
        except (OSError, ValueError):
            return
        valeurs = data.get("reglages", {})
        # Migration depuis l'ancienne version (Vigie) : bloc "mail" et "animations"
        if "mail" in data and isinstance(data["mail"], dict):
            m = data["mail"]
            correspondance = {"actif": "mail.actif", "serveur": "mail.serveur", "port": "mail.port",
                              "securite": "mail.securite", "utilisateur": "mail.utilisateur",
                              "mot_de_passe": "mail.mot_de_passe", "memoriser_mdp": "mail.memoriser",
                              "expediteur": "mail.expediteur", "destinataire": "mail.destinataire",
                              "joindre_photo": "mail.photo", "delai_min": "mail.delai",
                              "journal_auto_min": "mail.journal_auto"}
            for a, b in correspondance.items():
                if a in m and b not in valeurs:
                    valeurs[b] = m[a]
        if "animations" in data and "apparence.animations" not in valeurs:
            valeurs["apparence.animations"] = data["animations"]
        with self._lock:
            for cle, v in valeurs.items():
                if cle in PAR_CLE:
                    self._v[cle] = PAR_CLE[cle].valider(v)
            self.flux = [f for f in data.get("flux", []) if isinstance(f, dict)]
            self.groupes = [g for g in data.get("groupes", []) if isinstance(g, dict) and g.get("nom")]
            self.fenetre = data.get("fenetre", {}) if isinstance(data.get("fenetre"), dict) else {}

    def exporter_dict(self, avec_secrets=False, pour_partage=False):
        """pour_partage : retire tous les mots de passe et jetons (fichier d'export à partager)."""
        with self._lock:
            valeurs = dict(self._v)
            if not avec_secrets and not valeurs.get("mail.memoriser"):
                valeurs["mail.mot_de_passe"] = ""
            if pour_partage:
                for k in SECRETS:
                    valeurs[k] = ""
            return {"application": APP_NOM, "version": APP_VERSION, "reglages": valeurs,
                    "flux": copy.deepcopy(self.flux), "groupes": copy.deepcopy(self.groupes),
                    "fenetre": dict(self.fenetre)}

    def recharger(self):
        """Relit config.json (après une modification à la main) et prévient les abonnés des valeurs changées."""
        avant = dict(self._v)
        with self._lock:
            self._v = {r.cle: copy.deepcopy(r.defaut) for r in SCHEMA}
        self.charger()
        changes = [k for k in self._v if self._v[k] != avant.get(k)]
        for k in changes:
            for f in list(self._abonnes):
                try:
                    f(k, self._v[k])
                except Exception:  # noqa: BLE001
                    pass
        return changes

    def sauver(self):
        donnees = self.exporter_dict()
        tmp = self.chemin + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(donnees, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.chemin)  # écriture atomique : jamais de fichier à moitié écrit
        except OSError:
            pass

    def importer_fichier(self, chemin):
        with open(chemin, encoding="utf-8") as f:
            data = json.load(f)
        n = 0
        for cle, v in data.get("reglages", {}).items():
            if cle in PAR_CLE and not (cle in SECRETS and not v):  # un export sans secrets n'efface pas les vôtres
                self.set(cle, v, sauver=False)
                n += 1
        self.sauver()
        return n
