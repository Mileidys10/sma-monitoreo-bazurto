@echo off
cd /d "%~dp0"
echo ============================================================
echo   SMA Bazurto - Sala de control (LangGraph real)
echo ============================================================
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 3.10 o superior no esta instalado. Descargalo de https://www.python.org/downloads/
    echo Marca la casilla "Add python.exe to PATH" al instalar y vuelve a abrir este archivo.
    pause
    exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Creando entorno virtual .venv ...
    python -m venv .venv || goto :fallo
)
echo [2/3] Instalando dependencias (la primera vez necesita internet) ...
".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt || goto :fallo
echo [3/3] Iniciando. Se abrira http://127.0.0.1:8000 - cierra esta ventana para detener.
start "" "http://127.0.0.1:8000"
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
exit /b 0
:fallo
echo [ERROR] No se pudo preparar el entorno. Revisa tu conexion a internet y vuelve a intentar.
pause
exit /b 1
