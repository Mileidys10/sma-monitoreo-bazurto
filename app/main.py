"""Aplicación FastAPI para operar y visualizar SMAMonitoreoBazurto con persistencia SQLite."""

import asyncio
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.autonomo import LoopAutonomo
from app.eventos import EventBus
from app.models_masml import SMAMonitoreoBazurto
from app.motor_langgraph import info_motor
from app.vision_analyzer import analizar_imagen_contenedor, ensure_sample_images

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
SAMPLE_CATALOG = ensure_sample_images(STATIC_DIR)

bus = EventBus()
sma = SMAMonitoreoBazurto(db_path=os.environ.get("SMA_DB_PATH") or str(BASE_DIR.parent / "bazurto_sma.db"))
loop_autonomo = LoopAutonomo(
    sma,
    bus,
    intervalo_s=float(os.environ.get("SMA_INTERVALO_S", "6")),
    gemini_api_key=os.environ.get("GEMINI_API_KEY") or None,
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if os.environ.get("SMA_AUTONOMO", "1") != "0":
        loop_autonomo.iniciar()
    try:
        yield
    finally:
        loop_autonomo.detener()


app = FastAPI(
    lifespan=lifespan,
    title="SMAMonitoreoBazurto — MAS-ML & FIPA-ACL",
    description="Sistema Multiagente de Monitoreo Ambiental del Mercado de Bazurto con persistencia SQLite.",
    version="1.0.0",
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ZonaUpdateRequest(BaseModel):
    nivel_llenado_contenedores: Optional[float] = Field(None, ge=0.0, le=100.0)
    concentracion_gases: Optional[float] = Field(None, ge=0.0, le=5000.0)
    temperatura: Optional[float] = Field(None, ge=-10.0, le=70.0)
    humedad: Optional[float] = Field(None, ge=0.0, le=100.0)
    sensor_aire_activo: Optional[bool] = None
    comunidad_confirma: Optional[bool] = None


class ZonaCreateRequest(BaseModel):
    zona_id: Optional[str] = None
    nombre: str
    nivel_llenado_contenedores: float = Field(25.0, ge=0.0, le=100.0)
    concentracion_gases: float = Field(450.0, ge=0.0, le=5000.0)
    temperatura: float = Field(30.0, ge=-10.0, le=70.0)
    humedad: float = Field(72.0, ge=0.0, le=100.0)


class ContenedorCreateRequest(BaseModel):
    contenedor_id: Optional[str] = None
    zona_id: str
    codigo: str
    tipo: str = "Contenedor Municipal 1100L"
    nivel_llenado: float = Field(15.0, ge=0.0, le=100.0)


class CasoUso1Request(BaseModel):
    zona_id: str = "zona_3"
    contenedor_id: Optional[str] = None
    forzar_duplicada: bool = False
    comunidad_confirma: Optional[bool] = None
    image_base64: Optional[str] = None
    preset_imagen: Optional[str] = None
    esperar_confirmacion_interactiva: bool = False
    gemini_api_key: Optional[str] = None


class CasoUso2Request(BaseModel):
    zona_id: str = "zona_3"
    simular_sin_confirmacion: Optional[bool] = None
    simular_sensor_caido: Optional[bool] = None


class VisionAnalyzeRequest(BaseModel):
    zona_id: str = "zona_3"
    contenedor_id: Optional[str] = None
    image_base64: Optional[str] = None
    preset_imagen: Optional[str] = None
    aplicar_a_entorno: bool = True
    gemini_api_key: Optional[str] = None


class AsignarImagenRequest(BaseModel):
    preset_imagen: Optional[str] = None
    image_base64: Optional[str] = None


class InspeccionCamarasRequest(BaseModel):
    gemini_api_key: Optional[str] = None
    comunidad_confirma: Optional[bool] = None
    esperar_confirmacion_interactiva: bool = True


class CasoUsoRolRequest(BaseModel):
    zona_id: str = "zona_3"
    gemini_api_key: Optional[str] = None
    comunidad_confirma: Optional[bool] = None
    esperar_confirmacion_interactiva: bool = True
    simular_sin_confirmacion: Optional[bool] = None
    simular_sensor_caido: Optional[bool] = None


class AlertaResponderRequest(BaseModel):
    confirmar: bool



@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "organizacion": sma.objetivo, "ontologia": "AmbientalBazurto"}


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    sala = STATIC_DIR / "sala" / "sala.html"
    return (sala if sala.exists() else STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/documentacion", response_class=HTMLResponse)
def documentacion() -> str:
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/diagramas", response_class=HTMLResponse)
def diagramas() -> str:
    pagina = STATIC_DIR / "diagramas" / "diagramas.html"
    if not pagina.exists():
        raise HTTPException(status_code=404, detail="Pagina de diagramas aun no disponible")
    return pagina.read_text(encoding="utf-8")


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)


@app.get("/api/motor")
def get_motor() -> dict[str, Any]:
    return info_motor()


@app.get("/api/sala/snapshot")
def sala_snapshot() -> dict[str, Any]:
    return loop_autonomo.snapshot()


@app.get("/api/sala/vision/{zona_id}.png")
def sala_vision(zona_id: str) -> Response:
    png = loop_autonomo.imagenes.get(zona_id)
    if png is None:
        raise HTTPException(status_code=404, detail="Aun no hay imagen analizada para esa zona")
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "no-cache"})


@app.get("/api/stream")
async def stream_eventos(request: Request, desde: int = 0) -> StreamingResponse:
    ultimo = request.headers.get("last-event-id")
    if ultimo and ultimo.isdigit():
        desde = max(desde, int(ultimo))

    async def generador() -> AsyncIterator[str]:
        gen = bus.stream(desde_id=desde)
        pendiente: Optional["asyncio.Future[Any]"] = None
        try:
            yield "retry: 3000\n\n"
            while True:
                if pendiente is None:
                    pendiente = asyncio.ensure_future(gen.__anext__())
                hecho, _ = await asyncio.wait({pendiente}, timeout=15)
                if not hecho:
                    yield ": keepalive\n\n"
                    continue
                evento = pendiente.result()
                pendiente = None
                yield evento.a_sse()
        finally:
            if pendiente is not None:
                pendiente.cancel()
                await asyncio.gather(pendiente, return_exceptions=True)  # esperar a que termine antes de cerrar
            try:
                await gen.aclose()
            except RuntimeError:  # el generador ya se cerro al cancelarse la espera
                pass

    return StreamingResponse(
        generador(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
        "contenedores": [
            {
                **c,
                "tiene_imagen_custom": bool(c.get("imagen_custom_base64")),
                "imagen_custom_base64": None,
            }
            for c in sma.db.list_contenedores()
        ],
        "historial_vision": sma.db.list_historial_vision(limit=25),
        "muestras_vision": SAMPLE_CATALOG,
        "estado_interno_residuos": sma.db.list_estados_residuos(),
        "historial_mediciones_aire": sma.db.list_historial_aire(limit=15),
        "eventos_riesgo": sma.db.list_eventos(limit=15),
        "alertas": sma.db.list_alertas(limit=15),
        "incidencias": sma.db.list_incidencias(limit=15),
        "mensajes_acl": sma.db.list_acl_messages(limit=30),
    }


def _slugify_id(raw: str, prefix: str) -> str:
    slug = re.sub(r"[^a-z0-9_]+", "_", raw.strip().lower()).strip("_")
    return slug or f"{prefix}_1"


def _resolve_zona_y_contenedor(zona_id: str, contenedor_id: Optional[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    zona = sma.db.get_zona(zona_id)
    if not zona:
        raise ValueError(f"Zona desconocida: {zona_id}")
    if contenedor_id:
        cont = sma.db.get_contenedor(contenedor_id)
        if cont and cont["zona_id"] == zona_id:
            return zona, cont
    conts = sma.db.list_contenedores(zona_id)
    if conts:
        return zona, conts[0]
    created = sma.db.create_contenedor(
        contenedor_id=f"cont_{zona_id}_01",
        zona_id=zona_id,
        codigo=f"CONT-{zona_id.upper()}-01",
        tipo="Contenedor Municipal 1100L",
        nivel_llenado=float(zona["nivel_llenado_contenedores"]),
    )
    return zona, created


@app.post("/api/zonas")
def create_zona(req: ZonaCreateRequest) -> dict[str, Any]:
    try:
        raw_id = req.zona_id.strip() if req.zona_id else _slugify_id(req.nombre, "zona")
        if not raw_id.startswith("zona_") and not req.zona_id:
            raw_id = f"zona_{raw_id}"
        zona = sma.db.create_zona(
            zona_id=raw_id,
            nombre=req.nombre,
            nivel_llenado_contenedores=req.nivel_llenado_contenedores,
            concentracion_gases=req.concentracion_gases,
            temperatura=req.temperatura,
            humedad=req.humedad,
        )
        return {**zona, "contenedores": sma.db.list_contenedores(zona["zona_id"])}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/contenedores")
def create_contenedor(req: ContenedorCreateRequest) -> dict[str, Any]:
    try:
        cid = req.contenedor_id.strip() if req.contenedor_id else _slugify_id(f"{req.zona_id}_{req.codigo}", "cont")
        return sma.db.create_contenedor(
            contenedor_id=cid,
            zona_id=req.zona_id,
            codigo=req.codigo,
            tipo=req.tipo,
            nivel_llenado=req.nivel_llenado,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/vision/historial")
def get_vision_historial(zona_id: Optional[str] = None, limit: int = 25) -> list[dict[str, Any]]:
    return sma.db.list_historial_vision(zona_id=zona_id, limit=limit)


@app.post("/api/vision/analizar")
def analyze_vision(req: VisionAnalyzeRequest) -> dict[str, Any]:
    try:
        zona, cont = _resolve_zona_y_contenedor(req.zona_id, req.contenedor_id)
        resultado = analizar_imagen_contenedor(
            image_input=req.image_base64,
            preset_name=req.preset_imagen,
            static_dir=STATIC_DIR,
            umbral_critico=sma.parametros.nivel_residuos_critico,
            gemini_api_key=req.gemini_api_key,
        )
        zona_actualizada = None
        contenedor_actualizado = cont
        detectado = bool(resultado.get("contenedor_detectado", True))
        if req.aplicar_a_entorno and detectado:
            contenedor_actualizado = sma.db.update_contenedor_vision(
                contenedor_id=cont["contenedor_id"],
                nivel_llenado=float(resultado["nivel_llenado_visual"]),
                estado_visual=str(resultado["estado_visual"]),
                bolsas_suelo=int(resultado["bolsas_en_suelo"]),
                ultima_imagen=str(resultado["fuente_imagen"] if req.image_base64 else (req.preset_imagen or resultado["fuente_imagen"])),
                imagen_custom_base64=req.image_base64,
                actualizar_custom=True,
            )
            zona_actualizada = sma.db.update_zona(
                zona_id=req.zona_id,
                nivel_llenado_contenedores=float(resultado["nivel_llenado_visual"]),
            )
        historial_entry = sma.db.insert_historial_vision(
            zona_id=zona["zona_id"],
            zona_nombre=zona["nombre"],
            contenedor_id=cont["contenedor_id"],
            contenedor_codigo=cont["codigo"],
            fuente_imagen=str(resultado["fuente_imagen"]),
            contenedor_detectado=detectado,
            nivel_llenado_visual=float(resultado["nivel_llenado_visual"]),
            bolsas_en_suelo=int(resultado["bolsas_en_suelo"]),
            desbordamiento=bool(resultado["desbordamiento"]),
            estado_visual=str(resultado["estado_visual"]),
            confianza=float(resultado["confianza"]),
            annotated_image_base64=str(resultado["annotated_image_base64"]),
            motor_vision=str(resultado.get("motor_vision", "Motor Matemático HSV Local (100% Offline)")),
            explicacion_ia=str(resultado.get("explicacion_ia", "")),
        )
        return {
            **resultado,
            "zona_id": zona["zona_id"],
            "zona_nombre": zona["nombre"],
            "contenedor_id": cont["contenedor_id"],
            "contenedor_codigo": cont["codigo"],
            "contenedor_actualizado": contenedor_actualizado,
            "zona_actualizada": zona_actualizada,
            "historial_entry": historial_entry,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/contenedores/{contenedor_id}/asignar-imagen")
def assign_container_image(contenedor_id: str, req: AsignarImagenRequest) -> dict[str, Any]:
    try:
        cont = sma.db.asignar_imagen_contenedor(
            contenedor_id=contenedor_id,
            preset_imagen=req.preset_imagen,
            imagen_custom_base64=req.image_base64,
        )
        return {
            **cont,
            "tiene_imagen_custom": bool(cont.get("imagen_custom_base64")),
            "imagen_custom_base64": None,
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/coordinador/inspeccionar-camaras")
def run_coordinador_inspeccion(req: InspeccionCamarasRequest) -> dict[str, Any]:
    try:
        return sma.ejecutar_inspeccion_coordinada_camaras(
            gemini_api_key=req.gemini_api_key,
            comunidad_confirma=req.comunidad_confirma,
            esperar_confirmacion_interactiva=req.esperar_confirmacion_interactiva,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/casos-uso-rol/{cu_id}")
def run_caso_uso_rol(cu_id: str, req: CasoUsoRolRequest) -> dict[str, Any]:
    try:
        return sma.ejecutar_caso_uso_rol(
            cu_id=cu_id,
            zona_id=req.zona_id,
            gemini_api_key=req.gemini_api_key,
            comunidad_confirma=req.comunidad_confirma,
            esperar_confirmacion_interactiva=req.esperar_confirmacion_interactiva,
            simular_sin_confirmacion=req.simular_sin_confirmacion,
            simular_sensor_caido=req.simular_sensor_caido,
        )
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
            contenedor_id=req.contenedor_id,
            gemini_api_key=req.gemini_api_key,
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
