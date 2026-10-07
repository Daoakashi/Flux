@echo off
rem ===========================================================================
rem  Flux - installation complete (double-cliquer)
rem  Python, environnement, PyTorch avec carte NVIDIA, dependances, Deno, ffmpeg,
rem  raccourci sur le bureau. Peut etre relance sans risque (reparation / mise a jour).
rem ===========================================================================
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title Installation de Flux
echo.
echo   ==========================================
echo    Installation de Flux
echo   ==========================================
echo.

rem ---------------------------------------------------------------------------
rem 1. Python 3.10 a 3.13 (3.12 de preference)
rem ---------------------------------------------------------------------------
set "PY="
for %%V in (3.12 3.11 3.13 3.10) do (
    py -%%V -c "import sys" >nul 2>&1 && (
        set "PY=py -%%V"
        goto py_ok
    )
)
python -c "import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,13) else 1)" >nul 2>&1 && (
    set "PY=python"
    goto py_ok
)
echo [1/7] Python 3.12 introuvable : installation...
where winget >nul 2>&1 || goto pas_de_winget_python
winget install -e --id Python.Python.3.12 --scope user --silent --accept-source-agreements --accept-package-agreements
echo.
echo   Python vient d'etre installe. Fermez cette fenetre et relancez installer.bat.
pause
exit /b 0

:pas_de_winget_python
echo   Installez Python 3.12 depuis https://www.python.org/downloads/ en cochant
echo   "Add python.exe to PATH", puis relancez installer.bat.
pause
exit /b 1

:py_ok
for /f "tokens=2" %%P in ('%PY% --version 2^>^&1') do set "PYVER=%%P"
echo [1/7] Python %PYVER% trouve.

rem ---------------------------------------------------------------------------
rem 2. Environnement virtuel (recree s'il est casse)
rem ---------------------------------------------------------------------------
if exist "venv\Scripts\python.exe" (
    "venv\Scripts\python.exe" -c "import sys" >nul 2>&1 || (
        echo [2/7] Environnement existant casse : recreation...
        rmdir /s /q venv
    )
)
if not exist "venv\Scripts\python.exe" (
    echo [2/7] Creation de l'environnement...
    %PY% -m venv venv
    if errorlevel 1 goto erreur
) else (
    echo [2/7] Environnement existant conserve.
)
set "VPY=%~dp0venv\Scripts\python.exe"
"%VPY%" -m pip install --upgrade pip --quiet --disable-pip-version-check
if errorlevel 1 goto erreur

rem ---------------------------------------------------------------------------
rem 3. PyTorch : version CUDA si une carte NVIDIA est presente
rem ---------------------------------------------------------------------------
"%VPY%" -c "import torch, sys; sys.exit(0 if torch.cuda.is_available() else 1)" >nul 2>&1 && (
    echo [3/7] PyTorch avec carte graphique deja installe.
    goto torch_ok
)
where nvidia-smi >nul 2>&1 || goto torch_cpu
echo [3/7] Carte NVIDIA detectee : installation de PyTorch avec CUDA ^(plusieurs Go, patientez^)...
for %%C in (cu130 cu129 cu128 cu126) do (
    "%VPY%" -m pip install --upgrade torch torchvision --index-url https://download.pytorch.org/whl/%%C --disable-pip-version-check
    "%VPY%" -c "import torch, sys; sys.exit(0 if torch.cuda.is_available() else 1)" >nul 2>&1 && (
        echo       PyTorch CUDA installe ^(%%C^).
        goto torch_ok
    )
)
echo       ATTENTION : PyTorch CUDA n'a pas pu etre installe. Mettez a jour le pilote NVIDIA
echo       ^(https://www.nvidia.com/Download^) puis relancez installer.bat.
echo       Installation de la version processeur en attendant...

:torch_cpu
"%VPY%" -c "import torch" >nul 2>&1 && goto torch_ok
echo [3/7] Pas de carte NVIDIA : installation de PyTorch ^(processeur^)...
"%VPY%" -m pip install torch torchvision --disable-pip-version-check
if errorlevel 1 goto erreur

:torch_ok

rem ---------------------------------------------------------------------------
rem 4. Dependances de Flux
rem ---------------------------------------------------------------------------
echo [4/7] Installation des dependances...
"%VPY%" -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 goto erreur
rem yt-dlp toujours a jour (YouTube change souvent), OpenCV garde en version 4
"%VPY%" -m pip install --upgrade "yt-dlp[default]" --quiet --disable-pip-version-check
"%VPY%" -c "import cv2, sys; sys.exit(0 if int(cv2.__version__.split('.')[0]) < 5 else 1)" >nul 2>&1 || (
    echo       OpenCV 5 detecte : retour a la version 4...
    "%VPY%" -m pip uninstall -y opencv-python opencv-python-headless opencv-contrib-python --quiet
    "%VPY%" -m pip install "opencv-python>=4.10,<5" --quiet --disable-pip-version-check
)

rem ---------------------------------------------------------------------------
rem 5. Deno (YouTube) et ffmpeg (telechargement avec le son)
rem ---------------------------------------------------------------------------
where winget >nul 2>&1 || (
    echo [5/7] winget absent : installez Deno et ffmpeg a la main ^(voir LISEZMOI.txt^).
    goto outils_ok
)
where deno >nul 2>&1 && (
    echo [5/7] Deno deja installe.
) || (
    echo [5/7] Installation de Deno ^(necessaire pour YouTube^)...
    winget install -e --id DenoLand.Deno --silent --accept-source-agreements --accept-package-agreements >nul
)
where ffmpeg >nul 2>&1 && (
    echo       ffmpeg deja installe.
) || (
    echo       Installation de ffmpeg ^(videos telechargees avec le son^)...
    winget install -e --id Gyan.FFmpeg --silent --accept-source-agreements --accept-package-agreements >nul
)
:outils_ok

rem ---------------------------------------------------------------------------
rem 6. Verification
rem ---------------------------------------------------------------------------
echo [6/7] Verification...
"%VPY%" -m flux.outils verifier
if errorlevel 1 goto erreur

rem ---------------------------------------------------------------------------
rem 7. Raccourci sur le bureau
rem ---------------------------------------------------------------------------
echo [7/7] Raccourci sur le bureau...
"%VPY%" -m flux.outils icone "%~dp0flux.ico" >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -Command "$b=[Environment]::GetFolderPath('Desktop'); $s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $b 'Flux.lnk')); $s.TargetPath='%~dp0Flux.bat'; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%~dp0flux.ico'; $s.WindowStyle=7; $s.Description='Flux - surveillance video intelligente'; $s.Save()" >nul 2>&1

echo.
echo   ==========================================
echo    Installation terminee.
echo    Lancez Flux avec le raccourci du bureau
echo    ou en double-cliquant sur Flux.bat
echo   ==========================================
echo.
choice /c ON /n /m "Lancer Flux maintenant ? (O/N) "
if errorlevel 2 exit /b 0
start "" "%~dp0Flux.bat"
exit /b 0

:erreur
echo.
echo   L'installation s'est arretee sur une erreur ^(voir les lignes ci-dessus^).
echo   Verifiez votre connexion Internet puis relancez installer.bat.
pause
exit /b 1
