"""Fichiers propres à chaque système : la version Windows et la version Linux de Flux ne contiennent que les leurs.

Utilisé par les mises à jour (choix de la bonne archive) et par la publication (création des deux archives).
Aucune dépendance : ce fichier est aussi lu par le robot de publication de GitHub.
"""
import os

WINDOWS = "windows"
LINUX = "linux"
PLATEFORMES = (WINDOWS, LINUX)

# Fichiers (à la racine de Flux) qui ne servent que sur un système
SEULEMENT = {
    WINDOWS: {"Flux.bat", "installer.bat", "LISEZMOI.txt"},
    LINUX: {"Flux.sh", "installer.sh", "kiosque.sh", "LISEZMOI-LINUX.txt"},
}
# Scripts rendus exécutables dans l'archive Linux
EXECUTABLES = {"Flux.sh", "installer.sh", "kiosque.sh"}


def actuelle():
    return WINDOWS if os.name == "nt" else LINUX


def pour(chemin_relatif, plateforme):
    """Vrai si ce fichier (chemin relatif à la racine de Flux) fait partie de la version de ce système."""
    nom = chemin_relatif.replace("\\", "/")
    return not any(p != plateforme and nom in fichiers for p, fichiers in SEULEMENT.items())


def nom_archive(version, canal, plateforme):
    suffixe = "" if canal in ("", "stable") else f"-{canal}"
    return f"Flux-{version}{suffixe}-{plateforme}.zip"


def plateforme_archive(nom_fichier):
    """« Flux-0.9.6-alpha-linux.zip » -> « linux » ; archive commune (anciennes versions) -> None."""
    n = nom_fichier.lower()
    for p in PLATEFORMES:
        if f"-{p}." in n or f"_{p}." in n or n.endswith(f"-{p}"):
            return p
    return None
