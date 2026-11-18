"""Bucle autonomo de la Sala de Control: los 5 agentes (LangGraph real) trabajan solos.

El servidor recorre las zonas en rondas. Solo el ENTORNO (sensores de MercadoBazurto) y la
respuesta de la comunidad son simulados; agentes, grafo, mensajes FIPA-ACL, riesgo y alertas
son los reales. La pagina unicamente observa los eventos que se publican en el EventBus.
"""

from __future__ import annotations

import base64
import logging
import random
import threading
from typing import Any, Optional
from uuid import uuid4

from app.eventos import AGENTES, EventBus
from app.fipa_acl import ACLMessage
from app.models_masml import SMAMonitoreoBazurto, registrar_observador_acl
from app.motor_langgraph import VERSION_LANGGRAPH, BazurtoStateGraphRunner

log = logging.getLogger("sma.autonomo")

_SUJETO = {
    "AgenteSensorResiduos": "El sensor de residuos",
    "AgenteSensorAire": "El sensor de aire",
    "AgenteCoordinador": "El Coordinador",
    "AgenteAlertas": "El agente de alertas",
    "AgenteSupervisor": "El Supervisor",
}
_DESTINO = {
    "AgenteSensorResiduos": "al sensor de residuos",
    "AgenteSensorAire": "al sensor de aire",
    "AgenteCoordinador": "al Coordinador",
    "AgenteAlertas": "al agente de alertas",
    "AgenteSupervisor": "al Supervisor",
}


def _pct(riesgo: Optional[float]) -> Optional[float]:
    """El motor calcula riesgo en 0-1; la Sala de Control lo muestra en 0-100."""
    return None if riesgo is None else round(float(riesgo) * 100.0, 1)


def _limitar(valor: float, minimo: float, maximo: float) -> float:
    return max(minimo, min(maximo, valor))


class SimuladorEntorno:
    """Evoluciona de forma continua los sensores del entorno MercadoBazurto (simulado)."""

    def __init__(self, sma: SMAMonitoreoBazurto, rng: random.Random) -> None:
        self.sma = sma
        self.rng = rng

    def avanzar(self) -> list[str]:
        """Avanza todas las zonas un paso. Devuelve los nombres de zonas recolectadas por el camion."""
        recolectadas: list[str] = []
        for zona in self.sma.db.list_zonas():
            nivel = float(zona["nivel_llenado_contenedores"]) + self.rng.uniform(0.8, 3.2)
            if nivel >= 99.0:  # el camion recolector vacia los contenedores
                nivel = self.rng.uniform(18.0, 32.0)
                recolectadas.append(str(zona["nombre"]))
            gases = float(zona["concentracion_gases"]) + self.rng.uniform(-30.0, 45.0) + (nivel - 50.0) * 0.2
            self.sma.db.update_zona(
                str(zona["zona_id"]),
                nivel_llenado_contenedores=round(_limitar(nivel, 0.0, 100.0), 1),
                concentracion_gases=round(_limitar(gases, 380.0, 1400.0), 1),
                temperatura=round(_limitar(float(zona["temperatura"]) + self.rng.uniform(-0.4, 0.4), 26.0, 36.0), 1),
                humedad=round(_limitar(float(zona["humedad"]) + self.rng.uniform(-1.0, 1.0), 60.0, 85.0), 1),
            )
        return recolectadas


class LoopAutonomo:
    def __init__(
        self,
        sma: SMAMonitoreoBazurto,
        bus: EventBus,
        intervalo_s: float = 6.0,
        ritmo_s: float = 1.6,
        semilla: Optional[int] = None,
        prob_confirma: float = 0.7,
        gemini_api_key: Optional[str] = None,
    ) -> None:
        self.sma = sma
        self.bus = bus
        self.intervalo_s = intervalo_s
        self.prob_confirma = prob_confirma
        self.gemini_api_key = gemini_api_key
        self.rng = random.Random(semilla)
        self.entorno = SimuladorEntorno(sma, self.rng)
        self.ronda = 0
        self.imagenes: dict[str, bytes] = {}
        self.estado_agentes: dict[str, dict[str, str]] = {
            a: {"agente": a, "estado": "reposo", "detalle": ""} for a in AGENTES
        }
        self.runner = BazurtoStateGraphRunner(
            sma, on_agente=self._on_agente, on_vision=self._on_vision, ritmo_s=ritmo_s
        )
        self._stop = threading.Event()
        self._hilo: Optional[threading.Thread] = None
        self._zona_activa = ""
        self.info_sistema = {
            "motor": "LangGraph", "version_langgraph": VERSION_LANGGRAPH,
            "intervalo_s": intervalo_s, "mensaje": "Agentes autónomos en ejecución",
        }
        registrar_observador_acl(self._on_acl)

    # ---- callbacks del motor ------------------------------------------------
    def _on_agente(self, agente: str, estado: str, detalle: str) -> None:
        self.estado_agentes[agente] = {"agente": agente, "estado": estado, "detalle": detalle}
        self.bus.emitir("agente_estado", agente=agente, estado=estado, detalle=detalle)

    def _on_acl(self, msg: ACLMessage) -> None:
        if not self._zona_activa:  # mensajes de flujos manuales fuera del bucle no se transmiten
            return
        contenido = msg.content_as_sexpr()
        self.bus.emitir(
            "agente_estado", agente=msg.sender, estado="comunicando",
            detalle=f"{msg.performative.upper()} a {msg.receiver}",
        )
        self.bus.emitir(
            "mensaje_acl",
            msg_id=uuid4().hex[:10],
            performativa=msg.performative.upper(),
            emisor=msg.sender,
            receptor=msg.receiver,
            contenido=contenido[:180],
            conversation_id=msg.conversation_id,
            protocolo=msg.protocol,
            ronda=self.ronda,
        )
        self.bus.emitir("narracion", **self._narrar(msg))

    def _on_vision(self, zona_id: str, contenedor: Optional[dict[str, Any]], vision: dict[str, Any]) -> None:
        anotada = vision.get("annotated_image_base64") or ""
        if anotada.startswith("data:image/png;base64,"):
            self.imagenes[zona_id] = base64.b64decode(anotada.split(",", 1)[1])
        motor = "gemini" if "Gemini" in str(vision.get("motor_vision", "")) else "hsv"
        preset = (contenedor or {}).get("ultima_imagen")
        self.bus.emitir(
            "vision",
            zona_id=zona_id,
            contenedor_id=str((contenedor or {}).get("contenedor_id", f"cont_{zona_id}")),
            porcentaje_llenado=float(vision.get("nivel_llenado_visual", 0.0)),
            bolsas=int(vision.get("bolsas_en_suelo", 0)),
            cajas=[],
            motor=motor,
            imagen_url=f"/static/samples/{preset}" if preset else None,
            imagen_anotada_url=f"/api/sala/vision/{zona_id}.png?v={self.ronda}" if zona_id in self.imagenes else None,
            explicacion=str(vision.get("explicacion_ia", "")),
        )

    @staticmethod
    def _narrar(msg: ACLMessage) -> dict[str, str]:
        quien = _SUJETO.get(msg.sender, msg.sender)
        a = _DESTINO.get(msg.receiver, f"a {msg.receiver}")
        p = msg.performative.upper()
        if p == "INFORM" and msg.sender == "AgenteSensorResiduos":
            return {"texto": f"{quien} informa {a} el nivel de llenado de los contenedores.", "nivel": "info"}
        if p == "INFORM" and msg.sender == "AgenteSensorAire":
            return {"texto": f"{quien} informa {a} la concentración de gases que midió.", "nivel": "info"}
        textos = {
            "INFORM": (f"{quien} informa {a}.", "info"),
            "REQUEST": (f"{quien} le pide {a} que emita una alerta a la comunidad.", "info"),
            "AGREE": (f"{quien} acepta la solicitud y avisa {a}.", "info"),
            "CONFIRM": (f"{quien} confirma {a} que la alerta llegó a la comunidad.", "info"),
            "INFORM-DONE": (f"{quien} avisa {a}: la comunidad atendió la alerta.", "info"),
            "REFUSE": (f"{quien} rechaza la solicitud y se lo dice {a}.", "atencion"),
            "FAILURE": (f"{quien} avisa {a}: la comunidad no confirmó la alerta.", "critico"),
            "DISCONFIRM": (f"{quien} le dice {a} que la alerta no fue confirmada.", "atencion"),
            "QUERY-IF": (f"{quien} le pregunta {a} si la alerta fue confirmada.", "info"),
        }
        texto, nivel = textos.get(p, (f"{quien} envía un mensaje {p} {a}.", "info"))
        return {"texto": texto, "nivel": nivel}

    # ---- ronda --------------------------------------------------------------
    def ejecutar_ronda(self) -> dict[str, Any]:
        zonas = self.sma.db.list_zonas()
        self.ronda += 1
        zona = zonas[(self.ronda - 1) % len(zonas)]
        zid, nombre = str(zona["zona_id"]), str(zona["nombre"])
        self._zona_activa = zid
        try:
            for recolectada in self.entorno.avanzar():
                self.bus.emitir("narracion", texto=f"Un camión recolector vació los contenedores de {recolectada}.")
            self.bus.emitir("ronda_inicio", ronda=self.ronda, zona_id=zid, zona_nombre=nombre)
            self.bus.emitir("narracion", texto=f"Ronda {self.ronda}: los cinco agentes revisan {nombre}.")
            confirma = self.rng.random() < self.prob_confirma
            res = self.runner.run(zona_id=zid, comunidad_confirma=confirma, gemini_api_key=self.gemini_api_key)
            est = res["estado_final_checkpoint"]
            z = self.sma.db.get_zona(zid) or {}
            riesgo = est.get("riesgo")
            self.bus.emitir(
                "medicion",
                zona_id=zid,
                nivel_llenado=float(z.get("nivel_llenado_contenedores", 0.0)),
                concentracion_gases=float(z.get("concentracion_gases", 0.0)),
                temperatura=float(z.get("temperatura", 0.0)),
                humedad=float(z.get("humedad", 0.0)),
                riesgo=_pct(riesgo),
            )
            if est.get("alerta_id") is not None:
                self.bus.emitir(
                    "alerta", alerta_id=str(est["alerta_id"]), zona_id=zid,
                    estado=str(est.get("resultado_acl")),
                    mensaje=f"Alerta en {nombre}: {est.get('resultado_acl')}",
                )
            self.bus.emitir(
                "ronda_fin",
                ronda=self.ronda,
                zona_id=zid,
                riesgo=_pct(riesgo),
                ranking=[
                    {"zona_id": r["zona_id"], "riesgo": _pct(r.get("riesgo"))}
                    for r in (est.get("ranking") or []) if "zona_id" in r
                ][:5],
            )
            return res
        finally:
            self._zona_activa = ""

    def snapshot(self) -> dict[str, Any]:
        recientes = self.bus.recientes()[-40:]
        riesgos: dict[str, float] = {}
        for ev in self.bus.recientes():
            if ev.tipo == "medicion" and ev.datos.get("riesgo") is not None:
                riesgos[ev.datos["zona_id"]] = ev.datos["riesgo"]
        return {
            "ultimo_evento_id": recientes[-1].id if recientes else 0,
            "sistema": self.info_sistema,
            "zonas": [
                {
                    "zona_id": z["zona_id"],
                    "nombre": z["nombre"],
                    "nivel_llenado": z["nivel_llenado_contenedores"],
                    "concentracion_gases": z["concentracion_gases"],
                    "temperatura": z["temperatura"],
                    "humedad": z["humedad"],
                    "riesgo": riesgos.get(str(z["zona_id"])),
                }
                for z in self.sma.db.list_zonas()
            ],
            "agentes": list(self.estado_agentes.values()),
            "recientes": [e.model_dump() for e in recientes],
        }

    # ---- ciclo de vida ------------------------------------------------------
    def iniciar(self) -> None:
        if self._hilo and self._hilo.is_alive():
            return
        self._stop.clear()
        self.bus.emitir("sistema", **self.info_sistema)
        self._hilo = threading.Thread(target=self._bucle, name="sma-autonomo", daemon=True)
        self._hilo.start()

    def detener(self) -> None:
        self._stop.set()
        if self._hilo:
            self._hilo.join(timeout=5)

    def _bucle(self) -> None:
        while not self._stop.is_set():
            try:
                self.ejecutar_ronda()
            except Exception:
                log.exception("Ronda omitida por error")
                self.bus.emitir("narracion", texto="Una ronda se omitió por un error interno; el sistema continúa.", nivel="atencion")
            self._stop.wait(self.intervalo_s)
