"""Visión por computador real (Pillow) para AgenteSensorResiduos.analizarImagenes()."""

import base64
import io
import math
from pathlib import Path
from typing import Any, Optional

from PIL import Image, ImageDraw, ImageFont

SAMPLE_FILES = {
    "contenedor_limpio.png": {
        "titulo": "Escena 1: Contenedor Limpio (~18%)",
        "descripcion": "Contenedor municipal vacío en su mayoría y piso despejado.",
        "fill_ratio": 0.18,
        "bolsas_suelo": 0,
    },
    "contenedor_medio.png": {
        "titulo": "Escena 2: Contenedor Nivel Medio (~64%)",
        "descripcion": "Contenedor con acumulación intermedia sin desbordamiento externo.",
        "fill_ratio": 0.64,
        "bolsas_suelo": 0,
    },
    "contenedor_critico.png": {
        "titulo": "Escena 3: Contenedor Crítico Desbordado (~94%)",
        "descripcion": "Contenedor rebasado con bolsas acumuladas en el suelo perimetral.",
        "fill_ratio": 0.94,
        "bolsas_suelo": 4,
    },
}


def _draw_trash_bag(draw: ImageDraw.ImageDraw, cx: int, cy: int, rx: int, ry: int, base_color: tuple[int, int, int]) -> None:
    """Dibuja una bolsa o bulto de residuo con volumen y brillo para realismo de píxeles."""
    draw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=base_color, outline=(18, 20, 24), width=2)
    highlight = (
        min(base_color[0] + 28, 255),
        min(base_color[1] + 28, 255),
        min(base_color[2] + 28, 255),
    )
    draw.ellipse((cx - rx // 2, cy - ry // 2, cx + rx // 4, cy), fill=highlight)


def _generate_scene_image(fill_ratio: float, bolsas_suelo: int, dest_path: Path) -> None:
    """Genera una escena sintética realista de un punto de acopio en Bazurto (480x320)."""
    width, height = 480, 320
    img = Image.new("RGB", (width, height), (218, 224, 228))
    draw = ImageDraw.Draw(img)

    # Fondo: pared del mercado (arriba) y pavimento claro (abajo)
    draw.rectangle((0, 0, width, int(height * 0.76)), fill=(224, 229, 232))
    draw.rectangle((0, int(height * 0.76), width, height), fill=(198, 202, 204))
    draw.line((0, int(height * 0.76), width, int(height * 0.76)), fill=(165, 170, 174), width=3)

    # Marco del contenedor centrado en ROI [22%..78% x, 18%..78% y]
    c_left, c_top = 104, 56
    c_right, c_bottom = 376, 248
    interior_left, interior_top = c_left + 10, c_top + 10
    interior_right, interior_bottom = c_right - 10, c_bottom - 10

    # Cuerpo verde exterior del contenedor
    draw.rectangle((c_left, c_top, c_right, c_bottom), fill=(30, 108, 66), outline=(18, 66, 40), width=4)
    # Interior metálico claro visible cuando está vacío
    draw.rectangle((interior_left, interior_top, interior_right, interior_bottom), fill=(214, 220, 224))

    # Nivel de llenado real dentro del interior del contenedor
    interior_h = interior_bottom - interior_top
    fill_px = int(interior_h * min(fill_ratio, 1.0))
    fill_y = interior_bottom - fill_px

    if fill_px > 0:
        # Fondo de masa de residuos
        draw.rectangle((interior_left, fill_y, interior_right, interior_bottom), fill=(52, 56, 50))
        # Capas de bolsas, cajas y materia orgánica dentro de la zona llena
        palette = [
            (32, 35, 40),    # bolsa negra
            (45, 52, 62),    # bolsa gris oscura
            (152, 106, 62),  # cartón húmedo
            (72, 108, 48),   # orgánico vegetal
            (34, 88, 148),   # plástico azul
            (138, 64, 42),   # residuos varios
        ]
        idx = 0
        y_cursor = interior_bottom - 14
        while y_cursor >= fill_y + 6:
            x_cursor = interior_left + 20
            while x_cursor <= interior_right - 20:
                color = palette[idx % len(palette)]
                rx = 18 + (idx % 3) * 4
                ry = 13 + (idx % 2) * 3
                _draw_trash_bag(draw, x_cursor, max(y_cursor, fill_y + 10), rx, ry, color)
                x_cursor += 32
                idx += 1
            y_cursor -= 20

    # Si hay desbordamiento (>85%), bolsas sobresaliendo claramente por encima del borde superior
    if fill_ratio >= 0.85:
        overflow_bags = [
            (155, c_top - 16, 30, 18, (34, 38, 44)),
            (215, c_top - 22, 34, 20, (148, 102, 58)),
            (278, c_top - 20, 32, 19, (38, 86, 142)),
            (330, c_top - 14, 28, 17, (68, 104, 46)),
        ]
        for bx, by, brx, bry, col in overflow_bags:
            _draw_trash_bag(draw, bx, by, brx, bry, col)

    # Asas laterales exteriores del contenedor (sin tapar ni ensuciar el interior)
    draw.rectangle((c_left - 8, c_top + 60, c_left + 4, c_top + 100), fill=(22, 82, 50))
    draw.rectangle((c_right - 4, c_top + 60, c_right + 8, c_top + 100), fill=(22, 82, 50))

    # Bolsas en el suelo perimetral (ROI suelo: y 78%..96% -> y=250..308)
    if bolsas_suelo > 0:
        ground_positions = [
            (62, 278, 26, 17, (32, 36, 42)),
            (156, 284, 28, 16, (76, 108, 48)),
            (318, 282, 27, 17, (34, 84, 140)),
            (414, 276, 26, 18, (40, 44, 50)),
        ]
        for bx, by, brx, bry, col in ground_positions[:bolsas_suelo]:
            _draw_trash_bag(draw, bx, by, brx, bry, col)

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest_path, format="PNG")


def ensure_sample_images(static_dir: Path) -> list[dict[str, Any]]:
    """Garantiza que existan las 3 escenas de muestra en static/samples y retorna su metadata."""
    samples_dir = static_dir / "samples"
    samples_dir.mkdir(parents=True, exist_ok=True)
    catalog: list[dict[str, Any]] = []
    for filename, meta in SAMPLE_FILES.items():
        path = samples_dir / filename
        if not path.exists():
            _generate_scene_image(meta["fill_ratio"], meta["bolsas_suelo"], path)
        catalog.append(
            {
                "filename": filename,
                "url": f"/static/samples/{filename}",
                "titulo": meta["titulo"],
                "descripcion": meta["descripcion"],
            }
        )
    return catalog


def _load_image_from_input(
    image_input: Optional[str],
    preset_name: Optional[str],
    static_dir: Path,
) -> tuple[Image.Image, str]:
    """Carga un PIL.Image real desde Data URL Base64 o desde una escena de muestra."""
    if image_input:
        payload = image_input.strip()
        if "," in payload and payload.startswith("data:"):
            payload = payload.split(",", 1)[1]
        raw_bytes = base64.b64decode(payload)
        img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
        return img, "imagen_usuario_o_webcam"

    ensure_sample_images(static_dir)
    chosen = preset_name if preset_name in SAMPLE_FILES else "contenedor_critico.png"
    sample_path = static_dir / "samples" / chosen
    img = Image.open(sample_path).convert("RGB")
    return img, chosen


def _pixel_is_waste(r: int, g: int, b: int, bg_rgb: tuple[float, float, float]) -> bool:
    """Determina si un píxel difiere del fondo limpio (oscuro, saturado o distinto al entorno)."""
    luma = 0.299 * r + 0.587 * g + 0.114 * b
    sat = max(r, g, b) - min(r, g, b)
    dist_bg = math.sqrt((r - bg_rgb[0]) ** 2 + (g - bg_rgb[1]) ** 2 + (b - bg_rgb[2]) ** 2)
    # Residuos oscuros (bolsas negras/grises), objetos saturados (orgánicos/plásticos/cartón) o contraste fuerte
    return (luma < 145 and dist_bg > 38) or (sat > 38 and dist_bg > 32) or (dist_bg > 68)


def analizar_imagen_contenedor(
    image_input: Optional[str] = None,
    preset_name: Optional[str] = None,
    static_dir: Optional[Path] = None,
    umbral_critico: float = 80.0,
) -> dict[str, Any]:
    """Analiza píxel a píxel la imagen de un contenedor y devuelve nivel visual, bolsas y imagen anotada."""
    resolved_static = static_dir or (Path(__file__).resolve().parent / "static")
    orig_img, fuente = _load_image_from_input(image_input, preset_name, resolved_static)

    # Normalizar tamaño para análisis rápido y determinístico
    ana_w, ana_h = 240, 160
    small = orig_img.resize((ana_w, ana_h), Image.Resampling.BILINEAR)
    px = small.load()
    if px is None:
        raise ValueError("No se pudieron leer los píxeles de la imagen.")

    # Estimar color base de fondo limpio tomando banda superior neutra (pared/cielo) y piso inferior esquina
    wall_samples: list[tuple[int, int, int]] = []
    for y in range(4, 18):
        for x in range(10, 48):
            wall_samples.append(px[x, y])  # type: ignore[index]
        for x in range(ana_w - 48, ana_w - 10):
            wall_samples.append(px[x, y])  # type: ignore[index]

    bg_wall = (
        sum(c[0] for c in wall_samples) / len(wall_samples),
        sum(c[1] for c in wall_samples) / len(wall_samples),
        sum(c[2] for c in wall_samples) / len(wall_samples),
    )

    floor_samples: list[tuple[int, int, int]] = []
    for y in range(int(ana_h * 0.80), int(ana_h * 0.94)):
        for x in range(4, 14):
            floor_samples.append(px[x, y])  # type: ignore[index]
        for x in range(ana_w - 14, ana_w - 4):
            floor_samples.append(px[x, y])  # type: ignore[index]

    bg_floor = (
        sum(c[0] for c in floor_samples) / len(floor_samples),
        sum(c[1] for c in floor_samples) / len(floor_samples),
        sum(c[2] for c in floor_samples) / len(floor_samples),
    )

    # 1. ROI Contenedor interior: x=[25%..75%], y=[22%..74%]
    rx1, rx2 = int(ana_w * 0.25), int(ana_w * 0.75)
    ry1, ry2 = int(ana_h * 0.22), int(ana_h * 0.74)

    waste_rows = 0
    total_rows = max(ry2 - ry1, 1)
    highest_waste_row = ry2
    waste_pixels_total = 0
    roi_pixels_total = max((rx2 - rx1) * (ry2 - ry1), 1)

    for y in range(ry1, ry2):
        row_waste = 0
        for x in range(rx1, rx2):
            r, g, b = px[x, y]  # type: ignore[index]
            if _pixel_is_waste(r, g, b, bg_wall):
                row_waste += 1
        row_ratio = row_waste / max(rx2 - rx1, 1)
        waste_pixels_total += row_waste
        # Una fila se considera ocupada por residuos si >=30% de su ancho tiene material
        if row_ratio >= 0.30:
            waste_rows += 1
            if y < highest_waste_row:
                highest_waste_row = y

    # Revisar también desbordamiento encima del borde superior (y=[6%..16%], x=[25%..75%])
    overflow_top_pixels = 0
    oy1, oy2 = int(ana_h * 0.06), int(ana_h * 0.16)
    top_rx_area = max((rx2 - rx1) * (oy2 - oy1), 1)
    for y in range(oy1, oy2):
        for x in range(rx1, rx2):
            r, g, b = px[x, y]  # type: ignore[index]
            if _pixel_is_waste(r, g, b, bg_wall):
                overflow_top_pixels += 1
    top_overflow_ratio = overflow_top_pixels / top_rx_area

    altura_ocupada_pct = ((ry2 - highest_waste_row) / total_rows) * 100.0 if waste_rows > 0 else 0.0
    densidad_pct = (waste_pixels_total / roi_pixels_total) * 100.0
    nivel_visual = 0.70 * densidad_pct + 0.30 * altura_ocupada_pct
    if top_overflow_ratio > 0.15:
        nivel_visual = max(nivel_visual, 88.0 + min(top_overflow_ratio * 20.0, 9.0))
    nivel_llenado_visual = round(min(max(nivel_visual, 5.0), 98.0), 1)

    # 2. ROI Suelo Perimetral: detectar bolsas/acúmulos en el suelo (y=[78%..95%], x=[6%..94%])
    fy1, fy2 = int(ana_h * 0.78), int(ana_h * 0.95)
    num_sectors = 10
    sector_w = (int(ana_w * 0.94) - int(ana_w * 0.06)) // num_sectors
    start_fx = int(ana_w * 0.06)
    detected_ground_boxes: list[tuple[int, int, int, int]] = []

    for s in range(num_sectors):
        sx1 = start_fx + s * sector_w
        sx2 = sx1 + sector_w
        s_waste = 0
        s_total = max((sx2 - sx1) * (fy2 - fy1), 1)
        for y in range(fy1, fy2):
            for x in range(sx1, sx2):
                r, g, b = px[x, y]  # type: ignore[index]
                if _pixel_is_waste(r, g, b, bg_floor):
                    s_waste += 1
        if (s_waste / s_total) >= 0.24:
            detected_ground_boxes.append((sx1, fy1, sx2, fy2))

    # Fusionar sectores adyacentes para contar bultos/bolsas reales en el suelo
    merged_ground_boxes: list[tuple[int, int, int, int]] = []
    for box in detected_ground_boxes:
        if merged_ground_boxes and box[0] <= merged_ground_boxes[-1][2] + 4:
            prev = merged_ground_boxes[-1]
            merged_ground_boxes[-1] = (prev[0], min(prev[1], box[1]), box[2], max(prev[3], box[3]))
        else:
            merged_ground_boxes.append(box)

    bolsas_en_suelo = len(merged_ground_boxes)
    desbordamiento = bool(nivel_llenado_visual >= umbral_critico or bolsas_en_suelo >= 2)
    estado_visual = "desbordamiento_detectado" if desbordamiento else "contenedor_estable"

    # 3. Generar imagen anotada con Bounding Boxes para el panel visual
    annotated = orig_img.copy()
    if annotated.width > 640:
        scale_h = int(annotated.height * (640 / annotated.width))
        annotated = annotated.resize((640, scale_h), Image.Resampling.BILINEAR)
    aw, ah = annotated.size
    draw = ImageDraw.Draw(annotated)

    sx_factor = aw / ana_w
    sy_factor = ah / ana_h

    roi_color = (220, 38, 38) if desbordamiento else ((217, 119, 6) if nivel_llenado_visual >= 55.0 else (22, 163, 74))
    box_container = (
        int(rx1 * sx_factor),
        int(ry1 * sy_factor),
        int(rx2 * sx_factor),
        int(ry2 * sy_factor),
    )
    draw.rectangle(box_container, outline=roi_color, width=3)

    # Línea de nivel estimado dentro del contenedor
    level_y = int((ry2 - (ry2 - ry1) * (nivel_llenado_visual / 100.0)) * sy_factor)
    draw.line((box_container[0], level_y, box_container[2], level_y), fill=roi_color, width=3)

    # Bounding boxes de bolsas detectadas en el suelo
    for gbox in merged_ground_boxes:
        draw.rectangle(
            (
                int(gbox[0] * sx_factor),
                int(gbox[1] * sy_factor),
                int(gbox[2] * sx_factor),
                int(gbox[3] * sy_factor),
            ),
            outline=(239, 68, 68),
            width=3,
        )

    # Etiqueta superior de telemetría visual
    draw.rectangle((0, 0, aw, 28), fill=(17, 24, 39))
    font = ImageFont.load_default()
    banner = (
        f"VISION SMA BAZURTO | Llenado: {nivel_llenado_visual:.1f}% | "
        f"Bolsas suelo: {bolsas_en_suelo} | Desborde: {'SI' if desbordamiento else 'NO'}"
    )
    draw.text((10, 8), banner, fill=(255, 255, 255), font=font)

    out_buf = io.BytesIO()
    annotated.save(out_buf, format="PNG")
    annotated_b64 = "data:image/png;base64," + base64.b64encode(out_buf.getvalue()).decode("ascii")

    return {
        "nivel_llenado_visual": nivel_llenado_visual,
        "desbordamiento": desbordamiento,
        "estado_visual": estado_visual,
        "bolsas_en_suelo": bolsas_en_suelo,
        "confianza": round(min(0.86 + (0.08 if desbordamiento else 0.04), 0.96), 2),
        "fuente_imagen": fuente,
        "annotated_image_base64": annotated_b64,
    }
