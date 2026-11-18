"""Contrato de eventos en vivo de la Sala de Control (SSE) para SMAMonitoreoBazurto V2.

Un unico canal de eventos tipados: el motor LangGraph (hilo de fondo) emite, la pagina
solo observa. Cada payload se valida con Pydantic antes de publicarse, de modo que la
interfaz puede confiar en el esquema documentado en docs/CONTRATO_SALA_CONTROL.md.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import threading
import time
from collections import deque
from typing import Any, AsyncIterator, Literal, Optional

from pydantic import BaseModel, Field

AGENTES: tuple[str, ...] = (
    "AgenteSensorResiduos",
    "AgenteSensorAire",
    "AgenteCoordinador",
    "AgenteAlertas",
    "AgenteSupervisor",
)


class RondaInicio(BaseModel):
    ronda: int
    zona_id: str
    zona_nombre: str


class AgenteEstado(BaseModel):
    agente: str
    estado: Literal["reposo", "analizando", "comunicando", "esperando"]
    detalle: str = ""


class MensajeACL(BaseModel):
    msg_id: str
    performativa: str
    emisor: str
    receptor: str
    contenido: str
    conversation_id: str
    protocolo: str = "fipa-request"
    ronda: int = 0
    caso_uso: str = ""


class Medicion(BaseModel):
    zona_id: str
    nivel_llenado: float
    concentracion_gases: float
    temperatura: float
    humedad: float
    riesgo: Optional[float] = None


class CajaVision(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(ge=0, le=1)
    h: float = Field(ge=0, le=1)
    etiqueta: str


class Vision(BaseModel):
    zona_id: str
    contenedor_id: str
    porcentaje_llenado: float
    bolsas: int = 0
    cajas: list[CajaVision] = Field(default_factory=list)
    motor: Literal["gemini", "hsv"]
    imagen_url: Optional[str] = None
    imagen_anotada_url: Optional[str] = None
    explicacion: str = ""


class Alerta(BaseModel):
    alerta_id: Optional[str] = None
    zona_id: str
    estado: str
    mensaje: str = ""


class Narracion(BaseModel):
    texto: str
    nivel: Literal["info", "atencion", "critico"] = "info"


class RondaFin(BaseModel):
    ronda: int
    zona_id: str
    riesgo: Optional[float] = None
    ranking: list[dict[str, Any]] = Field(default_factory=list)


class Sistema(BaseModel):
    motor: str
    version_langgraph: str
    intervalo_s: float
    mensaje: str = ""


PAYLOADS: dict[str, type[BaseModel]] = {
    "ronda_inicio": RondaInicio,
    "agente_estado": AgenteEstado,
    "mensaje_acl": MensajeACL,
    "medicion": Medicion,
    "vision": Vision,
    "alerta": Alerta,
    "narracion": Narracion,
    "ronda_fin": RondaFin,
    "sistema": Sistema,
}


class Evento(BaseModel):
    id: int
    tipo: str
    ts: float
    datos: dict[str, Any]

    def a_sse(self) -> str:
        cuerpo = json.dumps(self.model_dump(), ensure_ascii=False)
        return f"id: {self.id}\nevent: {self.tipo}\ndata: {cuerpo}\n\n"


def _poner_sin_bloquear(cola: "asyncio.Queue[Evento]", evento: Evento) -> None:
    try:
        cola.put_nowait(evento)
    except asyncio.QueueFull:  # cliente lento: se descarta, el siguiente snapshot lo resincroniza
        pass


class EventBus:
    """Difusion de eventos segura entre hilos (motor) y asyncio (clientes SSE)."""

    def __init__(self, historial: int = 300) -> None:
        self._ids = itertools.count(1)
        self._historial: deque[Evento] = deque(maxlen=historial)
        self._subs: set[tuple[asyncio.AbstractEventLoop, "asyncio.Queue[Evento]"]] = set()
        self._lock = threading.Lock()

    def emitir(self, tipo: str, **datos: Any) -> Evento:
        modelo = PAYLOADS.get(tipo)
        if modelo is None:
            raise ValueError(f"Tipo de evento desconocido: {tipo}")
        validado = modelo(**datos).model_dump()
        with self._lock:
            evento = Evento(id=next(self._ids), tipo=tipo, ts=time.time(), datos=validado)
            self._historial.append(evento)
            subs = list(self._subs)
        for loop, cola in subs:
            loop.call_soon_threadsafe(_poner_sin_bloquear, cola, evento)
        return evento

    def recientes(self, desde_id: int = 0) -> list[Evento]:
        with self._lock:
            return [e for e in self._historial if e.id > desde_id]

    async def stream(self, desde_id: int = 0) -> AsyncIterator[Evento]:
        loop = asyncio.get_running_loop()
        cola: "asyncio.Queue[Evento]" = asyncio.Queue(maxsize=500)
        with self._lock:  # snapshot + alta atomicos: ningun evento se pierde ni se duplica
            atrasados = [e for e in self._historial if e.id > desde_id]
            self._subs.add((loop, cola))
        try:
            for evento in atrasados:
                yield evento
            while True:
                yield await cola.get()
        finally:
            with self._lock:
                self._subs.discard((loop, cola))
