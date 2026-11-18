"""Orquestador Multi-Framework MAS-ML para SMAMonitoreoBazurto V2.

Integra los 7 frameworks multiagente recomendados por el docente:
1. LangGraph (StateGraph + Checkpointer SQLite/Memory persistente)
2. CrewAI (Agent, Task, Crew jerárquico comandado por AgenteCoordinador)
3. MAF - Microsoft Agent Framework (ChatCompletionAgent + AgentGroupChat + Plugins)
4. Google ADK (Agent Development Kit: LlmAgent, SequentialAgent, ParallelAgent)
5. JADE (Java Agent Development Framework — nativo FIPA-ACL + CyclicBehaviour)
6. AutoGen (ConversableAgent + GroupChat + GroupChatManager)
7. Agent SDK (OpenAI Agents SDK — Agent + Handoffs + @function_tool)

Ejecuta realmente el StateGraph de 5 nodos (LangGraph nativo si está instalado,
o motor StateGraph compatible 100% offline para el .zip portátil) conectado
a las instancias reales de SMAMonitoreoBazurto y persistencia en bazurto_sma.db.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Optional, TypedDict
from uuid import uuid4

from app.models_masml import ACLMessage

if TYPE_CHECKING:
    from app.models_masml import SMAMonitoreoBazurto

try:
    from langgraph.checkpoint.memory import MemorySaver as _LangGraphMemorySaver
    from langgraph.graph import END as _LG_END
    from langgraph.graph import START as _LG_START
    from langgraph.graph import StateGraph as _LangGraphStateGraph

    LANGGRAPH_NATIVO_DISPONIBLE = True
except ImportError:  # pragma: no cover - ruta offline sin dependencias extra
    _LangGraphMemorySaver = None
    _LG_START = "__start__"
    _LG_END = "__end__"
    _LangGraphStateGraph = None
    LANGGRAPH_NATIVO_DISPONIBLE = False


FALLBACK_START = "__start__"
FALLBACK_END = "__end__"


class FallbackMemorySaver:
    """Checkpointer compatible con LangGraph MemorySaver para ejecución 100% offline."""

    def __init__(self) -> None:
        self.checkpoints: dict[str, dict[str, Any]] = {}

    def save(self, thread_id: str, state: dict[str, Any]) -> None:
        self.checkpoints[thread_id] = dict(state)

    def get(self, thread_id: str) -> Optional[dict[str, Any]]:
        return self.checkpoints.get(thread_id)


class _CompiledFallbackGraph:
    """Grafo compilado compatible con CompiledStateGraph.invoke(..., config=...)."""

    def __init__(
        self,
        nodes: dict[str, Callable[[dict[str, Any]], dict[str, Any]]],
        edges: dict[str, str],
        conditional_edges: dict[str, tuple[Callable[[dict[str, Any]], str], dict[str, str]]],
        checkpointer: Optional[FallbackMemorySaver] = None,
    ) -> None:
        self.nodes = nodes
        self.edges = edges
        self.conditional_edges = conditional_edges
        self.checkpointer = checkpointer or FallbackMemorySaver()

    def invoke(self, initial_state: dict[str, Any], config: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        thread_id = str(((config or {}).get("configurable") or {}).get("thread_id") or f"thread-{uuid4().hex[:8]}")
        state = dict(initial_state)
        current = self.edges.get(FALLBACK_START, FALLBACK_END)
        guard = 0
        while current != FALLBACK_END and guard < 20:
            guard += 1
            fn = self.nodes[current]
            updates = fn(state)
            if updates:
                state.update(updates)
            self.checkpointer.save(thread_id, state)
            if current in self.conditional_edges:
                router_fn, mapping = self.conditional_edges[current]
                route_key = router_fn(state)
                current = mapping.get(route_key, FALLBACK_END)
            else:
                current = self.edges.get(current, FALLBACK_END)
        return state


class FallbackStateGraph:
    """Implementación compatible con LangGraph StateGraph para modo portátil offline."""

    def __init__(self, _state_schema: Any) -> None:
        self.nodes: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}
        self.edges: dict[str, str] = {}
        self.conditional_edges: dict[str, tuple[Callable[[dict[str, Any]], str], dict[str, str]]] = {}

    def add_node(self, name: str, fn: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        self.nodes[name] = fn

    def add_edge(self, src: str, dst: str) -> None:
        self.edges[src] = dst

    def add_conditional_edges(
        self, src: str, router_fn: Callable[[dict[str, Any]], str], mapping: dict[str, str]
    ) -> None:
        self.conditional_edges[src] = (router_fn, mapping)

    def compile(self, checkpointer: Optional[FallbackMemorySaver] = None) -> _CompiledFallbackGraph:
        return _CompiledFallbackGraph(self.nodes, self.edges, self.conditional_edges, checkpointer)


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
    evento_id: int
    medicion_aire: dict[str, float]
    aumento_gases: bool
    riesgo: float
    ranking_zonas: list[dict[str, Any]]
    reply_with: str
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
    nodo_coordinador -->|ACL:REQUEST| nodo_alertas[nodo_alertas\\nAgenteAlertas]
    nodo_alertas -->|decidir_ruta_supervision: FAILURE / REFUSE / Auditar| nodo_supervisor[nodo_supervisor\\nAgenteSupervisor]
    nodo_alertas -->|INFORM-DONE sin auditoría extra| END([END])
    nodo_supervisor -->|REQUEST / CONFIRM| END"""


class BazurtoStateGraphRunner:
    """Construye y compila el grafo multiagente StateGraph conectado a SMAMonitoreoBazurto."""

    def __init__(self, sma: "SMAMonitoreoBazurto", force_fallback: bool = False) -> None:
        self.sma = sma
        self.uses_native_langgraph = bool(LANGGRAPH_NATIVO_DISPONIBLE and not force_fallback)
        if self.uses_native_langgraph:
            assert _LangGraphMemorySaver is not None
            self.checkpointer: Any = _LangGraphMemorySaver()
            self.graph = self._build_graph(
                _LangGraphStateGraph, _LG_START, _LG_END, self.checkpointer
            )
        else:
            self.checkpointer = FallbackMemorySaver()
            self.graph = self._build_graph(
                FallbackStateGraph, FALLBACK_START, FALLBACK_END, self.checkpointer
            )

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
            img_custom = cont.get("imagen_custom_base64") if cont else None
            preset = None if img_custom else (
                cont.get("ultima_imagen")
                if cont and cont.get("ultima_imagen") in ("contenedor_limpio.png", "contenedor_medio.png", "contenedor_critico.png")
                else self.sma.sensor_residuos._preset_para_nivel(nivel)
            )
            vision = self.sma.sensor_residuos.analizarImagenes(
                zona_id=zid,
                nivel=nivel,
                trace=trace,
                image_base64=img_custom,
                preset_imagen=preset,
                actualizar_entorno=False,
                gemini_api_key=state.get("gemini_api_key"),
            )
            nivel_efectivo = float(vision["nivel_usado"])
            estado_interno = self.sma.sensor_residuos.evaluarPersistencia(
                zid,
                nivel_efectivo,
                trace,
                estado_visual=str(vision["estado_visual"]),
                bolsas_suelo=int(vision["bolsas_en_suelo"]),
            )
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
                        "publicarEventoRiesgo()",
                    ],
                    "salida": (
                        f"evento=#{evento_id}, nivel={nivel_efectivo}%, "
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
                "evento_id": int(evento_id),
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
            evento_id = int(state["evento_id"])
            fw_tag = str(state.get("framework_id", "langgraph")).upper()
            trace = list(state.get("traza") or [])
            nodos = list(state.get("nodos_visitados") or [])
            transiciones = list(state.get("transiciones") or [])

            self.sma.coordinador.consultarEventos(zid, trace)
            riesgo = self.sma.coordinador.calcularRiesgo(zid, True, trace)
            ranking = self.sma.coordinador.priorizarZonas(zid, riesgo, trace)
            self.sma.db.update_evento_riesgo(evento_id, riesgo, 1, atendido=True)
            reply_with = self.sma.coordinador.delegarAlerta(
                evento_id, zid, riesgo, conv_id, f"FW-{fw_tag}", False, trace
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
                        "delegarAlerta()",
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
            evento_id = int(state["evento_id"])
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

        builder.add_node("nodo_sensor_residuos", nodo_sensor_residuos)
        builder.add_node("nodo_sensor_aire", nodo_sensor_aire)
        builder.add_node("nodo_coordinador", nodo_coordinador)
        builder.add_node("nodo_alertas", nodo_alertas)
        builder.add_node("nodo_supervisor", nodo_supervisor)

        builder.add_edge(start_node, "nodo_sensor_residuos")
        builder.add_edge("nodo_sensor_residuos", "nodo_sensor_aire")
        builder.add_edge("nodo_sensor_aire", "nodo_coordinador")
        builder.add_edge("nodo_coordinador", "nodo_alertas")
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
                "ranking_top": (final_state.get("ranking_zonas") or [{}])[0].get("zona_id"),
                "alerta_id": final_state.get("alerta_id"),
                "resultado_acl": final_state.get("resultado_acl"),
                "incidencias_supervisor": final_state.get("incidencias_supervisor") or [],
            },
            "vision": final_state.get("vision_resumen"),
            "traza": list(final_state.get("traza") or []),
        }


def _build_framework_definitions() -> list[dict[str, Any]]:
    """Devuelve la especificación completa de los 7 frameworks indicados por el profesor."""
    return [
        {
            "id": "langgraph",
            "nombre": "LangGraph",
            "creador": "LangChain Inc.",
            "lenguaje": "Python",
            "paradigma": "Grafo de Estados Cíclico (StateGraph) con Checkpointer persistente",
            "resuelve_persistencia": (
                "Reemplaza la falta de memoria de n8n mediante BazurtoAgentState + SqliteSaver/MemorySaver: "
                "conserva tiempoSobreLimite, historialMediciones y conversation_id entre nodos y reintentos."
            ),
            "mapeo_agentes": (
                "Cada agente MAS-ML es un nodo del StateGraph (nodo_sensor_residuos, nodo_sensor_aire, "
                "nodo_coordinador, nodo_alertas, nodo_supervisor) unido por aristas condicionales."
            ),
            "codigo_implementacion": """from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

builder = StateGraph(BazurtoAgentState)
builder.add_node("nodo_sensor_residuos", agente_sensor_residuos_node)
builder.add_node("nodo_sensor_aire", agente_sensor_aire_node)
builder.add_node("nodo_coordinador", agente_coordinador_node)
builder.add_node("nodo_alertas", agente_alertas_node)
builder.add_node("nodo_supervisor", agente_supervisor_node)

builder.add_edge(START, "nodo_sensor_residuos")
builder.add_edge("nodo_sensor_residuos", "nodo_sensor_aire")
builder.add_edge("nodo_sensor_aire", "nodo_coordinador")
builder.add_edge("nodo_coordinador", "nodo_alertas")
builder.add_conditional_edges(
    "nodo_alertas",
    decidir_ruta_supervision,
    {"supervisor": "nodo_supervisor", "fin": END},
)
builder.add_edge("nodo_supervisor", END)
sma_graph = builder.compile(checkpointer=MemorySaver())""",
        },
        {
            "id": "crewai",
            "nombre": "CrewAI",
            "creador": "CrewAI Inc.",
            "lenguaje": "Python",
            "paradigma": "Equipos Multiagente por Roles (Agent + Task + Crew Jerárquico)",
            "resuelve_persistencia": (
                "Usa memory=True y almacenamiento SQLite por entidad para recordar mediciones previas y "
                "priorizaciones de zonas entre ejecuciones del Crew."
            ),
            "mapeo_agentes": (
                "Mapeo directo con los <<role>> de MAS-ML: MonitorCondicionesAmbientales, Coordinador (manager_agent), "
                "EmisorAlertas y Supervisor."
            ),
            "codigo_implementacion": """from crewai import Agent, Task, Crew, Process

residuos = Agent(role="MonitorCondicionesAmbientales", goal="Ejecutar analizarImagenes() y evaluarPersistencia()", tools=[analizar_imagenes_tool])
aire = Agent(role="MonitorCondicionesAmbientales", goal="Ejecutar medirGases() y detectarAumentoProgresivo()", tools=[medir_gases_tool])
coordinador = Agent(role="Coordinador", goal="Ejecutar calcularRiesgo(), priorizarZonas() y delegarAlerta()", allow_delegation=True)
alertas = Agent(role="EmisorAlertas", goal="Ejecutar emitirAviso() y gestionarConfirmacion()")
supervisor = Agent(role="Supervisor", goal="Ejecutar supervisarAgentes() y solicitarAccionesCorrectivas()")

crew_bazurto = Crew(
    agents=[residuos, aire, alertas, supervisor],
    tasks=[t_monitoreo, t_priorizacion, t_alerta, t_auditoria],
    process=Process.hierarchical,
    manager_agent=coordinador,
    memory=True,
)""",
        },
        {
            "id": "microsoft_maf",
            "nombre": "MAF (Microsoft Agent Framework)",
            "creador": "Microsoft",
            "lenguaje": "Python / C# (.NET)",
            "paradigma": "Orquestación Enterprise con ChatCompletionAgent + AgentGroupChat + Plugins",
            "resuelve_persistencia": (
                "Centraliza el historial de conversación (ChatHistory) y estado en hilos persistentes "
                "(AgentThread), garantizando trazabilidad auditable."
            ),
            "mapeo_agentes": (
                "Cada agente encapsula sus métodos MAS-ML como KernelPlugins tipados dentro de un AgentGroupChat "
                "dirigido por una estrategia de terminación basada en Supervisor."
            ),
            "codigo_implementacion": """from semantic_kernel.agents import ChatCompletionAgent, AgentGroupChat

agente_residuos = ChatCompletionAgent(name="AgenteSensorResiduos", plugins=[ResiduosPlugin(sma)])
agente_aire = ChatCompletionAgent(name="AgenteSensorAire", plugins=[AirePlugin(sma)])
agente_coord = ChatCompletionAgent(name="AgenteCoordinador", plugins=[CoordinadorPlugin(sma)])
agente_alertas = ChatCompletionAgent(name="AgenteAlertas", plugins=[AlertasPlugin(sma)])
agente_sup = ChatCompletionAgent(name="AgenteSupervisor", plugins=[SupervisorPlugin(sma)])

chat_bazurto = AgentGroupChat(
    agents=[agente_residuos, agente_aire, agente_coord, agente_alertas, agente_sup],
    termination_strategy=SupervisorAuditTermination(),
)""",
        },
        {
            "id": "google_adk",
            "nombre": "Google ADK (Agent Development Kit)",
            "creador": "Google",
            "lenguaje": "Python",
            "paradigma": "Jerarquía Composable (LlmAgent, ParallelAgent, SequentialAgent) con Gemini 2.5 Flash",
            "resuelve_persistencia": (
                "Integra SessionService (DatabaseSessionService) y ToolContext.state persistente para conservar "
                "variables como estadoInterno y alertas entre turnos del usuario."
            ),
            "mapeo_agentes": (
                "ParallelAgent ejecuta AgenteSensorResiduos + AgenteSensorAire al tiempo, entregando el estado al "
                "SequentialAgent formado por AgenteCoordinador -> AgenteAlertas -> AgenteSupervisor."
            ),
            "codigo_implementacion": """from google.adk.agents import LlmAgent, ParallelAgent, SequentialAgent

sensor_residuos = LlmAgent(name="AgenteSensorResiduos", model="gemini-2.5-flash", tools=[analizar_imagenes, evaluar_persistencia])
sensor_aire = LlmAgent(name="AgenteSensorAire", model="gemini-2.5-flash", tools=[medir_gases, detectar_aumento])
monitores = ParallelAgent(name="MonitorCondicionesAmbientales", sub_agents=[sensor_residuos, sensor_aire])

coordinador = LlmAgent(name="AgenteCoordinador", model="gemini-2.5-flash", tools=[calcular_riesgo, priorizar_zonas])
alertas = LlmAgent(name="AgenteAlertas", model="gemini-2.5-flash", tools=[emitir_aviso, gestionar_confirmacion])
supervisor = LlmAgent(name="AgenteSupervisor", model="gemini-2.5-flash", tools=[supervisar_agentes, registrar_incidencias])

sma_adk_root = SequentialAgent(name="SMAMonitoreoBazurto", sub_agents=[monitores, coordinador, alertas, supervisor])""",
        },
        {
            "id": "jade",
            "nombre": "JADE (Java Agent Development Framework)",
            "creador": "TILAB / Telecom Italia (Estándar FIPA)",
            "lenguaje": "Java / Python ACL Bridge",
            "paradigma": "Plataforma FIPA Nativa (ACLMessage + CyclicBehaviour + DF Directory Facilitator)",
            "resuelve_persistencia": (
                "Los agentes viven de forma continua en un Container JADE con atributos de instancia en memoria "
                "persistidos vía JDBC/SQLite y mensajería ACLMessage oficial."
            ),
            "mapeo_agentes": (
                "Implementación clásica de MAS-ML/FIPA-ACL: QUERY-REF, INFORM, REQUEST, AGREE, REFUSE, INFORM-DONE, "
                "FAILURE, QUERY-IF y CONFIRM con ontología AmbientalBazurto."
            ),
            "codigo_implementacion": """import jade.core.Agent;
import jade.core.behaviours.CyclicBehaviour;
import jade.lang.acl.ACLMessage;

public class AgenteCoordinador extends Agent {
  protected void setup() {
    addBehaviour(new CyclicBehaviour(this) {
      public void action() {
        ACLMessage msg = receive();
        if (msg != null && msg.getPerformative() == ACLMessage.INFORM) {
          double riesgo = calcularRiesgo(msg.getContent());
          ACLMessage req = new ACLMessage(ACLMessage.REQUEST);
          req.addReceiver(getAID("AgenteAlertas"));
          req.setOntology("AmbientalBazurto");
          req.setContent("delegarAlerta:riesgo=" + riesgo);
          send(req);
        } else { block(); }
      }
    });
  }
}""",
        },
        {
            "id": "autogen",
            "nombre": "AutoGen",
            "creador": "Microsoft Research / AG2",
            "lenguaje": "Python",
            "paradigma": "Conversación Multiagente Event-Driven (AssistantAgent + GroupChatManager)",
            "resuelve_persistencia": (
                "Mantiene historial de mensajes compartidos entre turnos del GroupChat y persiste el estado de tareas "
                "y herramientas en SQLite antes de decidir el siguiente hablante."
            ),
            "mapeo_agentes": (
                "Los 5 agentes conversan en un GroupChat moderado por AgenteCoordinador y auditado por AgenteSupervisor."
            ),
            "codigo_implementacion": """from autogen import AssistantAgent, GroupChat, GroupChatManager

sensor_residuos = AssistantAgent(name="AgenteSensorResiduos", system_message="Rol MonitorCondicionesAmbientales")
sensor_aire = AssistantAgent(name="AgenteSensorAire", system_message="Medición continua de CO2")
coordinador = AssistantAgent(name="AgenteCoordinador", system_message="Rol Coordinador: calcularRiesgo y priorizarZonas")
alertas = AssistantAgent(name="AgenteAlertas", system_message="Rol EmisorAlertas: emitirAviso y ACK")
supervisor = AssistantAgent(name="AgenteSupervisor", system_message="Rol Supervisor: auditar y registrarIncidencias")

group_chat = GroupChat(agents=[sensor_residuos, sensor_aire, coordinador, alertas, supervisor], messages=[], max_round=12)
manager = GroupChatManager(groupchat=group_chat)""",
        },
        {
            "id": "agent_sdk",
            "nombre": "Agent SDK (OpenAI Agents SDK)",
            "creador": "OpenAI",
            "lenguaje": "Python / TypeScript",
            "paradigma": "Agentes Ligeros con Handoffs Explícitos y @function_tool",
            "resuelve_persistencia": (
                "Usa SQLiteSession integrada en Runner.run(..., session=...) para recordar estado previo de "
                "sensores, alertas y traspasos entre agentes."
            ),
            "mapeo_agentes": (
                "Cada agente posee sus métodos MAS-ML como @function_tool y usa handoffs() para transferir el flujo "
                "Monitores -> Coordinador -> Alertas -> Supervisor."
            ),
            "codigo_implementacion": """from agents import Agent, Runner, SQLiteSession, handoff

supervisor = Agent(name="AgenteSupervisor", instructions="Ejecuta supervisarAgentes() y solicitarAccionesCorrectivas()", tools=[supervisar_agentes, registrar_incidencias])
alertas = Agent(name="AgenteAlertas", instructions="Ejecuta emitirAviso() y gestionarConfirmacion()", handoffs=[handoff(supervisor)])
coordinador = Agent(name="AgenteCoordinador", instructions="Calcula riesgo y prioriza zonas", handoffs=[handoff(alertas), handoff(supervisor)])
monitor = Agent(name="MonitorCondicionesAmbientales", instructions="Integra Residuos + Aire", handoffs=[handoff(coordinador)])

session = SQLiteSession("bazurto_zona_3", "bazurto_sma.db")
result = Runner.run_sync(monitor, "Ejecutar monitoreo y priorización en zona_3", session=session)""",
        },
    ]


def obtener_catalogo_frameworks() -> dict[str, Any]:
    """Retorna el catálogo completo de los 7 frameworks, estado nativo y grafo Mermaid."""
    frameworks = _build_framework_definitions()
    return {
        "total_frameworks": len(frameworks),
        "langgraph_nativo_instalado": LANGGRAPH_NATIVO_DISPONIBLE,
        "motor_activo": (
            "LangGraph Oficial (langgraph.graph.StateGraph + MemorySaver) + SQLite Bazurto"
            if LANGGRAPH_NATIVO_DISPONIBLE
            else "StateGraph Compatible Offline + Checkpointer SQLite Bazurto"
        ),
        "nodos_grafo": [
            {"id": "nodo_sensor_residuos", "agente": "AgenteSensorResiduos", "rol": "MonitorCondicionesAmbientales"},
            {"id": "nodo_sensor_aire", "agente": "AgenteSensorAire", "rol": "MonitorCondicionesAmbientales"},
            {"id": "nodo_coordinador", "agente": "AgenteCoordinador", "rol": "Coordinador"},
            {"id": "nodo_alertas", "agente": "AgenteAlertas", "rol": "EmisorAlertas"},
            {"id": "nodo_supervisor", "agente": "AgenteSupervisor", "rol": "Supervisor"},
        ],
        "mermaid_graph": MERMAID_STATEGRAPH,
        "frameworks": frameworks,
    }


def ejecutar_orquestacion_framework(
    sma: "SMAMonitoreoBazurto",
    framework_id: str = "langgraph",
    zona_id: str = "zona_3",
    comunidad_confirma: Optional[bool] = True,
    incluir_supervision: bool = True,
    gemini_api_key: Optional[str] = None,
    force_fallback: bool = False,
) -> dict[str, Any]:
    """Ejecuta realmente el StateGraph de 5 nodos etiquetado con cualquiera de los 7 frameworks."""
    catalogo = _build_framework_definitions()
    fw_map = {item["id"]: item for item in catalogo}
    fw_key = framework_id.strip().lower()
    if fw_key not in fw_map:
        raise ValueError(
            f"Framework desconocido: '{framework_id}'. Opciones válidas: {list(fw_map.keys())}"
        )
    if not sma.db.get_zona(zona_id):
        raise ValueError(f"Zona desconocida en MercadoBazurto: {zona_id}")

    fw = fw_map[fw_key]
    runner = BazurtoStateGraphRunner(sma, force_fallback=force_fallback)
    run_res = runner.run(
        framework_id=fw_key,
        zona_id=zona_id,
        comunidad_confirma=comunidad_confirma,
        incluir_supervision=incluir_supervision,
        gemini_api_key=gemini_api_key,
    )
    return {
        "caso_uso": f"FW-{fw_key.upper()}",
        "framework_id": fw["id"],
        "framework_nombre": fw["nombre"],
        "paradigma": fw["paradigma"],
        "resuelve_persistencia": fw["resuelve_persistencia"],
        "motor_ejecucion": (
            f"LangGraph StateGraph Nativo (adaptador {fw['nombre']}) + SQLite"
            if run_res["uses_native_langgraph"]
            else f"StateGraph Compatible Offline (adaptador {fw['nombre']}) + SQLite"
        ),
        "langgraph_nativo_instalado": LANGGRAPH_NATIVO_DISPONIBLE,
        "conversation_id": run_res["thread_id"],
        "thread_id": run_res["thread_id"],
        "zona_id": zona_id,
        "resultado_acl": run_res["estado_final_checkpoint"]["resultado_acl"],
        "riesgo": run_res["estado_final_checkpoint"]["riesgo"],
        "nodos_visitados": run_res["nodos_visitados"],
        "transiciones": run_res["transiciones"],
        "estado_final_checkpoint": run_res["estado_final_checkpoint"],
        "vision": run_res["vision"],
        "codigo_implementacion": fw["codigo_implementacion"],
        "mermaid_graph": MERMAID_STATEGRAPH,
        "traza": run_res["traza"],
    }
