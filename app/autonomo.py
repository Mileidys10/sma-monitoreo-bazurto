"""Bucle autonomo de la Sala de Control: los 5 agentes (LangGraph real) trabajan solos.

El servidor recorre las zonas en rondas. Solo el ENTORNO (sensores de MercadoBazurto) y la
respuesta de la comunidad son simulados; agentes, grafo, mensajes FIPA-ACL, riesgo y alertas
son los reales. La pagina unicamente observa los eventos que se publican en el EventBus.
"""

from __future__ import annotations

import base64
import logging
import os
import random
from pathlib import Path
import threading
from typing import Any, Optional
from uuid import uuid4

from app.banco_fotos import BancoFotos
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
    """Evoluciona de forma continua los sensores del entorno MercadoBazurto (simulado).

    El llenado solo baja cuando un camion recolector vacia la zona; el camion se programa al
    confirmarse una alerta (INFORM-DONE) y llega unas rondas despues, tiempo en el que una nueva
    solicitud de alerta para la misma zona debe ser rechazada por duplicada (REFUSE).
    """

    def __init__(
        self,
        sma: SMAMonitoreoBazurto,
        rng: random.Random,
        paso_llenado: tuple[float, float] = (2.5, 6.0),
        prob_falla_sensor: float = 0.03,
    ) -> None:
        self.sma = sma
        self.rng = rng
        self.paso_llenado = paso_llenado  # puntos de llenado por ronda
        self.pendientes: dict[str, int] = {}  # zona_id -> rondas que faltan para que llegue el camion
        self.prob_falla_sensor = prob_falla_sensor  # por zona y ronda (CU-02, flujo A2)
        self.sensores_caidos: dict[str, int] = {}  # zona_id -> rondas que faltan para que el sensor vuelva

    def restablecer_sensores(self) -> None:
        for zona in self.sma.db.list_zonas():
            self.sma.db.update_zona(str(zona["zona_id"]), sensor_aire_activo=True)
        self.sensores_caidos.clear()

    def _actualizar_sensor_aire(self, zid: str) -> None:
        if zid in self.sensores_caidos:
            self.sensores_caidos[zid] -= 1
            if self.sensores_caidos[zid] <= 0:
                del self.sensores_caidos[zid]
                self.sma.db.update_zona(zid, sensor_aire_activo=True)
        elif self.rng.random() < self.prob_falla_sensor:
            # dura lo suficiente para que la zona sea visitada al menos una vez con el sensor caido
            self.sensores_caidos[zid] = self.rng.randint(3, 5)
            self.sma.db.update_zona(zid, sensor_aire_activo=False)

    def programar_recoleccion(self, zona_id: str, en_rondas: int = 4) -> None:
        self.pendientes.setdefault(zona_id, en_rondas)

    def avanzar(self) -> list[str]:
        """Avanza todas las zonas un paso. Devuelve los nombres de zonas recolectadas por el camion."""
        recolectadas: list[str] = []
        for zona in self.sma.db.list_zonas():
            zid = str(zona["zona_id"])
            self._actualizar_sensor_aire(zid)
            nivel = float(zona["nivel_llenado_contenedores"]) + self.rng.uniform(*self.paso_llenado)
            if zid in self.pendientes:
                self.pendientes[zid] -= 1
                if self.pendientes[zid] <= 0:
                    del self.pendientes[zid]
                    nivel = self.rng.uniform(18.0, 32.0)
                    self.sma.db.resolver_alertas_zona(zid)  # el camion cierra la alerta activa
                    recolectadas.append(str(zona["nombre"]))
            gases = float(zona["concentracion_gases"]) + self.rng.uniform(-30.0, 45.0) + (nivel - 50.0) * 0.2
            self.sma.db.update_zona(
                zid,
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
        carpeta_fotos = Path(os.environ.get("SMA_FOTOS_DIR") or Path(__file__).resolve().parent / "static" / "fotos_locales")
        self.banco = BancoFotos(carpeta_fotos, sma.parametros.nivel_residuos_critico, self.rng)
        self.runner = BazurtoStateGraphRunner(
            sma,
            on_agente=self._on_agente,
            on_vision=self._on_vision,
            ritmo_s=ritmo_s,
            imagen_segun_nivel=True,
            proveedor_imagen=self.banco.elegir if len(self.banco) else None,
        )
        self._stop = threading.Event()
        self._hilo: Optional[threading.Thread] = None
        self._zona_activa = ""
        self.info_sistema = {
            "motor": "LangGraph", "version_langgraph": VERSION_LANGGRAPH,
            "intervalo_s": intervalo_s,
            "mensaje": "Agentes autónomos en ejecución. Cámara: "
            + (f"banco de fotos locales ({self.banco.resumen()})" if len(self.banco) else "3 imágenes de muestra"),
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
            caso_uso=str(msg.caso_uso or ""),
        )
        self.bus.emitir("narracion", **self._narrar(msg))

    def _on_vision(self, zona_id: str, contenedor: Optional[dict[str, Any]], vision: dict[str, Any]) -> None:
        anotada = vision.get("annotated_image_base64") or ""
        if anotada.startswith("data:image/png;base64,"):
            self.imagenes[zona_id] = base64.b64decode(anotada.split(",", 1)[1])
        motor = "gemini" if "Gemini" in str(vision.get("motor_vision", "")) else "hsv"
        fuente = str(vision.get("fuente_imagen", ""))
        preset = next(
            (n for n in ("contenedor_critico.png", "contenedor_medio.png", "contenedor_limpio.png") if n in fuente), None
        )
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
        contenido = msg.content if isinstance(msg.content, dict) else {}
        if p == "INFORM" and msg.sender == "AgenteSensorResiduos":
            return {"texto": f"{quien} avisa {a}: los contenedores llevan un buen rato por encima del umbral.", "nivel": "atencion"}
        if p == "INFORM" and msg.sender == "AgenteSensorAire":
            return {"texto": f"{quien} informa {a} la concentración de gases que midió.", "nivel": "info"}
        if p == "INFORM" and msg.sender == "AgenteSupervisor":
            return {"texto": f"{quien} notifica {a} una falla en un agente.", "nivel": "critico"}
        if p == "REQUEST" and msg.sender == "AgenteSupervisor":
            return {"texto": f"{quien} pide {a} una acción correctiva.", "nivel": "atencion"}
        if p == "REQUEST" and contenido.get("reintento"):
            return {"texto": f"{quien} pide {a} reintentar la alerta.", "nivel": "atencion"}
        if p == "AGREE" and msg.receiver == "AgenteSupervisor":
            return {"texto": f"{quien} acepta la acción correctiva que pidió el Supervisor.", "nivel": "info"}
        if p == "QUERY-IF" and msg.receiver == "AgenteSensorAire":
            return {"texto": f"{quien} pregunta {a} si sigue funcionando (plazo: 5 s).", "nivel": "info"}
        if p == "QUERY-IF" and msg.receiver == "AgenteCoordinador":
            return {"texto": f"{quien} pregunta {a} si atendió el evento de riesgo.", "nivel": "info"}
        if p == "CONFIRM" and msg.sender == "AgenteSensorAire":
            return {"texto": f"{quien} responde {a}: sigue activo.", "nivel": "info"}
        if p == "CONFIRM" and msg.sender == "AgenteCoordinador":
            return {"texto": f"{quien} confirma {a} que atendió el evento.", "nivel": "info"}
        textos = {
            "INFORM": (f"{quien} informa {a}.", "info"),
            "REQUEST": (f"{quien} le pide {a} que emita una alerta a la comunidad.", "info"),
            "AGREE": (f"{quien} acepta la solicitud y avisa {a}.", "info"),
            "CONFIRM": (f"{quien} confirma {a} que la alerta llegó a la comunidad.", "info"),
            "INFORM-DONE": (f"{quien} avisa {a}: la comunidad atendió la alerta.", "info"),
            "REFUSE": (f"{quien} rechaza la solicitud {a}: ya hay una alerta activa en esa zona.", "atencion"),
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
            traza = res.get("traza") or []
            if any(t.get("tipo") == "TIMEOUT" for t in traza):
                self.bus.emitir(
                    "narracion",
                    texto=(
                        f"El sensor de aire de {nombre} no respondió antes del plazo: el Supervisor registra la "
                        "incidencia y el Coordinador recalcula el riesgo sin ese sensor."
                    ),
                    nivel="critico",
                )
            z = self.sma.db.get_zona(zid) or {}
            riesgo = est.get("riesgo")
            # Todas las zonas publican su lectura de la ronda: nivel y riesgo siempre del mismo instante.
            riesgo_por_zona = {str(r["zona_id"]): r.get("riesgo") for r in (est.get("ranking") or []) if "zona_id" in r}
            riesgo_por_zona[zid] = riesgo
            for zona_actual in self.sma.db.list_zonas():
                otra = str(zona_actual["zona_id"])
                self.bus.emitir(
                    "medicion",
                    zona_id=otra,
                    nivel_llenado=float(zona_actual["nivel_llenado_contenedores"]),
                    concentracion_gases=float(zona_actual["concentracion_gases"]),
                    temperatura=float(zona_actual["temperatura"]),
                    humedad=float(zona_actual["humedad"]),
                    riesgo=_pct(riesgo_por_zona.get(otra)),
                )
            if est.get("resultado_acl") is None and not any(t.get("tipo") == "TIMEOUT" for t in traza):
                nivel_z = float(z.get("nivel_llenado_contenedores", 0.0))
                limite = self.sma.parametros.nivel_residuos_critico
                motivo = (
                    f"está por debajo del umbral ({limite:.0f} %)" if nivel_z <= limite
                    else "supera el umbral pero aún no lleva el tiempo mínimo seguido"
                )
                self.bus.emitir(
                    "narracion",
                    texto=f"{nombre} {motivo} con {nivel_z:.0f} % de llenado: no hace falta alertar.",
                )
            if est.get("resultado_acl") == "INFORM-DONE":
                self.entorno.programar_recoleccion(zid)
                self.bus.emitir(
                    "narracion", texto=f"Alerta atendida: se envió un camión recolector a {nombre}; llegará en unas rondas."
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
        self.entorno.restablecer_sensores()
        limite = self.sma.parametros.nivel_residuos_critico
        for z in self.sma.db.list_zonas():  # una alerta vieja no debe bloquear nuevas con la zona ya bajo el umbral
            if float(z["nivel_llenado_contenedores"]) < limite:
                self.sma.db.resolver_alertas_zona(str(z["zona_id"]))
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
