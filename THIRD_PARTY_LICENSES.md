# Licences des composants tiers — Flux

Flux est distribué sous la licence GNU Affero General Public License v3.0 (voir `LICENSE`).
Il intègre les composants tiers ci-dessous, chacun soumis à sa propre licence.
Les textes complets se trouvent dans le dossier `licenses/`.

Liste à confirmer avec `pip-licenses --format=markdown --with-urls` dans l'environnement de Flux.

| Composant | Licence | Texte | Source |
| --- | --- | --- | --- |
| Ultralytics YOLO (code et poids des modèles) | AGPL-3.0 | `LICENSE` | https://github.com/ultralytics/ultralytics |
| ultralytics-thop | AGPL-3.0 | `LICENSE` | https://github.com/ultralytics/thop |
| ultralytics-platform | AGPL-3.0 | `LICENSE` | https://pypi.org/project/ultralytics-platform/ |
| Python | PSF-2.0 | `licenses/PSF-2.0.txt` | https://www.python.org |
| PySide6 / Qt for Python | LGPL-3.0 (+ GPL-3.0 auquel elle renvoie) | `licenses/LGPL-3.0.txt`, `licenses/GPL-3.0.txt` | https://code.qt.io/cgit/pyside/pyside-setup.git |
| Qt 6 (inclus dans PySide6) | LGPL-3.0 | `licenses/LGPL-3.0.txt` | https://download.qt.io/official_releases/qt/ |
| PyTorch | BSD-3-Clause | `licenses/PyTorch-BSD-3-Clause.txt` | https://github.com/pytorch/pytorch |
| torchvision | BSD-3-Clause | `licenses/torchvision-BSD-3-Clause.txt` | https://github.com/pytorch/vision |
| OpenCV (opencv-python) | Apache-2.0 | `licenses/Apache-2.0.txt` | https://github.com/opencv/opencv |
| FFmpeg (inclus dans opencv-python) | LGPL-2.1 | `licenses/LGPL-2.1.txt` | https://ffmpeg.org |
| YuNet (détection de visages) | MIT, © 2020 Shiqi Yu | `licenses/YuNet-MIT.txt` | https://github.com/opencv/opencv_zoo |
| OpenVINO (si utilisé) | Apache-2.0 | `licenses/Apache-2.0.txt` | https://github.com/openvinotoolkit/openvino |
| ONNX Runtime (si utilisé) | MIT | `licenses/ONNXRuntime-MIT.txt` | https://github.com/microsoft/onnxruntime |
| NVIDIA CUDA, cuDNN (bibliothèques d'exécution) | Licence propriétaire NVIDIA | voir lien | https://docs.nvidia.com/cuda/eula/ |
| NumPy | BSD-3-Clause | `licenses/NumPy-BSD-3-Clause.txt` | https://github.com/numpy/numpy |
| Matplotlib | Licence Matplotlib (type PSF) | `licenses/Matplotlib.txt` | https://github.com/matplotlib/matplotlib |
| Pillow | MIT-CMU (HPND) | `licenses/Pillow-MIT-CMU.txt` | https://github.com/python-pillow/Pillow |
| PyYAML | MIT | `licenses/PyYAML-MIT.txt` | https://github.com/yaml/pyyaml |
| Polars | MIT | `licenses/Polars-MIT.txt` | https://github.com/pola-rs/polars |
| psutil | BSD-3-Clause | `licenses/psutil-BSD-3-Clause.txt` | https://github.com/giampaolo/psutil |
| nvidia-ml-py | BSD | lien | https://pypi.org/project/nvidia-ml-py/ |
| Requests | Apache-2.0 | `licenses/Apache-2.0.txt` | https://github.com/psf/requests |
| Jeu de données COCO (pré-entraînement des modèles) | CC BY 4.0 (annotations) | `licenses/CC-BY-4.0.txt` | https://cocodataset.org |
| Lecture de plaques (OCR) | À COMPLÉTER | | |
| Reconnaissance d'expressions | À COMPLÉTER | | |

## Obligations particulières

- **PySide6 / Qt (LGPL-3.0)** : ces bibliothèques sont livrées comme fichiers séparés et peuvent être remplacées par l'utilisateur. Leur code source est disponible aux adresses ci-dessus.
- **FFmpeg (LGPL-2.1)** : livré en bibliothèque dynamique dans opencv-python, non modifié.
- **NVIDIA CUDA / cuDNN** : seules les bibliothèques d'exécution redistribuables sont livrées, non modifiées. Un pilote NVIDIA compatible est nécessaire.
- **COCO** : Lin et al., « Microsoft COCO: Common Objects in Context », ECCV 2014.
