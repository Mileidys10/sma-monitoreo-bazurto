@echo off
cd /d "%~dp0"
echo ============================================================
echo   SMAMonitoreoBazurto - Consola Multiagente Python + SQLite
echo ============================================================
where python >nul 2>&1
if errorlevel 1 (
    echo [AVISO] Python no esta instalado en este equipo.
    echo Abriendo el modo autonomo offline en el navegador...
    start "" "%~dp0index.html"
    pause
    exit /b 0
)
if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Creando entorno virtual local .venv ...
    python -m venv .venv
)
echo [2/3] Verificando dependencias de requirements.txt ...
".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
echo [3/3] Abriendo consola en http://127.0.0.1:8000 ...
start "" "http://127.0.0.1:8000"
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
