# Flux — logiciel de vidéosurveillance intelligent
# Copyright (C) [ANNÉE] [NOM DE L'ENTREPRISE OU TON NOM]
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Onglet « À propos » de Flux : version, licence AGPL, code source et licences tierces.

Intégration :
    from about_tab import AboutTab
    tabs.addTab(AboutTab(version="Beta Version 0.x alpha"), "À propos")

Fichiers attendus à côté de l'application (et dans l'installeur PyInstaller) :
    LICENSE, THIRD_PARTY_LICENSES.md, licenses/*.txt
    PyInstaller : --add-data "LICENSE;." --add-data "THIRD_PARTY_LICENSES.md;." --add-data "licenses;licenses"
    (sous Linux, remplacer ";" par ":")
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QAbstractItemView,
)

# --- À compléter -----------------------------------------------------------
APP_NAME = "Flux"
PUBLISHER = "[NOM DE L'ENTREPRISE]"
COPYRIGHT_YEAR = "[ANNÉE]"
SOURCE_URL = "https://github.com/Daoakashi/Flux"
WEBSITE_URL = "[SITE WEB]"
CONTACT_EMAIL = "[E-MAIL]"
# ---------------------------------------------------------------------------

AGPL_URL = "https://www.gnu.org/licenses/agpl-3.0.html"

# (composant, licence, fichier de licence relatif à la racine ou URL, source)
THIRD_PARTY: list[tuple[str, str, str, str]] = [
    ("Ultralytics YOLO", "AGPL-3.0", "LICENSE", "https://github.com/ultralytics/ultralytics"),
    ("ultralytics-thop", "AGPL-3.0", "LICENSE", "https://github.com/ultralytics/thop"),
    ("ultralytics-platform", "AGPL-3.0", "LICENSE", "https://pypi.org/project/ultralytics-platform/"),
    ("Python", "PSF-2.0", "licenses/PSF-2.0.txt", "https://www.python.org"),
    ("PySide6 / Qt 6", "LGPL-3.0", "licenses/LGPL-3.0.txt", "https://code.qt.io/cgit/pyside/pyside-setup.git"),
    ("PyTorch", "BSD-3-Clause", "licenses/PyTorch-BSD-3-Clause.txt", "https://github.com/pytorch/pytorch"),
    ("torchvision", "BSD-3-Clause", "licenses/torchvision-BSD-3-Clause.txt", "https://github.com/pytorch/vision"),
    ("OpenCV", "Apache-2.0", "licenses/Apache-2.0.txt", "https://github.com/opencv/opencv"),
    ("FFmpeg (via OpenCV)", "LGPL-2.1", "licenses/LGPL-2.1.txt", "https://ffmpeg.org"),
    ("YuNet", "MIT", "licenses/YuNet-MIT.txt", "https://github.com/opencv/opencv_zoo"),
    ("OpenVINO", "Apache-2.0", "licenses/Apache-2.0.txt", "https://github.com/openvinotoolkit/openvino"),
    ("ONNX Runtime", "MIT", "licenses/ONNXRuntime-MIT.txt", "https://github.com/microsoft/onnxruntime"),
    ("NVIDIA CUDA / cuDNN", "Licence NVIDIA", "https://docs.nvidia.com/cuda/eula/", "https://developer.nvidia.com/cuda-toolkit"),
    ("NumPy", "BSD-3-Clause", "licenses/NumPy-BSD-3-Clause.txt", "https://github.com/numpy/numpy"),
    ("Matplotlib", "Matplotlib (PSF)", "licenses/Matplotlib.txt", "https://github.com/matplotlib/matplotlib"),
    ("Pillow", "MIT-CMU", "licenses/Pillow-MIT-CMU.txt", "https://github.com/python-pillow/Pillow"),
    ("PyYAML", "MIT", "licenses/PyYAML-MIT.txt", "https://github.com/yaml/pyyaml"),
    ("Polars", "MIT", "licenses/Polars-MIT.txt", "https://github.com/pola-rs/polars"),
    ("psutil", "BSD-3-Clause", "licenses/psutil-BSD-3-Clause.txt", "https://github.com/giampaolo/psutil"),
    ("nvidia-ml-py", "BSD", "https://pypi.org/project/nvidia-ml-py/", "https://pypi.org/project/nvidia-ml-py/"),
    ("Requests", "Apache-2.0", "licenses/Apache-2.0.txt", "https://github.com/psf/requests"),
    ("COCO (données d'entraînement)", "CC BY 4.0", "licenses/CC-BY-4.0.txt", "https://cocodataset.org"),
]


def resource_root() -> Path:
    """Dossier contenant LICENSE et licenses/, en développement comme une fois empaqueté."""
    if hasattr(sys, "_MEIPASS"):  # PyInstaller
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


class LicenseDialog(QDialog):
    """Affiche le texte complet d'une licence."""

    def __init__(self, title: str, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(720, 560)
        view = QPlainTextEdit(text)
        view.setReadOnly(True)
        view.setFont(QFont("Consolas, DejaVu Sans Mono, monospace", 9))
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(view)
        layout.addWidget(buttons)


class AboutTab(QWidget):
    """Onglet « À propos » conforme aux obligations de l'AGPL-3.0 et des licences tierces."""

    def __init__(self, version: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.root = resource_root()

        title = QLabel(f"<h2 style='margin:0'>{APP_NAME}</h2>")
        subtitle = QLabel(version)
        subtitle.setStyleSheet("color: palette(mid);")

        notice = QLabel(
            f"© {COPYRIGHT_YEAR} {PUBLISHER}<br><br>"
            f"{APP_NAME} est un logiciel libre distribué sous la "
            f"<a href='{AGPL_URL}'>GNU Affero General Public License v3.0</a>. "
            "Vous pouvez l'utiliser, l'étudier, le modifier et le redistribuer selon ses termes.<br><br>"
            f"<b>Code source :</b> <a href='{SOURCE_URL}'>{SOURCE_URL}</a><br>"
            f"<b>Site :</b> <a href='{WEBSITE_URL}'>{WEBSITE_URL}</a> · "
            f"<b>Contact :</b> <a href='mailto:{CONTACT_EMAIL}'>{CONTACT_EMAIL}</a><br><br>"
            "<b>Aucune garantie.</b> Ce logiciel est fourni « en l'état », sans garantie "
            "d'aucune sorte. Les détections reposent sur des modèles statistiques et peuvent "
            "manquer des événements ou produire de fausses alertes.<br><br>"
            "L'utilisateur est responsable du respect du RGPD, de la loi sur les caméras de "
            "surveillance et du règlement européen sur l'IA."
        )
        notice.setWordWrap(True)
        notice.setOpenExternalLinks(True)
        notice.setTextInteractionFlags(Qt.TextBrowserInteraction)

        license_btn = QPushButton("Lire la licence AGPL-3.0")
        license_btn.clicked.connect(lambda: self._show_file("Licence de Flux (AGPL-3.0)", "LICENSE"))
        source_btn = QPushButton("Ouvrir le code source")
        source_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(SOURCE_URL)))
        buttons = QHBoxLayout()
        buttons.addWidget(license_btn)
        buttons.addWidget(source_btn)
        buttons.addStretch()

        table_title = QLabel("<b>Composants tiers</b> — double-cliquez sur une ligne pour lire sa licence")
        self.table = QTableWidget(len(THIRD_PARTY), 2)
        self.table.setHorizontalHeaderLabels(["Composant", "Licence"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        for row, (name, lic, _, url) in enumerate(THIRD_PARTY):
            item = QTableWidgetItem(name)
            item.setToolTip(url)
            self.table.setItem(row, 0, item)
            self.table.setItem(row, 1, QTableWidgetItem(lic))
        self.table.cellDoubleClicked.connect(self._open_third_party)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(8)
        layout.addWidget(notice)
        layout.addLayout(buttons)
        layout.addSpacing(8)
        layout.addWidget(table_title)
        layout.addWidget(self.table, 1)

    def _show_file(self, title: str, relative: str) -> None:
        path = self.root / relative
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            QMessageBox.warning(
                self,
                "Licence introuvable",
                f"Le fichier {relative} est absent de l'installation.\n"
                f"Texte de la licence AGPL-3.0 : {AGPL_URL}",
            )
            return
        LicenseDialog(title, text, self).exec()

    def _open_third_party(self, row: int, _column: int) -> None:
        name, lic, target, url = THIRD_PARTY[row]
        if target.startswith("http"):
            QDesktopServices.openUrl(QUrl(target))
        else:
            self._show_file(f"{name} — {lic}", target)


if __name__ == "__main__":  # aperçu autonome : python about_tab.py
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    w = AboutTab(version="Beta Version 0.x alpha")
    w.resize(760, 720)
    w.show()
    sys.exit(app.exec())
