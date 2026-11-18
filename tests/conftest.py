import os

# Las pruebas no deben depender de las fotos locales (no versionadas) de quien las ejecute.
os.environ.setdefault("SMA_FOTOS_DIR", os.path.join(os.path.dirname(__file__), "_sin_fotos"))
