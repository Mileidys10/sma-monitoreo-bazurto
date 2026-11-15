"""Aplicación FastAPI para operar y visualizar SMAMonitoreoBazurto con persistencia SQLite."""

from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.models_masml import SMAMonitoreoBazurto
from app.vision_analyzer import analizar_imagen_contenedor, ensure_sample_images

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
SAMPLE_CATALOG = ensure_sample_images(STATIC_DIR)

app = FastAPI(
    title="SMAMonitoreoBazurto — MAS-ML & FIPA-ACL",
    description="Sistema Multiagente de Monitoreo Ambiental del Mercado de Bazurto con persistencia SQLite.",
    version="1.0.0",
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

sma = SMAMonitoreoBazurto(db_path=str(BASE_DIR.parent / "bazurto_sma.db"))


class ZonaUpdateRequest(BaseModel):
    nivel_llenado_contenedores: Optional[float] = Field(None, ge=0.0, le=100.0)
    concentracion_gases: Optional[float] = Field(None, ge=0.0, le=5000.0)
    temperatura: Optional[float] = Field(None, ge=-10.0, le=70.0)
    humedad: Optional[float] = Field(None, ge=0.0, le=100.0)
    sensor_aire_activo: Optional[bool] = None
    comunidad_confirma: Optional[bool] = None


class CasoUso1Request(BaseModel):
    zona_id: str = "zona_3"
    forzar_duplicada: bool = False
    comunidad_confirma: Optional[bool] = None
    image_base64: Optional[str] = None
    preset_imagen: Optional[str] = None
    esperar_confirmacion_interactiva: bool = False


class CasoUso2Request(BaseModel):
    zona_id: str = "zona_3"
    simular_sin_confirmacion: Optional[bool] = None
    simular_sensor_caido: Optional[bool] = None


class VisionAnalyzeRequest(BaseModel):
    zona_id: str = "zona_3"
    image_base64: Optional[str] = None
    preset_imagen: Optional[str] = None
    aplicar_a_entorno: bool = True


class AlertaResponderRequest(BaseModel):
    confirmar: bool


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "organizacion": sma.objetivo, "ontologia": "AmbientalBazurto"}


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/privacy", response_class=HTMLResponse)
def privacy() -> str:
    return (
        "<html><body style='font-family:sans-serif;max-width:720px;margin:40px auto;line-height:1.6'>"
        "<h1>Política de Privacidad — SMAMonitoreoBazurto</h1>"
        "<p>Este sistema procesa únicamente variables ambientales simuladas o de sensores físicos "
        "(nivel de llenado de contenedores, gases, temperatura y humedad) en el Mercado de Bazurto.</p>"
        "<p>No recopila datos personales de ciudadanos ni comerciantes. Los registros técnicos en "
        "SQLite se limitan a telemetría ambiental, alertas operativas y trazas FIPA-ACL.</p>"
        "<a href='/'>Volver al panel</a></body></html>"
    )


@app.get("/terms", response_class=HTMLResponse)
def terms() -> str:
    return (
        "<html><body style='font-family:sans-serif;max-width:720px;margin:40px auto;line-height:1.6'>"
        "<h1>Términos de Uso — SMAMonitoreoBazurto</h1>"
        "<p>Plataforma académica y operativa de monitoreo ambiental multiagente basada en MAS-ML y FIPA-ACL.</p>"
        "<a href='/'>Volver al panel</a></body></html>"
    )


@app.get("/api/estado")
def get_estado() -> dict[str, Any]:
    return {
        "organizacion": {
            "nombre": "SMAMonitoreoBazurto",
            "objetivo": sma.objetivo,
            "politica": sma.politica,
            "parametros": {
                "nivel_residuos_critico": sma.parametros.nivel_residuos_critico,
                "tiempo_persistencia_min": sma.parametros.tiempo_persistencia_min,
                "gases_co2_critico": sma.parametros.gases_co2_critico,
                "riesgo_alerta_umbral": sma.parametros.riesgo_alerta_umbral,
            },
        },
        "entorno_zonas": sma.db.list_zonas(),
        "muestras_vision": SAMPLE_CATALOG,
        "estado_interno_residuos": sma.db.list_estados_residuos(),
        "historial_mediciones_aire": sma.db.list_historial_aire(limit=15),
        "eventos_riesgo": sma.db.list_eventos(limit=15),
        "alertas": sma.db.list_alertas(limit=15),
        "incidencias": sma.db.list_incidencias(limit=15),
        "mensajes_acl": sma.db.list_acl_messages(limit=30),
    }


@app.post("/api/vision/analizar")
def analyze_vision(req: VisionAnalyzeRequest) -> dict[str, Any]:
    try:
        resultado = analizar_imagen_contenedor(
            image_input=req.image_base64,
            preset_name=req.preset_imagen,
            static_dir=STATIC_DIR,
            umbral_critico=sma.parametros.nivel_residuos_critico,
        )
        zona_actualizada = None
        if req.aplicar_a_entorno:
            zona_actualizada = sma.db.update_zona(
                zona_id=req.zona_id,
                nivel_llenado_contenedores=float(resultado["nivel_llenado_visual"]),
            )
        return {**resultado, "zona_id": req.zona_id, "zona_actualizada": zona_actualizada}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/zonas/{zona_id}")
def update_zona(zona_id: str, req: ZonaUpdateRequest) -> dict[str, Any]:
    try:
        return sma.db.update_zona(
            zona_id=zona_id,
            nivel_llenado_contenedores=req.nivel_llenado_contenedores,
            concentracion_gases=req.concentracion_gases,
            temperatura=req.temperatura,
            humedad=req.humedad,
            sensor_aire_activo=req.sensor_aire_activo,
            comunidad_confirma=req.comunidad_confirma,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/caso-uso-1")
def run_cu1(req: CasoUso1Request) -> dict[str, Any]:
    try:
        return sma.ejecutar_caso_uso_1(
            zona_id=req.zona_id,
            forzar_duplicada=req.forzar_duplicada,
            comunidad_confirma=req.comunidad_confirma,
            image_base64=req.image_base64,
            preset_imagen=req.preset_imagen,
            esperar_confirmacion_interactiva=req.esperar_confirmacion_interactiva,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/alertas/{alerta_id}/responder")
def responder_alerta(alerta_id: int, req: AlertaResponderRequest) -> dict[str, Any]:
    try:
        return sma.responder_alerta_comunidad(alerta_id=alerta_id, confirmar=req.confirmar)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/caso-uso-2")
def run_cu2(req: CasoUso2Request) -> dict[str, Any]:
    try:
        return sma.ejecutar_caso_uso_2(
            zona_id=req.zona_id,
            simular_sin_confirmacion=req.simular_sin_confirmacion,
            simular_sensor_caido=req.simular_sensor_caido,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/reset")
def reset_system() -> dict[str, str]:
    sma.db.reset_all()
    return {"status": "reset_ok"}
