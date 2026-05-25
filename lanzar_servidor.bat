@echo off
REM Arranca el servidor local de Izipega (FastAPI en localhost:8765).
REM La extension Chrome se conecta aqui para pedir respuestas con IA.

cd /d "%~dp0"

REM ── Verificar que Python este instalado y en el PATH ──────────────
REM Esta es la falla mas comun para usuarios no-devs: no tienen Python,
REM o lo tienen pero no marcaron "Add to PATH" al instalarlo.
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo ====================================================================
    echo    NO PUEDO ENCONTRAR PYTHON EN ESTE PC
    echo ====================================================================
    echo.
    echo    Izipega necesita Python 3.10 o superior para funcionar.
    echo.
    echo    QUE HACER:
    echo    ----------
    echo    1^) Abri tu navegador y entra a:
    echo.
    echo          https://www.python.org/downloads/
    echo.
    echo    2^) Descarga el instalador ^(boton amarillo grande^).
    echo.
    echo    3^) IMPORTANTE: en la PRIMERA pantalla del instalador,
    echo       MARCA la casilla que dice:
    echo.
    echo          [X] Add Python to PATH       ^<-- ESTA, abajo
    echo.
    echo       Si no marcas esa casilla, este error volvera a aparecer.
    echo.
    echo    4^) Termina la instalacion ^(siguiente, siguiente, instalar^).
    echo.
    echo    5^) CIERRA esta ventana y vuelve a hacer doble click en
    echo       lanzar_servidor.bat
    echo.
    echo ====================================================================
    echo    Si ya instalaste Python pero ves este error, probablemente
    echo    no marcaste "Add to PATH". Desinstala desde "Agregar o quitar
    echo    programas" y reinstala con la casilla marcada.
    echo ====================================================================
    echo.
    pause
    exit /b 1
)

REM ── Crear perfil.json desde plantilla si no existe (primer arranque) ─
if not exist "perfil.json" (
    if exist "perfil.json.template" (
        copy /Y "perfil.json.template" "perfil.json" >nul
        echo [INFO] perfil.json creado desde plantilla.
        echo         Subiras tu CV desde la extension para llenarlo.
        echo.
    )
)

REM ── Crear acceso directo en el escritorio (solo la primera vez) ───
if not exist "%USERPROFILE%\Desktop\Izipega.lnk" (
    echo [INFO] Creando acceso directo en el escritorio...
    powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop') + '\Izipega.lnk'); $s.TargetPath='%~f0'; $s.WorkingDirectory='%~dp0'; $s.WindowStyle=1; $s.Description='Lanzar servidor Izipega'; $s.Save()" >nul 2>&1
    if exist "%USERPROFILE%\Desktop\Izipega.lnk" (
        echo [OK] Acceso directo creado: Izipega.lnk
        echo.
    )
)

REM ── Crear venv la primera vez ─────────────────────────────────────
if not exist "venv\Scripts\python.exe" (
    echo [INFO] Primera vez: creando venv y instalando dependencias...
    echo.
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] No pude crear el venv. Tienes Python instalado?
        pause
        exit /b 1
    )
    "venv\Scripts\python.exe" -m pip install --upgrade pip
    "venv\Scripts\pip.exe" install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Fallo la instalacion de dependencias.
        pause
        exit /b 1
    )
    echo.
    echo [OK] venv listo. Continuando...
    echo.
)

echo ======================================================================
echo   IZIPEGA — servidor en http://localhost:8765
echo ======================================================================
echo.
echo   Cargar la extension en Chrome:
echo     1) chrome://extensions  -^>  activa 'Modo desarrollador'
echo     2) 'Cargar descomprimida' -^>  elige carpeta extension\
echo     3) En cualquier pagina con formulario, abre el icono y dale a Rellenar
echo.
echo   Ctrl+C para detener.
echo.

"venv\Scripts\python.exe" server.py
pause
