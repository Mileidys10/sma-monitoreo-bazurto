"""Motor multiagente REAL de SMAMonitoreoBazurto V2: LangGraph (StateGraph de 5 nodos).

Cada agente MAS-ML es un nodo del grafo. No existe motor de respaldo: si LangGraph no
esta instalado el arranque falla con un mensaje claro, para no simular sin avisar.
El estado de dominio (zonas, mensajes FIPA-ACL, alertas) persiste en SQLite (bazurto_sma.db);
el checkpointer de LangGraph es MemorySaver.
"""

from __future__ import annotations

import time
from importlib.metadata import version as _version
from typing import TYPE_CHECKING, Any, Callable, Optional, TypedDict
from uuid import uuid4

from app.models_masml import ACLMessage

try:
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph import END, START, StateGraph
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        "LangGraph no esta instalado. Ejecute: pip install -r requirements.txt"
    ) from exc

if TYPE_CHECKING:
    from app.models_masml import SMAMonitoreoBazurto

VERSION_LANGGRAPH: str = _version("langgraph")

CallbackAgente = Callable[[str, str, str], None]  # (agente, estado, detalle)
CallbackVision = Callable[[str, Optional[dict[str, Any]], dict[str, Any]], None]  # (zona, contenedor, resultado)


class BazurtoAgentState(TypedDict, total=False):
    """Estado tipado compartido a través de los 5 nodos del StateGraph (resuelve el límite de n8n)."""

    zona_id: str
    conversation_id: str
    framework_id: str
    gemini_api_key: Optional[str]
    comunidad_confirma: Optional[bool]
    incluir_supervision: bool
    nivel_llenado: float
    vision_resumen: dict[str, Any]
    estado_interno_residuos: dict[str, Any]
    evento_id: Optional[int]
    medicion_aire: dict[str, float]
    aumento_gases: bool
    riesgo: float
    ranking_zonas: list[dict[str, Any]]
    reply_with: Optional[str]
    alerta_aceptada: bool
    alerta_id: Optional[int]
    resultado_acl: str
    incidencias_supervisor: list[int]
    nodos_visitados: list[dict[str, Any]]
    transiciones: list[str]
    traza: list[dict[str, Any]]


MERMAID_STATEGRAPH = """flowchart TD
    START([START]) --> nodo_sensor_residuos[nodo_sensor_residuos\\nAgenteSensorResiduos]
    nodo_sensor_residuos -->|ACL:INFORM| nodo_sensor_aire[nodo_sensor_aire\\nAgenteSensorAire]
    nodo_sensor_aire -->|ACL:INFORM| nodo_coordinador[nodo_coordinador\\nAgenteCoordinador]
    nodo_coordinador -->|sin evento de riesgo persistente| END([END])
    nodo_coordinador -->|ACL:REQUEST si hay evento| nodo_alertas[nodo_alertas\\nAgenteAlertas]
    nodo_alertas -->|decidir_ruta_supervision: FAILURE / REFUSE / Auditar| nodo_supervisor[nodo_supervisor\\nAgenteSupervisor]
    nodo_alertas -->|INFORM-DONE sin auditoría extra| END([END])
    nodo_supervisor -->|REQUEST / CONFIRM| END"""


class BazurtoStateGraphRunner:
    """Construye y compila el grafo multiagente StateGraph conectado a SMAMonitoreoBazurto."""

    def __init__(
        self,
        sma: "SMAMonitoreoBazurto",
        on_agente: Optional[CallbackAgente] = None,
        on_vision: Optional[CallbackVision] = None,
        ritmo_s: float = 0.0,
        imagen_segun_nivel: bool = False,
        proveedor_imagen: Optional[Callable[[float], Optional[str]]] = None,
    ) -> None:
        self.sma = sma
        # En modo autonomo la camara "ve" el nivel simulado: la foto se elige segun ese nivel y
        # nunca sobrescribe el entorno. En modo manual la foto asignada/subida sigue mandando.
        self.imagen_segun_nivel = imagen_segun_nivel
        self.proveedor_imagen = proveedor_imagen  # nivel -> foto (data URL) o None
        self.on_agente = on_agente
        self.on_vision = on_vision
        self.ritmo_s = ritmo_s  # pausa tras cada agente para que la Sala de Control muestre el avance
        self.uses_native_langgraph = True
        self.checkpointer = MemorySaver()
        self.graph = self._build_graph(StateGraph, START, END, self.checkpointer)

    def _observado(self, agente: str, fn: Callable[[Any], dict[str, Any]]) -> Callable[[Any], dict[str, Any]]:
        """Envuelve un nodo para informar cuando su agente empieza a analizar y cuando vuelve a reposo."""

        def envuelto(state: Any) -> dict[str, Any]:
            if self.on_agente:
                self.on_agente(agente, "analizando", "")
            try:
                return fn(state)
            finally:
                if self.ritmo_s > 0:
                    time.sleep(self.ritmo_s)
                if self.on_agente:
                    self.on_agente(agente, "reposo", "")

        envuelto.__name__ = fn.__name__
        return envuelto

    def _build_graph(self, graph_cls: Any, start_node: Any, end_node: Any, checkpointer: Any) -> Any:
        builder = graph_cls(BazurtoAgentState)

        def nodo_sensor_residuos(state: BazurtoAgentState) -> dict[str, Any]:
            zid = str(state["zona_id"])
            conv_id = str(state["conversation_id"])
            fw_tag = str(state.get("framework_id", "langgraph")).upper()
            trace = list(state.get("traza") or [])
            nodos = list(state.get("nodos_visitados") or [])
            transiciones = list(state.get("transiciones") or [])

            nivel = self.sma.sensor_residuos.medirNivelLlenadoContenedores(zid, trace)
            conts = self.sma.db.list_contenedores(zid)
            cont = conts[0] if conts else None
            img_custom = None if self.imagen_segun_nivel else (cont.get("imagen_custom_base64") if cont else None)
            preset = None if (img_custom or self.imagen_segun_nivel) else (
                cont.get("ultima_imagen")
                if cont and cont.get("ultima_imagen") in ("contenedor_limpio.png", "contenedor_medio.png", "contenedor_critico.png")
                else self.sma.sensor_residuos._preset_para_nivel(nivel)
            )
            foto_banco = self.proveedor_imagen(nivel) if (self.imagen_segun_nivel and self.proveedor_imagen) else None
            vision = self.sma.sensor_residuos.analizarImagenes(
                zona_id=zid,
                nivel=nivel,
                trace=trace,
                image_base64=foto_banco or img_custom,
                preset_imagen=preset,
                actualizar_entorno=False,
                gemini_api_key=state.get("gemini_api_key"),
                no_modificar_entorno=bool(foto_banco),
            )
            if self.on_vision:
                self.on_vision(zid, cont, vision)
            nivel_efectivo = float(vision["nivel_usado"])
            estado_interno = self.sma.sensor_residuos.evaluarPersistencia(
                zid,
                nivel_efectivo,
                trace,
                estado_visual=str(vision["estado_visual"]),
                bolsas_suelo=int(vision["bolsas_en_suelo"]),
            )
            evento_id: Optional[int] = None
            if estado_interno["persiste"]:  # bloque opt del CU-01: nivel > umbral AND persiste
                evento_id = self.sma.sensor_residuos.publicarEventoRiesgo(
                    zid, estado_interno, conv_id, f"FW-{fw_tag}", trace
                )

            nodos.append(
                {
                    "nodo": "nodo_sensor_residuos",
                    "agente": "AgenteSensorResiduos",
                    "rol": "MonitorCondicionesAmbientales",
                    "metodos": [
                        "medirNivelLlenadoContenedores()",
                        "analizarImagenes()",
                        "evaluarPersistencia()",
                        "publicarEventoRiesgo()" if evento_id is not None else "sin evento (bajo umbral o sin persistencia)",
                    ],
                    "salida": (
                        f"evento={'#' + str(evento_id) if evento_id is not None else 'ninguno'}, nivel={nivel_efectivo}%, "
                        f"tiempoSobreLimite={estado_interno['tiempo_sobre_limite']}min, "
                        f"vision={vision['estado_visual']}"
                    ),
                }
            )
            transiciones.append("START -> nodo_sensor_residuos")
            return {
                "nivel_llenado": nivel_efectivo,
                "vision_resumen": {
                    "fuente_imagen": vision["fuente_imagen"],
                    "estado_visual": vision["estado_visual"],
                    "nivel_llenado_visual": float(vision["nivel_llenado_visual"]),
                    "bolsas_en_suelo": int(vision["bolsas_en_suelo"]),
                    "motor_vision": str(vision.get("motor_vision", "HSV Local")),
                    "explicacion_ia": str(vision.get("explicacion_ia", "")),
                },
                "estado_interno_residuos": {
                    "nivel": float(estado_interno["nivel"]),
                    "tiempo_sobre_limite": int(estado_interno["tiempo_sobre_limite"]),
                    "ritmo_llenado": float(estado_interno["ritmo_llenado"]),
                    "ciclos_consecutivos": int(estado_interno["ciclos_consecutivos"]),
                },
                "evento_id": evento_id,
                "nodos_visitados": nodos,
                "transiciones": transiciones,
                "traza": trace,
            }

        def nodo_sensor_aire(state: BazurtoAgentState) -> dict[str, Any]:
            zid = str(state["zona_id"])
            conv_id = str(state["conversation_id"])
            fw_tag = str(state.get("framework_id", "langgraph")).upper()
            trace = list(state.get("traza") or [])
            nodos = list(state.get("nodos_visitados") or [])
            transiciones = list(state.get("transiciones") or [])

            medicion = self.sma.sensor_aire.medirGases(zid, trace)
            self.sma.sensor_aire.registrarMedicion(zid, medicion, trace)
            aumento = self.sma.sensor_aire.detectarAumentoProgresivo(zid, trace)
            self.sma.sensor_aire.publicarMedicion(zid, medicion, aumento, conv_id, f"FW-{fw_tag}", trace)

            nodos.append(
                {
                    "nodo": "nodo_sensor_aire",
                    "agente": "AgenteSensorAire",
                    "rol": "MonitorCondicionesAmbientales",
                    "metodos": [
                        "medirGases()",
                        "registrarMedicion()",
                        "detectarAumentoProgresivo()",
                        "publicarMedicion()",
                    ],
                    "salida": (
                        f"CO2={medicion['concentracionGases']}ppm, "
                        f"aumentoProgresivo={aumento}"
                    ),
                }
            )
            transiciones.append("nodo_sensor_residuos -> nodo_sensor_aire")
            return {
                "medicion_aire": medicion,
                "aumento_gases": bool(aumento),
                "nodos_visitados": nodos,
                "transiciones": transiciones,
                "traza": trace,
            }

        def nodo_coordinador(state: BazurtoAgentState) -> dict[str, Any]:
            zid = str(state["zona_id"])
            conv_id = str(state["conversation_id"])
            evento_id = state.get("evento_id")
            fw_tag = str(state.get("framework_id", "langgraph")).upper()
            trace = list(state.get("traza") or [])
            nodos = list(state.get("nodos_visitados") or [])
            transiciones = list(state.get("transiciones") or [])

            self.sma.coordinador.consultarEventos(zid, trace)
            riesgo = self.sma.coordinador.calcularRiesgo(zid, True, trace)
            ranking = self.sma.coordinador.priorizarZonas(zid, riesgo, trace)
            reply_with: Optional[str] = None
            if evento_id is not None:  # solo hay alerta que delegar si el sensor publico un evento
                self.sma.db.update_evento_riesgo(int(evento_id), riesgo, 1, atendido=True)
                reply_with = self.sma.coordinador.delegarAlerta(
                    int(evento_id), zid, riesgo, conv_id, f"FW-{fw_tag}", False, trace
                )

            nodos.append(
                {
                    "nodo": "nodo_coordinador",
                    "agente": "AgenteCoordinador",
                    "rol": "Coordinador",
                    "metodos": [
                        "consultarEventos()",
                        "calcularRiesgo()",
                        "priorizarZonas()",
                        "delegarAlerta()" if evento_id is not None else "sin alerta que delegar",
                    ],
                    "salida": f"riesgo={riesgo}, rankingTop={ranking[0]['zona_id'] if ranking else zid}",
                }
            )
            transiciones.append("nodo_sensor_aire -> nodo_coordinador")
            return {
                "riesgo": float(riesgo),
                "ranking_zonas": ranking,
                "reply_with": reply_with,
                "nodos_visitados": nodos,
                "transiciones": transiciones,
                "traza": trace,
            }

        def nodo_alertas(state: BazurtoAgentState) -> dict[str, Any]:
            zid = str(state["zona_id"])
            conv_id = str(state["conversation_id"])
            evento_id = int(state["evento_id"])  # garantizado: este nodo solo corre con evento
            riesgo = float(state["riesgo"])
            reply_with = str(state["reply_with"])
            fw_tag = str(state.get("framework_id", "langgraph")).upper()
            trace = list(state.get("traza") or [])
            nodos = list(state.get("nodos_visitados") or [])
            transiciones = list(state.get("transiciones") or [])

            nivel_alerta = "ALTO" if riesgo >= self.sma.parametros.riesgo_alerta_umbral else "MODERADO"
            acepta = self.sma.alertas.recibirSolicitudAlerta(
                zid, False, reply_with, conv_id, f"FW-{fw_tag}", trace
            )
            resultado_acl = "REFUSE"
            alerta_id: Optional[int] = None
            if acepta:
                self.sma.alertas.emitirAviso(zid, trace)
                confirma = self.sma.alertas.gestionarConfirmacion(zid, trace)
                if confirma:
                    alerta_id = self.sma.alertas.generarReporteConfirmacion(
                        evento_id, zid, nivel_alerta, reply_with, conv_id, f"FW-{fw_tag}", trace
                    )
                    resultado_acl = "INFORM-DONE"
                else:
                    alerta_id = self.sma.alertas.generarReporteSinConfirmacion(
                        evento_id, zid, nivel_alerta, reply_with, conv_id, f"FW-{fw_tag}", trace
                    )
                    resultado_acl = "FAILURE"

            nodos.append(
                {
                    "nodo": "nodo_alertas",
                    "agente": "AgenteAlertas",
                    "rol": "EmisorAlertas",
                    "metodos": [
                        "recibirSolicitudAlerta()",
                        "emitirAviso()",
                        "gestionarConfirmacion()",
                        "generarReporteConfirmacion()" if resultado_acl == "INFORM-DONE" else "generarReporteSinConfirmacion()",
                    ],
                    "salida": f"alerta_id={alerta_id}, ACL={resultado_acl}",
                }
            )
            transiciones.append("nodo_coordinador -> nodo_alertas")
            return {
                "alerta_aceptada": bool(acepta),
                "alerta_id": alerta_id,
                "resultado_acl": resultado_acl,
                "nodos_visitados": nodos,
                "transiciones": transiciones,
                "traza": trace,
            }

        def decidir_ruta_supervision(state: BazurtoAgentState) -> str:
            if state.get("resultado_acl") in ("FAILURE", "REFUSE") or state.get("incluir_supervision", True):
                return "supervisor"
            return "fin"

        def nodo_supervisor(state: BazurtoAgentState) -> dict[str, Any]:
            zid = str(state["zona_id"])
            conv_id = str(state["conversation_id"])
            evento_id = int(state["evento_id"])
            fw_tag = str(state.get("framework_id", "langgraph")).upper()
            caso_lbl = f"FW-{fw_tag}"
            trace = list(state.get("traza") or [])
            nodos = list(state.get("nodos_visitados") or [])
            transiciones = list(state.get("transiciones") or [])

            self.sma.supervisor.verificarAtencionEventos(zid, trace)
            self.sma.supervisor.supervisarAgentes(trace)

            q_alerta = ACLMessage(
                performative="QUERY-IF",
                sender="AgenteSupervisor",
                receiver="AgenteAlertas",
                content={"alerta_confirmada_por_comunidad": zid, "evento_id": evento_id},
                protocol="FIPA-Query",
                conversation_id=conv_id,
                reply_with=f"q-alerta-{evento_id}",
                metodo_origen="verificarAtencionEventos()",
                caso_uso=caso_lbl,
            )
            self.sma.supervisor.emitir_acl(q_alerta, trace)

            incidencias: list[int] = []
            if state.get("resultado_acl") in ("FAILURE", "REFUSE"):
                self.sma.alertas.emitir_acl(
                    ACLMessage(
                        performative="DISCONFIRM",
                        sender="AgenteAlertas",
                        receiver="AgenteSupervisor",
                        content={"reporteSinConfirmacion": zid, "evento_id": evento_id},
                        protocol="FIPA-Query",
                        conversation_id=conv_id,
                        in_reply_to=q_alerta.reply_with,
                        metodo_origen="generarReporteSinConfirmacion()",
                        caso_uso=caso_lbl,
                    ),
                    trace,
                )
                inc_id = self.sma.supervisor.registrarIncidencias(
                    "AgenteAlertas",
                    zid,
                    f"Orquestador {fw_tag}: Alerta #{state.get('alerta_id')} sin confirmación comunitaria",
                    "Escalamiento automático hacia AgenteCoordinador",
                    trace,
                )
                incidencias.append(inc_id)
                self.sma.supervisor.notificarFallos("AgenteAlertas", zid, conv_id, caso_lbl, trace)
                req_id = self.sma.supervisor.solicitarAccionesCorrectivas(
                    "escalar_alerta_reintento", zid, conv_id, caso_lbl, trace
                )
                self.sma.coordinador.emitir_acl(
                    ACLMessage(
                        performative="AGREE",
                        sender="AgenteCoordinador",
                        receiver="AgenteSupervisor",
                        content={"accion_correctiva": "escalar_alerta_reintento", "zona": zid},
                        protocol="FIPA-Request",
                        conversation_id=conv_id,
                        in_reply_to=req_id,
                        metodo_origen="delegarAlerta()",
                        caso_uso=caso_lbl,
                    ),
                    trace,
                )
            else:
                self.sma.alertas.emitir_acl(
                    ACLMessage(
                        performative="CONFIRM",
                        sender="AgenteAlertas",
                        receiver="AgenteSupervisor",
                        content={"reporteConfirmacion": zid, "evento_id": evento_id},
                        protocol="FIPA-Query",
                        conversation_id=conv_id,
                        in_reply_to=q_alerta.reply_with,
                        metodo_origen="gestionarConfirmacion()",
                        caso_uso=caso_lbl,
                    ),
                    trace,
                )

            nodos.append(
                {
                    "nodo": "nodo_supervisor",
                    "agente": "AgenteSupervisor",
                    "rol": "Supervisor",
                    "metodos": [
                        "verificarAtencionEventos()",
                        "supervisarAgentes()",
                        "registrarIncidencias()" if incidencias else "confirmarAuditoria()",
                        "notificarFallos()" if incidencias else "cierreAuditado()",
                        "solicitarAccionesCorrectivas()" if incidencias else "supervisarAgentes()",
                    ],
                    "salida": (
                        f"Incidencias escaladas={incidencias}"
                        if incidencias
                        else "Auditoría CONFIRM sin incidencias"
                    ),
                }
            )
            transiciones.append("nodo_alertas -> nodo_supervisor")
            return {
                "incidencias_supervisor": incidencias,
                "nodos_visitados": nodos,
                "transiciones": transiciones,
                "traza": trace,
            }

        builder.add_node("nodo_sensor_residuos", self._observado("AgenteSensorResiduos", nodo_sensor_residuos))
        builder.add_node("nodo_sensor_aire", self._observado("AgenteSensorAire", nodo_sensor_aire))
        builder.add_node("nodo_coordinador", self._observado("AgenteCoordinador", nodo_coordinador))
        builder.add_node("nodo_alertas", self._observado("AgenteAlertas", nodo_alertas))
        builder.add_node("nodo_supervisor", self._observado("AgenteSupervisor", nodo_supervisor))

        builder.add_edge(start_node, "nodo_sensor_residuos")
        builder.add_edge("nodo_sensor_residuos", "nodo_sensor_aire")
        builder.add_edge("nodo_sensor_aire", "nodo_coordinador")
        builder.add_conditional_edges(
            "nodo_coordinador",
            lambda st: "alertas" if st.get("evento_id") is not None else "fin",
            {"alertas": "nodo_alertas", "fin": end_node},
        )
        builder.add_conditional_edges(
            "nodo_alertas",
            decidir_ruta_supervision,
            {"supervisor": "nodo_supervisor", "fin": end_node},
        )
        builder.add_edge("nodo_supervisor", end_node)
        return builder.compile(checkpointer=checkpointer)

    def run(
        self,
        framework_id: str = "langgraph",
        zona_id: str = "zona_3",
        comunidad_confirma: Optional[bool] = None,
        incluir_supervision: bool = True,
        gemini_api_key: Optional[str] = None,
    ) -> dict[str, Any]:
        if comunidad_confirma is not None:
            self.sma.db.update_zona(zona_id, comunidad_confirma=comunidad_confirma)

        thread_id = f"{framework_id}-{zona_id}-{uuid4().hex[:6]}"
        initial: BazurtoAgentState = {
            "zona_id": zona_id,
            "conversation_id": thread_id,
            "framework_id": framework_id,
            "gemini_api_key": gemini_api_key,
            "comunidad_confirma": comunidad_confirma,
            "incluir_supervision": incluir_supervision,
            "nodos_visitados": [],
            "transiciones": [],
            "traza": [],
        }
        final_state = self.graph.invoke(initial, config={"configurable": {"thread_id": thread_id}})
        self.checkpointer.delete_thread(thread_id)
        transiciones = list(final_state.get("transiciones") or [])
        last_node = (final_state.get("nodos_visitados") or [{}])[-1].get("nodo", "nodo_alertas")
        transiciones.append(f"{last_node} -> END")

        estado_res = self.sma.db.get_estado_residuos(zona_id) or {}
        hist_aire = self.sma.db.list_historial_aire(zona_id, limit=20)
        return {
            "thread_id": thread_id,
            "uses_native_langgraph": self.uses_native_langgraph,
            "nodos_visitados": list(final_state.get("nodos_visitados") or []),
            "transiciones": transiciones,
            "estado_final_checkpoint": {
                "zona_id": zona_id,
                "tiempoSobreLimite": estado_res.get("tiempo_sobre_limite", 0),
                "ritmoLlenado": estado_res.get("ritmo_llenado", 0.0),
                "ciclosConsecutivos": estado_res.get("ciclos_consecutivos", 0),
                "historialMediciones_count": len(hist_aire),
                "concentracionGases": (final_state.get("medicion_aire") or {}).get("concentracionGases"),
                "riesgo": final_state.get("riesgo"),
                "ranking": list(final_state.get("ranking_zonas") or []),
                "ranking_top": (final_state.get("ranking_zonas") or [{}])[0].get("zona_id"),
                "alerta_id": final_state.get("alerta_id"),
                "resultado_acl": final_state.get("resultado_acl"),
                "incidencias_supervisor": final_state.get("incidencias_supervisor") or [],
            },
            "vision": final_state.get("vision_resumen"),
            "traza": list(final_state.get("traza") or []),
        }


def info_motor() -> dict[str, Any]:
    """Descripcion verificable del motor activo (sin catalogos ni etiquetas de otros frameworks)."""
    return {
        "motor": "LangGraph",
        "version_langgraph": VERSION_LANGGRAPH,
        "checkpointer": "MemorySaver (estado de dominio en SQLite)",
        "nodos_grafo": [
            {"id": "nodo_sensor_residuos", "agente": "AgenteSensorResiduos", "rol": "MonitorCondicionesAmbientales"},
            {"id": "nodo_sensor_aire", "agente": "AgenteSensorAire", "rol": "MonitorCondicionesAmbientales"},
            {"id": "nodo_coordinador", "agente": "AgenteCoordinador", "rol": "Coordinador"},
            {"id": "nodo_alertas", "agente": "AgenteAlertas", "rol": "EmisorAlertas"},
            {"id": "nodo_supervisor", "agente": "AgenteSupervisor", "rol": "Supervisor"},
        ],
        "mermaid_graph": MERMAID_STATEGRAPH,
    }
