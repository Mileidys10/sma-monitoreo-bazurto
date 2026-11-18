#!/usr/bin/env bash
# Arranque en Linux/macOS: crea .venv, instala dependencias y lanza la Sala de control.
set -euo pipefail
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo "Instala Python 3.10+"; exit 1; }
[ -d .venv ] || python3 -m venv .venv
.venv/bin/python -m pip install --quiet -r requirements.txt
echo "Sala de control en http://127.0.0.1:8000 (Ctrl+C para detener)"
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
