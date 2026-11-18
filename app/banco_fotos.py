"""Banco opcional de fotografias locales para la camara del agente de residuos.

Cada foto se analiza una sola vez al arrancar; las que no contienen un contenedor se descartan.
En cada ronda se elige la foto cuyo nivel analizado mas se parece al nivel simulado de la zona.
Las fotos NO se versionan (carpeta ignorada por git): su licencia la documenta quien las aporta.
"""

from __future__ import annotations

import base64
import io
import random
from pathlib import Path
from typing import Optional

from PIL import Image

from app.vision_analyzer import analizar_imagen_contenedor

EXTENSIONES = {".png", ".jpg", ".jpeg", ".webp"}


class BancoFotos:
    def __init__(self, carpeta: Path, umbral_critico: float = 80.0, rng: Optional[random.Random] = None) -> None:
        self.rng = rng or random.Random()
        self.fotos: list[dict[str, object]] = []
        self.descartadas: list[str] = []
        if not carpeta.is_dir():
            return
        for archivo in sorted(carpeta.iterdir()):
            if archivo.suffix.lower() not in EXTENSIONES:
                continue
            try:
                imagen = Image.open(archivo).convert("RGB")
                imagen.thumbnail((640, 640))
                buf = io.BytesIO()
                imagen.save(buf, format="PNG")
                data_url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
                res = analizar_imagen_contenedor(
                    image_input=data_url, preset_name=None, umbral_critico=umbral_critico, gemini_api_key=None
                )
            except Exception:  # archivo corrupto o formato no soportado: se omite sin detener el sistema
                self.descartadas.append(archivo.name)
                continue
            if not res.get("contenedor_detectado", True):
                self.descartadas.append(archivo.name)
                continue
            self.fotos.append(
                {"nombre": archivo.name, "data_url": data_url, "nivel": float(res["nivel_llenado_visual"])}
            )

    def __len__(self) -> int:
        return len(self.fotos)

    def elegir(self, nivel: float) -> Optional[str]:
        """Devuelve la foto (data URL) mas parecida al nivel simulado, o None si el banco esta vacio."""
        if not self.fotos:
            return None
        cercanas = sorted(self.fotos, key=lambda f: abs(float(f["nivel"]) - nivel))[:2]
        return str(self.rng.choice(cercanas)["data_url"])

    def resumen(self) -> str:
        return f"{len(self.fotos)} fotos usables, {len(self.descartadas)} descartadas"
