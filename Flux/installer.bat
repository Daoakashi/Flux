@echo off
rem ===========================================================================
rem  Flux - installation complete (double-cliquer)
rem  Python, Microsoft Visual C++, environnement, PyTorch (NVIDIA ou processeur),
rem  dependances, Deno, ffmpeg, modeles de detection, raccourci sur le bureau.
rem  Fonctionne sans winget. Peut etre relance sans risque (reparation / mise a jour).
rem ===========================================================================
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title Installation de Flux
set "OUTILS=%~dp0outils"
set "REDEMARRER="
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
echo [1/9] Python 3.12 introuvable : installation...
where winget >nul 2>&1 && (
    winget install -e --id Python.Python.3.12 --scope user --silent --accept-source-agreements --accept-package-agreements
    echo.
    echo   Python vient d'etre installe. Fermez cette fenetre et relancez installer.bat.
    pause
    exit /b 0
)
echo       Telechargement de l'installateur officiel de Python 3.12...
call :telecharger "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe" "%TEMP%\python-3.12-flux.exe"
if errorlevel 1 goto pas_de_python
"%TEMP%\python-3.12-flux.exe" /passive InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0
del /f /q "%TEMP%\python-3.12-flux.exe" >nul 2>&1
echo.
echo   Python vient d'etre installe. Fermez cette fenetre et relancez installer.bat.
pause
exit /b 0

:pas_de_python
echo   Installez Python 3.12 depuis https://www.python.org/downloads/ en cochant
echo   "Add python.exe to PATH", puis relancez installer.bat.
pause
exit /b 1

:py_ok
for /f "tokens=2" %%P in ('%PY% --version 2^>^&1') do set "PYVER=%%P"
echo [1/9] Python %PYVER% trouve.

rem ---------------------------------------------------------------------------
rem 2. Microsoft Visual C++ 2015-2022 (sans lui, PyTorch echoue : c10.dll / WinError 126)
rem ---------------------------------------------------------------------------
call :vcpp_ok
if not errorlevel 1 (
    echo [2/9] Microsoft Visual C++ deja installe.
    goto vc_fin
)
echo [2/9] Installation de Microsoft Visual C++ ^(necessaire a PyTorch^)...
echo       Une fenetre Windows va demander l'autorisation : cliquez sur "Oui".
call :telecharger "https://aka.ms/vs/17/release/vc_redist.x64.exe" "%TEMP%\vc_redist.x64.exe"
if errorlevel 1 goto vc_echec
"%TEMP%\vc_redist.x64.exe" /install /passive /norestart
set "VCCODE=%errorlevel%"
del /f /q "%TEMP%\vc_redist.x64.exe" >nul 2>&1
if "%VCCODE%"=="3010" set "REDEMARRER=1"
if "%VCCODE%"=="1641" set "REDEMARRER=1"
call :vcpp_ok
if not errorlevel 1 (
    echo       Microsoft Visual C++ installe.
    goto vc_fin
)
:vc_echec
if exist "%SystemRoot%\System32\vcruntime140_1.dll" if exist "%SystemRoot%\System32\msvcp140.dll" (
    echo       Mise a jour de Visual C++ impossible, mais une version est presente : on continue.
    goto vc_fin
)
echo.
echo       ATTENTION : Microsoft Visual C++ n'a pas pu etre installe automatiquement
echo       ^(autorisation refusee, compte sans droits administrateur ou pas de connexion^).
echo       Ouvrez ce lien dans le navigateur, installez le fichier, redemarrez le PC
echo       puis relancez installer.bat :
echo           https://aka.ms/vs/17/release/vc_redist.x64.exe
echo.
pause
exit /b 1
:vc_fin

rem ---------------------------------------------------------------------------
rem 3. Environnement virtuel (recree s'il est casse)
rem ---------------------------------------------------------------------------
if exist "venv\Scripts\python.exe" (
    "venv\Scripts\python.exe" -c "import sys" >nul 2>&1 || (
        echo [3/9] Environnement existant casse : recreation...
        rmdir /s /q venv
    )
)
if not exist "venv\Scripts\python.exe" (
    echo [3/9] Creation de l'environnement...
    %PY% -m venv venv
    if errorlevel 1 goto erreur
) else (
    echo [3/9] Environnement existant conserve.
)
set "VPY=%~dp0venv\Scripts\python.exe"
"%VPY%" -m pip install --upgrade pip --quiet --disable-pip-version-check
if errorlevel 1 goto erreur_reseau

rem ---------------------------------------------------------------------------
rem 4. PyTorch : version CUDA si une carte NVIDIA est presente
rem ---------------------------------------------------------------------------
"%VPY%" -c "import torch, sys; sys.exit(0 if torch.cuda.is_available() else 1)" >nul 2>&1 && (
    echo [4/9] PyTorch avec carte graphique deja installe.
    goto torch_ok
)
where nvidia-smi >nul 2>&1 || goto torch_cpu
echo [4/9] Carte NVIDIA detectee : installation de PyTorch avec CUDA ^(plusieurs Go, patientez^)...
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
"%VPY%" -c "import torch" >nul 2>&1 && (
    echo [4/9] PyTorch deja installe.
    goto torch_ok
)
echo [4/9] Pas de carte NVIDIA : installation de PyTorch pour processeur ^(environ 250 Mo^)...
"%VPY%" -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu --disable-pip-version-check
if errorlevel 1 "%VPY%" -m pip install torch torchvision --disable-pip-version-check
if errorlevel 1 goto erreur_reseau

:torch_ok
rem PyTorch doit pouvoir se charger : sinon c'est presque toujours Visual C++
"%VPY%" -c "import torch" >nul 2>&1 && goto torch_charge
echo.
echo       PyTorch est installe mais ne demarre pas :
"%VPY%" -c "import torch" 2>&1 | findstr /i "error dll"
if defined REDEMARRER (
    echo       Visual C++ vient d'etre installe : REDEMARREZ LE PC puis relancez installer.bat.
) else (
    echo       Reparation : reinstallation de Microsoft Visual C++...
    call :telecharger "https://aka.ms/vs/17/release/vc_redist.x64.exe" "%TEMP%\vc_redist.x64.exe"
    if not errorlevel 1 "%TEMP%\vc_redist.x64.exe" /repair /passive /norestart
    echo       Redemarrez le PC puis relancez installer.bat.
)
pause
exit /b 1
:torch_charge

rem ---------------------------------------------------------------------------
rem 5. Dependances de Flux
rem ---------------------------------------------------------------------------
echo [5/9] Installation des dependances...
"%VPY%" -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 goto erreur_reseau
rem yt-dlp toujours a jour (YouTube change souvent), OpenCV garde en version 4
"%VPY%" -m pip install --upgrade "yt-dlp[default]" --quiet --disable-pip-version-check
"%VPY%" -c "import cv2, sys; sys.exit(0 if int(cv2.__version__.split('.')[0]) < 5 else 1)" >nul 2>&1 || (
    echo       OpenCV 5 detecte : retour a la version 4...
    "%VPY%" -m pip uninstall -y opencv-python opencv-python-headless opencv-contrib-python --quiet
    "%VPY%" -m pip install "opencv-python>=4.10,<5" --quiet --disable-pip-version-check
)

rem ---------------------------------------------------------------------------
rem 6. Deno (YouTube) et ffmpeg (son des videos telechargees), ranges dans Flux\outils
rem    Telechargement direct : pas besoin de winget ni de redemarrer la session.
rem ---------------------------------------------------------------------------
echo [6/9] Deno et ffmpeg...
if not exist "%OUTILS%" mkdir "%OUTILS%"
if exist "%OUTILS%\deno.exe" (
    echo       Deno deja present.
) else (
    call :installer_deno
)
if exist "%OUTILS%\ffmpeg.exe" (
    echo       ffmpeg deja present.
) else (
    "%VPY%" -c "import imageio_ffmpeg, shutil, sys; shutil.copyfile(imageio_ffmpeg.get_ffmpeg_exe(), sys.argv[1])" "%OUTILS%\ffmpeg.exe" >nul 2>&1
    if exist "%OUTILS%\ffmpeg.exe" (
        echo       ffmpeg installe.
    ) else (
        echo       ffmpeg n'a pas pu etre installe : seul le mode "Telecharger puis lire" en sera affecte.
    )
)

rem ---------------------------------------------------------------------------
rem 7. Modeles de detection et de visages (telecharges maintenant, pas au premier lancement)
rem ---------------------------------------------------------------------------
echo [7/9] Modeles de detection...
"%VPY%" -m flux.outils modeles
if errorlevel 1 (
    echo.
    echo       ATTENTION : un ou plusieurs modeles n'ont pas pu etre telecharges ^(raison ci-dessus^).
    echo       Flux reessaiera au demarrage. Vous pouvez aussi les telecharger a la main :
    echo         https://github.com/ultralytics/assets/releases  ^(fichier yolo26n.pt^)
    echo       et les placer dans le dossier "modeles" de Flux.
    echo.
)

rem ---------------------------------------------------------------------------
rem 8. Verification
rem ---------------------------------------------------------------------------
echo [8/9] Verification...
"%VPY%" -m flux.outils verifier
if errorlevel 1 goto erreur

rem ---------------------------------------------------------------------------
rem 9. Raccourci sur le bureau
rem ---------------------------------------------------------------------------
echo [9/9] Raccourci sur le bureau...
"%VPY%" -m flux.outils icone "%~dp0flux.ico" >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -Command "$b=[Environment]::GetFolderPath('Desktop'); $s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $b 'Flux.lnk')); $s.TargetPath='%~dp0Flux.bat'; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%~dp0flux.ico'; $s.WindowStyle=7; $s.Description='Flux - surveillance video intelligente'; $s.Save()" >nul 2>&1

echo.
echo   ==========================================
echo    Installation terminee.
echo    Lancez Flux avec le raccourci du bureau
echo    ou en double-cliquant sur Flux.bat
echo   ==========================================
echo.
if defined REDEMARRER (
    echo   Windows demande un redemarrage pour terminer Visual C++ : redemarrez le PC avant de lancer Flux.
    echo.
    pause
    exit /b 0
)
choice /c ON /n /m "Lancer Flux maintenant ? (O/N) "
if errorlevel 2 exit /b 0
start "" "%~dp0Flux.bat"
exit /b 0

:erreur_reseau
echo.
echo   Un telechargement a echoue. Verifiez la connexion Internet ^(et un eventuel proxy,
echo   pare-feu ou antivirus qui bloquerait Python^), puis relancez installer.bat.
pause
exit /b 1

:erreur
echo.
echo   L'installation s'est arretee sur une erreur ^(voir les lignes ci-dessus^).
echo   Corrigez-la ou relancez installer.bat.
pause
exit /b 1

rem ===========================================================================
rem Sous-programmes
rem ===========================================================================

:telecharger
rem %1 = adresse, %2 = fichier de destination. curl (Windows 10/11), sinon PowerShell.
del /f /q "%~2" >nul 2>&1
where curl >nul 2>&1 && curl -fsSL --retry 3 --connect-timeout 30 -o "%~2" "%~1" >nul 2>&1
call :non_vide "%~2" && exit /b 0
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; $ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing -Uri '%~1' -OutFile '%~2'" >nul 2>&1
call :non_vide "%~2" && exit /b 0
del /f /q "%~2" >nul 2>&1
exit /b 1

:non_vide
if not exist "%~1" exit /b 1
if %~z1 GTR 0 exit /b 0
exit /b 1

:vcpp_ok
rem Runtime Visual C++ 2015-2022 x64 recent (14.40 ou plus) + DLL presentes
if not exist "%SystemRoot%\System32\vcruntime140_1.dll" exit /b 1
if not exist "%SystemRoot%\System32\msvcp140.dll" exit /b 1
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ok=$false; foreach($k in 'HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64','HKLM:\SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64'){ $v=Get-ItemProperty -Path $k -ErrorAction SilentlyContinue; if($v -and $v.Installed -eq 1 -and $v.Minor -ge 40){ $ok=$true } }; if($ok){ exit 0 } else { exit 1 }" >nul 2>&1
exit /b %errorlevel%

:installer_deno
echo       Telechargement de Deno ^(YouTube^)...
call :telecharger "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip" "%TEMP%\deno-flux.zip"
if errorlevel 1 goto deno_echec
tar -xf "%TEMP%\deno-flux.zip" -C "%OUTILS%" >nul 2>&1
if not exist "%OUTILS%\deno.exe" powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -Force -LiteralPath '%TEMP%\deno-flux.zip' -DestinationPath '%OUTILS%'" >nul 2>&1
del /f /q "%TEMP%\deno-flux.zip" >nul 2>&1
if exist "%OUTILS%\deno.exe" (
    echo       Deno installe.
    exit /b 0
)
:deno_echec
echo       Deno n'a pas pu etre telecharge : seul YouTube en sera affecte ^(relancez installer.bat plus tard^).
exit /b 0
