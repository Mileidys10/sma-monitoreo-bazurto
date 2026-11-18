"""Implementación 1:1 del Diagrama de Clases MAS-ML para SMAMonitoreoBazurto."""

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from app.database import BazurtoDatabase
from app.fipa_acl import ACLMessage
from app.vision_analyzer import analizar_imagen_contenedor


@dataclass
class UmbralesConfigurables:
    """Parámetros de umbral ambiental para la organización SMAMonitoreoBazurto."""

    nivel_residuos_critico: float = 80.0
    tiempo_persistencia_min: int = 30
    gases_co2_critico: float = 700.0
    riesgo_alerta_umbral: float = 0.65


@dataclass
class MonitorCondicionesAmbientales:
    """<<role>> MonitorCondicionesAmbientales."""

    duties: list[str] = field(
        default_factory=lambda: [
            "obtener mediciones ambientales",
            "analizar condiciones del entorno",
            "identificar situaciones de riesgo",
            "reportar eventos ambientales",
        ]
    )
    rights: list[str] = field(
        default_factory=lambda: [
            "acceder a los datos de los sensores",
            "consultar mediciones ambientales",
            "comunicar eventos al coordinador",
        ]
    )


@dataclass
class Coordinador:
    """<<role>> Coordinador."""

    duties: list[str] = field(
        default_factory=lambda: [
            "calcular riesgo ambiental",
            "priorizar zonas",
            "delegar emisión de alertas",
            "escalar situaciones",
        ]
    )
    rights: list[str] = field(
        default_factory=lambda: [
            "consultar eventos ambientales",
            "solicitar emisión de alertas",
        ]
    )


@dataclass
class EmisorAlertas:
    """<<role>> EmisorAlertas."""

    duties: list[str] = field(
        default_factory=lambda: [
            "emitir mensajes a la comunidad",
            "gestionar confirmaciones de recepción",
            "generar reportes de confirmación o falta de confirmación",
        ]
    )
    rights: list[str] = field(
        default_factory=lambda: [
            "recibir solicitudes de alerta",
            "acceder a mecanismos de comunicación",
            "consultar estado de alertas",
        ]
    )


@dataclass
class Supervisor:
    """<<role>> Supervisor."""

    duties: list[str] = field(
        default_factory=lambda: [
            "supervisar funcionamiento de agentes",
            "verificar atención de eventos",
            "registrar incidencias",
            "notificar fallos",
        ]
    )
    rights: list[str] = field(
        default_factory=lambda: [
            "consultar estado general del sistema",
            "solicitar acciones correctivas",
        ]
    )


class MercadoBazurto:
    """<<environment>> MercadoBazurto conectado a la persistencia SQLite."""

    def __init__(self, db: BazurtoDatabase) -> None:
        self.db = db

    @property
    def zonas(self) -> list[dict[str, Any]]:
        return self.db.list_zonas()

    def leer_atributos_zona(self, zona_id: str) -> dict[str, Any]:
        zona = self.db.get_zona(zona_id)
        if not zona:
            raise ValueError(f"Zona {zona_id} no encontrada en MercadoBazurto")
        return {
            "zona_id": zona["zona_id"],
            "nombre": zona["nombre"],
            "nivelLlenadoContenedores": zona["nivel_llenado_contenedores"],
            "concentracionGases": zona["concentracion_gases"],
            "temperatura": zona["temperatura"],
            "humedad": zona["humedad"],
            "sensor_aire_activo": bool(zona["sensor_aire_activo"]),
            "comunidad_confirma": bool(zona["comunidad_confirma"]),
        }


_OBSERVADORES_ACL: list[Callable[[ACLMessage], None]] = []


def registrar_observador_acl(fn: Callable[[ACLMessage], None]) -> None:
    """Registra un callback que recibe cada mensaje FIPA-ACL en el instante en que se emite."""
    if fn not in _OBSERVADORES_ACL:
        _OBSERVADORES_ACL.append(fn)



class AgenteBase:
    """Base común para trazabilidad de ejecución y envío de mensajes FIPA-ACL."""

    def __init__(self, nombre: str, rol: Any, arquitectura: str, db: BazurtoDatabase) -> None:
        self.nombre = nombre
        self.rol = rol
        self.arquitectura = arquitectura
        self.db = db

    def emitir_acl(self, msg: ACLMessage, trace: list[dict[str, Any]]) -> ACLMessage:
        self.db.save_acl_message(msg)
        trace.append(
            {
                "tipo": "ACL",
                "performative": msg.performative.upper(),
                "sender": msg.sender,
                "receiver": msg.receiver,
                "metodo_origen": msg.metodo_origen,
                "protocol": msg.protocol,
                "content": msg.content,
                "sexpr": msg.to_sexpr(),
                "json": msg.to_dict(),
            }
        )
        for observador in list(_OBSERVADORES_ACL):
            try:
                observador(msg)
            except Exception:  # un observador defectuoso nunca debe romper al agente
                pass
        return msg


class AgenteSensorResiduos(AgenteBase):
    """<<agent>> AgenteSensorResiduos (Basado en modelos) — juega MonitorCondicionesAmbientales."""

    def __init__(self, db: BazurtoDatabase, entorno: MercadoBazurto, umbrales: UmbralesConfigurables) -> None:
        super().__init__("AgenteSensorResiduos", MonitorCondicionesAmbientales(), "Basado en modelos", db)
        self.entorno = entorno
        self.umbrales = umbrales

    def medirNivelLlenadoContenedores(self, zona_id: str, trace: list[dict[str, Any]]) -> float:
        datos = self.entorno.leer_atributos_zona(zona_id)
        nivel = float(datos["nivelLlenadoContenedores"])
        trace.append(
            {
                "tipo": "METODO",
                "agente": self.nombre,
                "metodo": "medirNivelLlenadoContenedores()",
                "detalle": f"Consulta a MercadoBazurto({zona_id}) -> nivelLlenadoContenedores={nivel}%",
            }
        )
        return nivel

    def _preset_para_nivel(self, nivel: float) -> str:
        if nivel >= self.umbrales.nivel_residuos_critico:
            return "contenedor_critico.png"
        if nivel >= 45.0:
            return "contenedor_medio.png"
        return "contenedor_limpio.png"

    def analizarImagenes(
        self,
        zona_id: str,
        nivel: float,
        trace: list[dict[str, Any]],
        image_base64: Optional[str] = None,
        preset_imagen: Optional[str] = None,
        actualizar_entorno: bool = False,
        gemini_api_key: Optional[str] = None,
    ) -> dict[str, Any]:
        tiene_fuente_explicita = bool(image_base64 or preset_imagen)
        chosen_preset = preset_imagen or self._preset_para_nivel(nivel)
        vision = analizar_imagen_contenedor(
            image_input=image_base64,
            preset_name=chosen_preset,
            umbral_critico=self.umbrales.nivel_residuos_critico,
            gemini_api_key=gemini_api_key,
        )
        contenedor_detectado = bool(vision.get("contenedor_detectado", True))
        if not contenedor_detectado:
            nivel_final = nivel
            desbordamiento = False
            estado_visual = "sin_contenedor_detectado"
            detalle = (
                f"Vision real ({vision['fuente_imagen']}) en {zona_id}: sin_contenedor_detectado. "
                f"Imagen descartada sin alterar MercadoBazurto (se conserva nivel={nivel_final}%)."
            )
        else:
            nivel_final = vision["nivel_llenado_visual"] if (tiene_fuente_explicita or actualizar_entorno) else nivel
            if tiene_fuente_explicita or actualizar_entorno:
                self.db.update_zona(zona_id, nivel_llenado_contenedores=nivel_final)

            desbordamiento = bool(vision["desbordamiento"] or nivel_final >= self.umbrales.nivel_residuos_critico)
            estado_visual = "desbordamiento_detectado" if desbordamiento else "contenedor_estable"
            detalle = (
                f"Vision real ({vision['fuente_imagen']}) en {zona_id}: {estado_visual} "
                f"(llenado_visual={vision['nivel_llenado_visual']}%, "
                f"bolsas_suelo={vision['bolsas_en_suelo']}, nivel_usado={nivel_final}%)"
            )

        trace.append(
            {
                "tipo": "METODO",
                "agente": self.nombre,
                "metodo": "analizarImagenes()",
                "detalle": detalle,
            }
        )
        return {
            **vision,
            "zona_id": zona_id,
            "contenedor_detectado": contenedor_detectado,
            "desbordamiento": desbordamiento,
            "estado_visual": estado_visual,
            "nivel_usado": nivel_final,
        }

    def evaluarPersistencia(
        self,
        zona_id: str,
        nivel: float,
        trace: list[dict[str, Any]],
        estado_visual: str = "contenedor_estable",
        bolsas_suelo: int = 0,
    ) -> dict[str, Any]:
        previo = self.db.get_estado_residuos(zona_id)
        if previo:
            ritmo = round(nivel - float(previo["nivel"]), 2)
            if nivel >= self.umbrales.nivel_residuos_critico:
                tiempo = int(previo["tiempo_sobre_limite"]) + 15
                ciclos = int(previo["ciclos_consecutivos"]) + 1
            else:
                tiempo = 0
                ciclos = 0
        else:
            ritmo = 0.0
            tiempo = 15 if nivel >= self.umbrales.nivel_residuos_critico else 0
            ciclos = 1 if nivel >= self.umbrales.nivel_residuos_critico else 0

        estado_interno = self.db.upsert_estado_residuos(
            zona_id, nivel, tiempo, ritmo, ciclos, estado_visual=estado_visual, bolsas_suelo=bolsas_suelo
        )
        persiste = nivel >= self.umbrales.nivel_residuos_critico and tiempo >= self.umbrales.tiempo_persistencia_min
        trace.append(
            {
                "tipo": "METODO",
                "agente": self.nombre,
                "metodo": "evaluarPersistencia()",
                "detalle": (
                    f"estadoInterno persistido en SQLite -> nivel={nivel}%, "
                    f"tiempoSobreLimite={tiempo}min, ritmoLlenado={ritmo}, "
                    f"vision={estado_visual}, persiste={persiste}"
                ),
            }
        )
        return {**estado_interno, "persiste": persiste}

    def publicarEventoRiesgo(
        self,
        zona_id: str,
        estado_interno: dict[str, Any],
        conversation_id: str,
        caso_uso: str,
        trace: list[dict[str, Any]],
    ) -> int:
        evento_id = self.db.insert_evento(
            zona_id=zona_id,
            origen=self.nombre,
            descripcion=(
                f"Contenedor sobre limite ({estado_interno['nivel']}%, "
                f"t={estado_interno['tiempo_sobre_limite']}min)"
            ),
        )
        trace.append(
            {
                "tipo": "METODO",
                "agente": self.nombre,
                "metodo": "publicarEventoRiesgo()",
                "detalle": f"Evento #{evento_id} registrado y enviado por INFORM a AgenteCoordinador",
            }
        )
        msg = ACLMessage(
            performative="INFORM",
            sender=self.nombre,
            receiver="AgenteCoordinador",
            content={
                "eventoRiesgo": zona_id,
                "evento_id": evento_id,
                "nivel": estado_interno["nivel"],
                "tiempoSobreLimite": estado_interno["tiempo_sobre_limite"],
                "ritmoLlenado": estado_interno["ritmo_llenado"],
            },
            protocol="FIPA-Inform",
            conversation_id=conversation_id,
            metodo_origen="publicarEventoRiesgo()",
            caso_uso=caso_uso,
        )
        self.emitir_acl(msg, trace)
        return evento_id


class AgenteSensorAire(AgenteBase):
    """<<agent>> AgenteSensorAire (Basado en modelos) — juega MonitorCondicionesAmbientales."""

    def __init__(self, db: BazurtoDatabase, entorno: MercadoBazurto, umbrales: UmbralesConfigurables) -> None:
        super().__init__("AgenteSensorAire", MonitorCondicionesAmbientales(), "Basado en modelos", db)
        self.entorno = entorno
        self.umbrales = umbrales

    def medirGases(self, zona_id: str, trace: list[dict[str, Any]]) -> dict[str, float]:
        datos = self.entorno.leer_atributos_zona(zona_id)
        medicion = {
            "concentracionGases": float(datos["concentracionGases"]),
            "temperatura": float(datos["temperatura"]),
            "humedad": float(datos["humedad"]),
        }
        trace.append(
            {
                "tipo": "METODO",
                "agente": self.nombre,
                "metodo": "medirGases()",
                "detalle": (
                    f"Consulta a MercadoBazurto({zona_id}) -> "
                    f"CO2={medicion['concentracionGases']}ppm, "
                    f"temp={medicion['temperatura']}C, hum={medicion['humedad']}%"
                ),
            }
        )
        return medicion

    def registrarMedicion(self, zona_id: str, medicion: dict[str, float], trace: list[dict[str, Any]]) -> int:
        med_id = self.db.insert_medicion_aire(
            zona_id, medicion["concentracionGases"], medicion["temperatura"], medicion["humedad"]
        )
        trace.append(
            {
                "tipo": "METODO",
                "agente": self.nombre,
                "metodo": "registrarMedicion()",
                "detalle": f"Medicion #{med_id} persistida en historialMediciones de {zona_id}",
            }
        )
        return med_id

    def detectarAumentoProgresivo(self, zona_id: str, trace: list[dict[str, Any]]) -> bool:
        historial = self.db.list_historial_aire(zona_id, limit=3)
        valores = [float(m["concentracion_gases"]) for m in reversed(historial)]
        aumento = len(valores) >= 2 and valores[-1] > valores[0] and valores[-1] >= self.umbrales.gases_co2_critico
        trace.append(
            {
                "tipo": "METODO",
                "agente": self.nombre,
                "metodo": "detectarAumentoProgresivo()",
                "detalle": f"Serie CO2 reciente {valores} -> aumentoProgresivo={aumento}",
            }
        )
        return aumento

    def publicarMedicion(
        self,
        zona_id: str,
        medicion: dict[str, float],
        aumento_progresivo: bool,
        conversation_id: str,
        caso_uso: str,
        trace: list[dict[str, Any]],
    ) -> None:
        trace.append(
            {
                "tipo": "METODO",
                "agente": self.nombre,
                "metodo": "publicarMedicion()",
                "detalle": f"Publicando medicion de aire {zona_id} via ACL:INFORM",
            }
        )
        msg = ACLMessage(
            performative="INFORM",
            sender=self.nombre,
            receiver="AgenteCoordinador",
            content={
                "medicion": zona_id,
                "concentracionGases": medicion["concentracionGases"],
                "temperatura": medicion["temperatura"],
                "humedad": medicion["humedad"],
                "aumentoProgresivo": aumento_progresivo,
            },
            protocol="FIPA-Inform",
            conversation_id=conversation_id,
            metodo_origen="publicarMedicion()",
            caso_uso=caso_uso,
        )
        self.emitir_acl(msg, trace)


class AgenteCoordinador(AgenteBase):
    """<<agent>> AgenteCoordinador (Basado en utilidad) — juega Coordinador."""

    def __init__(self, db: BazurtoDatabase, entorno: MercadoBazurto, umbrales: UmbralesConfigurables) -> None:
        super().__init__("AgenteCoordinador", Coordinador(), "Basado en utilidad", db)
        self.entorno = entorno
        self.umbrales = umbrales

    def consultarEventos(self, zona_id: str, trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
        eventos = [e for e in self.db.list_eventos(limit=10) if e["zona_id"] == zona_id]
        trace.append(
            {
                "tipo": "METODO",
                "agente": self.nombre,
                "metodo": "consultarEventos()",
                "detalle": f"Consultados {len(eventos)} eventos recientes para {zona_id}",
            }
        )
        return eventos

    def calcularRiesgo(
        self, zona_id: str, incluir_sensor_aire: bool, trace: list[dict[str, Any]]
    ) -> float:
        datos = self.entorno.leer_atributos_zona(zona_id)
        factor_residuos = min(float(datos["nivelLlenadoContenedores"]) / 100.0, 1.0)
        if incluir_sensor_aire and datos["sensor_aire_activo"]:
            factor_gases = min(float(datos["concentracionGases"]) / 1000.0, 1.0)
            riesgo = round(0.55 * factor_residuos + 0.45 * factor_gases, 2)
        else:
            riesgo = round(factor_residuos, 2)
        trace.append(
            {
                "tipo": "METODO",
                "agente": self.nombre,
                "metodo": "calcularRiesgo()",
                "detalle": f"Utilidad ambiental calculada para {zona_id}: riesgo={riesgo} (sensor_aire={incluir_sensor_aire})",
            }
        )
        return riesgo

    def priorizarZonas(
        self, zona_objetivo: str, riesgo_objetivo: float, trace: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        ranking = []
        for z in self.entorno.zonas:
            if z["zona_id"] == zona_objetivo:
                r = riesgo_objetivo
            else:
                r = round(
                    0.55 * min(z["nivel_llenado_contenedores"] / 100.0, 1.0)
                    + 0.45 * min(z["concentracion_gases"] / 1000.0, 1.0),
                    2,
                )
            ranking.append({"zona_id": z["zona_id"], "riesgo": r})
        ranking.sort(key=lambda item: item["riesgo"], reverse=True)
        trace.append(
            {
                "tipo": "METODO",
                "agente": self.nombre,
                "metodo": "priorizarZonas()",
                "detalle": f"Ranking por utilidad: {ranking}",
            }
        )
        return ranking

    def delegarAlerta(
        self,
        evento_id: int,
        zona_id: str,
        riesgo: float,
        conversation_id: str,
        caso_uso: str,
        reintento: bool,
        trace: list[dict[str, Any]],
    ) -> str:
        nivel_alerta = "ALTO" if riesgo >= self.umbrales.riesgo_alerta_umbral else "MODERADO"
        reply_with = f"req-alerta-{evento_id}"
        trace.append(
            {
                "tipo": "METODO",
                "agente": self.nombre,
                "metodo": "delegarAlerta()",
                "detalle": f"Delegando emision de alerta para {zona_id} (riesgo={riesgo}, nivel={nivel_alerta})",
            }
        )
        msg = ACLMessage(
            performative="REQUEST",
            sender=self.nombre,
            receiver="AgenteAlertas",
            content={
                "action": "emitir_alerta",
                "zona": zona_id,
                "evento_id": evento_id,
                "riesgo": riesgo,
                "nivel": nivel_alerta,
                "reintento": reintento,
            },
            protocol="FIPA-Request",
            conversation_id=conversation_id,
            reply_with=reply_with,
            metodo_origen="delegarAlerta()",
            caso_uso=caso_uso,
        )
        self.emitir_acl(msg, trace)
        return reply_with


class AgenteAlertas(AgenteBase):
    """<<agent>> AgenteAlertas (Basado en metas) — juega EmisorAlertas."""

    def __init__(self, db: BazurtoDatabase, entorno: MercadoBazurto) -> None:
        super().__init__("AgenteAlertas", EmisorAlertas(), "Basado en metas", db)
        self.entorno = entorno

    def recibirSolicitudAlerta(
        self,
        zona_id: str,
        forzar_duplicada: bool,
        reply_with: str,
        conversation_id: str,
        caso_uso: str,
        trace: list[dict[str, Any]],
    ) -> bool:
        alerta_activa = self.db.get_active_alerta_zona(zona_id)
        duplicada = forzar_duplicada or (alerta_activa is not None and forzar_duplicada)
        trace.append(
            {
                "tipo": "METODO",
                "agente": self.nombre,
                "metodo": "recibirSolicitudAlerta()",
                "detalle": f"Evaluando solicitud de alerta para {zona_id} (duplicada={duplicada})",
            }
        )
        if duplicada:
            msg = ACLMessage(
                performative="REFUSE",
                sender=self.nombre,
                receiver="AgenteCoordinador",
                content={"motivo": "alerta_ya_emitida", "zona": zona_id},
                protocol="FIPA-Request",
                conversation_id=conversation_id,
                in_reply_to=reply_with,
                metodo_origen="recibirSolicitudAlerta()",
                caso_uso=caso_uso,
            )
            self.emitir_acl(msg, trace)
            return False

        msg = ACLMessage(
            performative="AGREE",
            sender=self.nombre,
            receiver="AgenteCoordinador",
            content={"action": "emitir_alerta", "zona": zona_id},
            protocol="FIPA-Request",
            conversation_id=conversation_id,
            in_reply_to=reply_with,
            metodo_origen="recibirSolicitudAlerta()",
            caso_uso=caso_uso,
        )
        self.emitir_acl(msg, trace)
        return True

    def emitirAviso(self, zona_id: str, trace: list[dict[str, Any]]) -> None:
        trace.append(
            {
                "tipo": "METODO",
                "agente": self.nombre,
                "metodo": "emitirAviso()",
                "detalle": f"Difundiendo aviso ambiental a comerciantes y comunidad de {zona_id}",
            }
        )

    def gestionarConfirmacion(self, zona_id: str, trace: list[dict[str, Any]]) -> bool:
        datos = self.entorno.leer_atributos_zona(zona_id)
        confirmada = bool(datos["comunidad_confirma"])
        trace.append(
            {
                "tipo": "METODO",
                "agente": self.nombre,
                "metodo": "gestionarConfirmacion()",
                "detalle": f"Estado de confirmacion comunitaria en {zona_id}: confirmada={confirmada}",
            }
        )
        return confirmada

    def generarReporteConfirmacion(
        self,
        evento_id: int,
        zona_id: str,
        nivel: str,
        reply_with: str,
        conversation_id: str,
        caso_uso: str,
        trace: list[dict[str, Any]],
        existing_alerta_id: Optional[int] = None,
    ) -> int:
        reporte = f"Alerta en {zona_id} emitida y confirmada por la comunidad del Mercado de Bazurto."
        if existing_alerta_id is not None:
            self.db.update_alerta_confirmacion(existing_alerta_id, "CONFIRMADA", True, reporte)
            alerta_id = existing_alerta_id
        else:
            alerta_id = self.db.insert_alerta(evento_id, zona_id, nivel, "CONFIRMADA", True, reporte)
        trace.append(
            {
                "tipo": "METODO",
                "agente": self.nombre,
                "metodo": "generarReporteConfirmacion()",
                "detalle": f"Reporte de confirmacion guardado (alerta #{alerta_id})",
            }
        )
        msg = ACLMessage(
            performative="INFORM-DONE",
            sender=self.nombre,
            receiver="AgenteCoordinador",
            content={"estado": "alerta_confirmada", "zona": zona_id, "alerta_id": alerta_id},
            protocol="FIPA-Request",
            conversation_id=conversation_id,
            in_reply_to=reply_with,
            metodo_origen="generarReporteConfirmacion()",
            caso_uso=caso_uso,
        )
        self.emitir_acl(msg, trace)
        return alerta_id

    def generarReporteSinConfirmacion(
        self,
        evento_id: int,
        zona_id: str,
        nivel: str,
        reply_with: str,
        conversation_id: str,
        caso_uso: str,
        trace: list[dict[str, Any]],
        existing_alerta_id: Optional[int] = None,
    ) -> int:
        reporte = f"Alerta en {zona_id} emitida pero SIN confirmacion de recepcion comunitaria."
        if existing_alerta_id is not None:
            self.db.update_alerta_confirmacion(existing_alerta_id, "SIN_CONFIRMACION", False, reporte)
            alerta_id = existing_alerta_id
        else:
            alerta_id = self.db.insert_alerta(evento_id, zona_id, nivel, "SIN_CONFIRMACION", False, reporte)
        trace.append(
            {
                "tipo": "METODO",
                "agente": self.nombre,
                "metodo": "generarReporteSinConfirmacion()",
                "detalle": f"Reporte de falta de confirmacion guardado (alerta #{alerta_id})",
            }
        )
        msg = ACLMessage(
            performative="FAILURE",
            sender=self.nombre,
            receiver="AgenteCoordinador",
            content={"motivo": "sin_confirmacion_comunitaria", "zona": zona_id, "alerta_id": alerta_id},
            protocol="FIPA-Request",
            conversation_id=conversation_id,
            in_reply_to=reply_with,
            metodo_origen="generarReporteSinConfirmacion()",
            caso_uso=caso_uso,
        )
        self.emitir_acl(msg, trace)
        return alerta_id


class AgenteSupervisor(AgenteBase):
    """<<agent>> AgenteSupervisor (Basado en utilidad) — juega Supervisor."""

    def __init__(self, db: BazurtoDatabase) -> None:
        super().__init__("AgenteSupervisor", Supervisor(), "Basado en utilidad", db)

    def supervisarAgentes(self, trace: list[dict[str, Any]]) -> None:
        trace.append(
            {
                "tipo": "METODO",
                "agente": self.nombre,
                "metodo": "supervisarAgentes()",
                "detalle": "Iniciando ronda de auditoria sobre MonitorCondicionesAmbientales, Coordinador y EmisorAlertas",
            }
        )

    def verificarAtencionEventos(self, zona_id: str, trace: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
        evento = self.db.get_latest_evento(zona_id)
        trace.append(
            {
                "tipo": "METODO",
                "agente": self.nombre,
                "metodo": "verificarAtencionEventos()",
                "detalle": f"Verificando atencion de evento mas reciente en {zona_id}: {evento['id'] if evento else 'ninguno'}",
            }
        )
        return evento

    def registrarIncidencias(
        self, agente_afectado: str, zona_id: str, descripcion: str, accion: str, trace: list[dict[str, Any]]
    ) -> int:
        inc_id = self.db.insert_incidencia(agente_afectado, zona_id, descripcion, accion)
        trace.append(
            {
                "tipo": "METODO",
                "agente": self.nombre,
                "metodo": "registrarIncidencias()",
                "detalle": f"Incidencia #{inc_id} registrada en SQLite: {descripcion}",
            }
        )
        return inc_id

    def notificarFallos(
        self,
        agente_fallido: str,
        zona_id: str,
        conversation_id: str,
        caso_uso: str,
        trace: list[dict[str, Any]],
    ) -> None:
        trace.append(
            {
                "tipo": "METODO",
                "agente": self.nombre,
                "metodo": "notificarFallos()",
                "detalle": f"Notificando fallo de {agente_fallido} en {zona_id} al AgenteCoordinador",
            }
        )
        msg = ACLMessage(
            performative="INFORM",
            sender=self.nombre,
            receiver="AgenteCoordinador",
            content={"fallo": agente_fallido, "zona": zona_id},
            protocol="FIPA-Inform",
            conversation_id=conversation_id,
            metodo_origen="notificarFallos()",
            caso_uso=caso_uso,
        )
        self.emitir_acl(msg, trace)

    def solicitarAccionesCorrectivas(
        self,
        accion: str,
        zona_id: str,
        conversation_id: str,
        caso_uso: str,
        trace: list[dict[str, Any]],
    ) -> str:
        reply_with = f"req-corr-{zona_id}"
        trace.append(
            {
                "tipo": "METODO",
                "agente": self.nombre,
                "metodo": "solicitarAccionesCorrectivas()",
                "detalle": f"Solicitando accion correctiva ({accion}) al AgenteCoordinador",
            }
        )
        msg = ACLMessage(
            performative="REQUEST",
            sender=self.nombre,
            receiver="AgenteCoordinador",
            content={"accion_correctiva": accion, "zona": zona_id},
            protocol="FIPA-Request",
            conversation_id=conversation_id,
            reply_with=reply_with,
            metodo_origen="solicitarAccionesCorrectivas()",
            caso_uso=caso_uso,
        )
        self.emitir_acl(msg, trace)
        return reply_with


class SMAMonitoreoBazurto:
    """<<organization>> SMAMonitoreoBazurto que orquesta los 2 Casos de Uso."""

    def __init__(self, db_path: str = "bazurto_sma.db") -> None:
        self.objetivo = "ReducirRiesgoAmbientalBazurto"
        self.politica = "PriorizacionCoordinada"
        self.parametros = UmbralesConfigurables()
        self.db = BazurtoDatabase(db_path)
        self.entorno = MercadoBazurto(self.db)
        self.sensor_residuos = AgenteSensorResiduos(self.db, self.entorno, self.parametros)
        self.sensor_aire = AgenteSensorAire(self.db, self.entorno, self.parametros)
        self.coordinador = AgenteCoordinador(self.db, self.entorno, self.parametros)
        self.alertas = AgenteAlertas(self.db, self.entorno)
        self.supervisor = AgenteSupervisor(self.db)

    def ejecutar_caso_uso_1(
        self,
        zona_id: str = "zona_3",
        forzar_duplicada: bool = False,
        comunidad_confirma: Optional[bool] = None,
        image_base64: Optional[str] = None,
        preset_imagen: Optional[str] = None,
        esperar_confirmacion_interactiva: bool = False,
        contenedor_id: Optional[str] = None,
        gemini_api_key: Optional[str] = None,
    ) -> dict[str, Any]:
        """Ejecuta CU-01 completo o en espera de confirmación comunitaria interactiva."""
        if comunidad_confirma is not None:
            self.db.update_zona(zona_id, comunidad_confirma=comunidad_confirma)

        trace: list[dict[str, Any]] = []
        conv_id = f"cu01-{zona_id}-{len(self.db.list_eventos(limit=100)) + 1:03d}"

        # 1. Monitoreo de Residuos (sensor + cámara real con analizarImagenes)
        nivel = self.sensor_residuos.medirNivelLlenadoContenedores(zona_id, trace)
        vision = self.sensor_residuos.analizarImagenes(
            zona_id,
            nivel,
            trace,
            image_base64=image_base64,
            preset_imagen=preset_imagen,
            actualizar_entorno=bool(image_base64 or preset_imagen),
            gemini_api_key=gemini_api_key,
        )
        if vision.get("contenedor_detectado", True) and contenedor_id:
            cont = self.db.get_contenedor(contenedor_id)
            if cont and cont["zona_id"] == zona_id:
                self.db.update_contenedor_vision(
                    contenedor_id=contenedor_id,
                    nivel_llenado=float(vision["nivel_llenado_visual"]),
                    estado_visual=str(vision["estado_visual"]),
                    bolsas_suelo=int(vision["bolsas_en_suelo"]),
                    ultima_imagen=str(vision["fuente_imagen"]),
                )
        nivel_efectivo = float(vision["nivel_usado"])
        estado_interno = self.sensor_residuos.evaluarPersistencia(
            zona_id,
            nivel_efectivo,
            trace,
            estado_visual=str(vision["estado_visual"]),
            bolsas_suelo=int(vision["bolsas_en_suelo"]),
        )
        evento_id = self.sensor_residuos.publicarEventoRiesgo(zona_id, estado_interno, conv_id, "CU-01", trace)

        # 2. Monitoreo de Aire
        medicion = self.sensor_aire.medirGases(zona_id, trace)
        self.sensor_aire.registrarMedicion(zona_id, medicion, trace)
        aumento = self.sensor_aire.detectarAumentoProgresivo(zona_id, trace)
        self.sensor_aire.publicarMedicion(zona_id, medicion, aumento, conv_id, "CU-01", trace)

        # 3. Coordinación y Priorización
        self.coordinador.consultarEventos(zona_id, trace)
        riesgo = self.coordinador.calcularRiesgo(zona_id, True, trace)
        ranking = self.coordinador.priorizarZonas(zona_id, riesgo, trace)
        self.db.update_evento_riesgo(evento_id, riesgo, 1, atendido=True)
        reply_with = self.coordinador.delegarAlerta(evento_id, zona_id, riesgo, conv_id, "CU-01", False, trace)

        # 4. Emisión de Alerta y Confirmación
        nivel_alerta = "ALTO" if riesgo >= self.parametros.riesgo_alerta_umbral else "MODERADO"
        acepta = self.alertas.recibirSolicitudAlerta(zona_id, forzar_duplicada, reply_with, conv_id, "CU-01", trace)

        resultado = "REFUSE"
        alerta_id = None
        if acepta:
            self.alertas.emitirAviso(zona_id, trace)
            if esperar_confirmacion_interactiva:
                alerta_id = self.db.insert_alerta(
                    evento_id,
                    zona_id,
                    nivel_alerta,
                    "PENDIENTE_COMUNIDAD",
                    False,
                    f"Aviso #{evento_id} emitido a líderes de {zona_id}. Esperando respuesta en Panel de Comunidad.",
                )
                trace.append(
                    {
                        "tipo": "METODO",
                        "agente": "AgenteAlertas",
                        "metodo": "gestionarConfirmacion()",
                        "detalle": (
                            f"Alerta #{alerta_id} publicada en Panel de Comunidad ({zona_id}); "
                            f"esperando ACK o timeout para responder reply-with={reply_with}"
                        ),
                    }
                )
                resultado = "PENDIENTE_COMUNIDAD"
            else:
                confirma = self.alertas.gestionarConfirmacion(zona_id, trace)
                if confirma:
                    alerta_id = self.alertas.generarReporteConfirmacion(
                        evento_id, zona_id, nivel_alerta, reply_with, conv_id, "CU-01", trace
                    )
                    resultado = "INFORM-DONE"
                else:
                    alerta_id = self.alertas.generarReporteSinConfirmacion(
                        evento_id, zona_id, nivel_alerta, reply_with, conv_id, "CU-01", trace
                    )
                    resultado = "FAILURE"

        return {
            "caso_uso": "CU-01",
            "conversation_id": conv_id,
            "zona_id": zona_id,
            "riesgo": riesgo,
            "ranking": ranking,
            "resultado_acl": resultado,
            "evento_id": evento_id,
            "alerta_id": alerta_id,
            "vision": vision,
            "traza": trace,
        }

    def responder_alerta_comunidad(self, alerta_id: int, confirmar: bool) -> dict[str, Any]:
        """Procesa desde el Panel de Comunidad la respuesta (ACK o Sin Confirmación) de una alerta."""
        alerta = self.db.get_alerta_by_id(alerta_id)
        if not alerta:
            raise ValueError(f"Alerta #{alerta_id} no encontrada")

        zona_id = str(alerta["zona_id"])
        evento_id = int(alerta["evento_id"])
        nivel_alerta = str(alerta["nivel"])
        self.db.update_zona(zona_id, comunidad_confirma=confirmar)

        trace: list[dict[str, Any]] = []
        conv_id = f"cu01-{zona_id}-ack-{alerta_id:03d}"
        reply_with = f"req-alerta-{evento_id}"

        confirma = self.alertas.gestionarConfirmacion(zona_id, trace)
        if confirma:
            self.alertas.generarReporteConfirmacion(
                evento_id,
                zona_id,
                nivel_alerta,
                reply_with,
                conv_id,
                "CU-01",
                trace,
                existing_alerta_id=alerta_id,
            )
            resultado = "INFORM-DONE"
        else:
            self.alertas.generarReporteSinConfirmacion(
                evento_id,
                zona_id,
                nivel_alerta,
                reply_with,
                conv_id,
                "CU-01",
                trace,
                existing_alerta_id=alerta_id,
            )
            resultado = "FAILURE"

        return {
            "caso_uso": "CU-01",
            "conversation_id": conv_id,
            "zona_id": zona_id,
            "alerta_id": alerta_id,
            "resultado_acl": resultado,
            "confirmada_comunidad": confirma,
            "traza": trace,
        }

    def ejecutar_caso_uso_2(
        self,
        zona_id: str = "zona_3",
        simular_sin_confirmacion: Optional[bool] = None,
        simular_sensor_caido: Optional[bool] = None,
    ) -> dict[str, Any]:
        """Ejecuta CU-02 completo: Supervision -> Auditoria QUERY-IF -> Escalamiento o Fallo."""
        if simular_sin_confirmacion is not None:
            self.db.update_zona(zona_id, comunidad_confirma=not simular_sin_confirmacion)
        if simular_sensor_caido is not None:
            self.db.update_zona(zona_id, sensor_aire_activo=not simular_sensor_caido)

        trace: list[dict[str, Any]] = []
        conv_id = f"cu02-{zona_id}-{len(self.db.list_incidencias(limit=100)) + 1:03d}"

        # Asegurar un evento previo sobre el cual auditar
        evento = self.supervisor.verificarAtencionEventos(zona_id, trace)
        if not evento:
            self.ejecutar_caso_uso_1(zona_id=zona_id)
            evento = self.supervisor.verificarAtencionEventos(zona_id, trace)
        evento_id = int(evento["id"]) if evento else 1

        self.supervisor.supervisarAgentes(trace)

        # 1. QUERY-IF a AgenteCoordinador
        q_coord = ACLMessage(
            performative="QUERY-IF",
            sender="AgenteSupervisor",
            receiver="AgenteCoordinador",
            content={"atendido_evento": evento_id, "zona": zona_id},
            protocol="FIPA-Query",
            conversation_id=conv_id,
            reply_with=f"q-coord-{evento_id}",
            metodo_origen="verificarAtencionEventos()",
            caso_uso="CU-02",
        )
        self.supervisor.emitir_acl(q_coord, trace)
        self.coordinador.emitir_acl(
            ACLMessage(
                performative="CONFIRM",
                sender="AgenteCoordinador",
                receiver="AgenteSupervisor",
                content={"atendido_evento": evento_id, "alerta_delegada": True},
                protocol="FIPA-Query",
                conversation_id=conv_id,
                in_reply_to=q_coord.reply_with,
                metodo_origen="consultarEventos()",
                caso_uso="CU-02",
            ),
            trace,
        )

        # 2. QUERY-IF a AgenteAlertas (Confirmacion comunitaria)
        q_alerta = ACLMessage(
            performative="QUERY-IF",
            sender="AgenteSupervisor",
            receiver="AgenteAlertas",
            content={"alerta_confirmada_por_comunidad": zona_id, "evento_id": evento_id},
            protocol="FIPA-Query",
            conversation_id=conv_id,
            reply_with=f"q-alerta-{evento_id}",
            metodo_origen="verificarAtencionEventos()",
            caso_uso="CU-02",
        )
        self.supervisor.emitir_acl(q_alerta, trace)

        zona_datos = self.entorno.leer_atributos_zona(zona_id)
        alerta_confirmada = bool(zona_datos["comunidad_confirma"])
        incidencias_creadas = []

        if alerta_confirmada:
            self.alertas.emitir_acl(
                ACLMessage(
                    performative="CONFIRM",
                    sender="AgenteAlertas",
                    receiver="AgenteSupervisor",
                    content={"reporteConfirmacion": zona_id, "evento_id": evento_id},
                    protocol="FIPA-Query",
                    conversation_id=conv_id,
                    in_reply_to=q_alerta.reply_with,
                    metodo_origen="gestionarConfirmacion()",
                    caso_uso="CU-02",
                ),
                trace,
            )
        else:
            self.alertas.emitir_acl(
                ACLMessage(
                    performative="DISCONFIRM",
                    sender="AgenteAlertas",
                    receiver="AgenteSupervisor",
                    content={"reporteSinConfirmacion": zona_id, "evento_id": evento_id},
                    protocol="FIPA-Query",
                    conversation_id=conv_id,
                    in_reply_to=q_alerta.reply_with,
                    metodo_origen="generarReporteSinConfirmacion()",
                    caso_uso="CU-02",
                ),
                trace,
            )
            inc_id = self.supervisor.registrarIncidencias(
                "AgenteAlertas",
                zona_id,
                f"Alerta del evento #{evento_id} sin confirmacion comunitaria",
                "Escalamiento y reintento de emision de alerta",
                trace,
            )
            incidencias_creadas.append(inc_id)
            req_id = self.supervisor.solicitarAccionesCorrectivas(
                "escalar_alerta_reintento", zona_id, conv_id, "CU-02", trace
            )
            self.coordinador.emitir_acl(
                ACLMessage(
                    performative="AGREE",
                    sender="AgenteCoordinador",
                    receiver="AgenteSupervisor",
                    content={"accion_correctiva": "escalar_alerta_reintento", "zona": zona_id},
                    protocol="FIPA-Request",
                    conversation_id=conv_id,
                    in_reply_to=req_id,
                    metodo_origen="delegarAlerta()",
                    caso_uso="CU-02",
                ),
                trace,
            )
            self.coordinador.delegarAlerta(evento_id, zona_id, 0.90, conv_id, "CU-02", True, trace)

        # 3. QUERY-IF a AgenteSensorAire (Salud del sensor y Timeout)
        q_sensor = ACLMessage(
            performative="QUERY-IF",
            sender="AgenteSupervisor",
            receiver="AgenteSensorAire",
            content={"estado_activo": "AgenteSensorAire", "zona": zona_id},
            protocol="FIPA-Query",
            conversation_id=conv_id,
            reply_with=f"q-sensor-{evento_id}",
            reply_by="5s",
            metodo_origen="supervisarAgentes()",
            caso_uso="CU-02",
        )
        self.supervisor.emitir_acl(q_sensor, trace)

        sensor_ok = bool(zona_datos["sensor_aire_activo"])
        riesgo_recalculado = None
        if sensor_ok:
            self.sensor_aire.emitir_acl(
                ACLMessage(
                    performative="CONFIRM",
                    sender="AgenteSensorAire",
                    receiver="AgenteSupervisor",
                    content={"estado_activo": True, "zona": zona_id},
                    protocol="FIPA-Query",
                    conversation_id=conv_id,
                    in_reply_to=q_sensor.reply_with,
                    metodo_origen="medirGases()",
                    caso_uso="CU-02",
                ),
                trace,
            )
        else:
            trace.append(
                {
                    "tipo": "TIMEOUT",
                    "agente": "AgenteSensorAire",
                    "metodo": "reply-by vencido (5s)",
                    "detalle": f"AgenteSensorAire en {zona_id} no respondio dentro del tiempo limite",
                }
            )
            inc_id = self.supervisor.registrarIncidencias(
                "AgenteSensorAire",
                zona_id,
                f"Timeout de AgenteSensorAire en {zona_id} (reply-by vencido)",
                "Recalculo de riesgo usando solo AgenteSensorResiduos",
                trace,
            )
            incidencias_creadas.append(inc_id)
            self.supervisor.notificarFallos("AgenteSensorAire", zona_id, conv_id, "CU-02", trace)
            req_rec = self.supervisor.solicitarAccionesCorrectivas(
                "recalcular_riesgo_sin_sensor_aire", zona_id, conv_id, "CU-02", trace
            )
            self.coordinador.emitir_acl(
                ACLMessage(
                    performative="AGREE",
                    sender="AgenteCoordinador",
                    receiver="AgenteSupervisor",
                    content={"accion_correctiva": "recalcular_riesgo", "zona": zona_id},
                    protocol="FIPA-Request",
                    conversation_id=conv_id,
                    in_reply_to=req_rec,
                    metodo_origen="calcularRiesgo()",
                    caso_uso="CU-02",
                ),
                trace,
            )
            riesgo_recalculado = self.coordinador.calcularRiesgo(zona_id, False, trace)
            self.coordinador.priorizarZonas(zona_id, riesgo_recalculado, trace)

        return {
            "caso_uso": "CU-02",
            "conversation_id": conv_id,
            "zona_id": zona_id,
            "alerta_confirmada": alerta_confirmada,
            "sensor_aire_activo": sensor_ok,
            "riesgo_recalculado": riesgo_recalculado,
            "incidencias_creadas": incidencias_creadas,
            "traza": trace,
        }

    def ejecutar_inspeccion_coordinada_camaras(
        self,
        gemini_api_key: Optional[str] = None,
        comunidad_confirma: Optional[bool] = None,
        esperar_confirmacion_interactiva: bool = True,
    ) -> dict[str, Any]:
        """Orden iniciada por AgenteCoordinador: consulta cámaras de todas las zonas, prioriza y delega."""
        trace: list[dict[str, Any]] = []
        conv_id = f"cu-cam-{len(self.db.list_eventos(limit=100)) + 1:03d}"
        zonas = self.db.list_zonas()
        if not zonas:
            raise ValueError("No hay zonas registradas en MercadoBazurto.")

        inspecciones: list[dict[str, Any]] = []
        riesgos_mapa: dict[str, float] = {}
        eventos_mapa: dict[str, int] = {}

        for z in zonas:
            zid = z["zona_id"]
            if comunidad_confirma is not None:
                self.db.update_zona(zid, comunidad_confirma=comunidad_confirma)
                z = self.db.get_zona(zid) or z

            conts = self.db.list_contenedores(zid)
            if conts:
                cont = conts[0]
            else:
                cont = self.db.create_contenedor(
                    contenedor_id=f"cont_{zid}_01",
                    zona_id=zid,
                    codigo=f"CONT-{zid.upper()}-01",
                    tipo="Contenedor Municipal 1100L",
                    nivel_llenado=float(z["nivel_llenado_contenedores"]),
                )

            # 1. AgenteCoordinador consulta eventos y ordena revisar cámara de la zona
            self.coordinador.consultarEventos(zid, trace)
            req_cam_id = f"qry-cam-{zid}-{conv_id}"
            self.coordinador.emitir_acl(
                ACLMessage(
                    performative="QUERY-REF",
                    sender="AgenteCoordinador",
                    receiver="AgenteSensorResiduos",
                    content={
                        "accion": "revisar_camara_zona",
                        "zona": zid,
                        "contenedor": cont["codigo"],
                        "imagen_asignada": cont.get("ultima_imagen") or "auto",
                    },
                    protocol="FIPA-Query",
                    conversation_id=conv_id,
                    reply_with=req_cam_id,
                    metodo_origen="consultarEventos()",
                    caso_uso="CU-ROL-02",
                ),
                trace,
            )

            req_air_id = f"qry-air-{zid}-{conv_id}"
            self.coordinador.emitir_acl(
                ACLMessage(
                    performative="QUERY-REF",
                    sender="AgenteCoordinador",
                    receiver="AgenteSensorAire",
                    content={"accion": "consultar_gases_zona", "zona": zid},
                    protocol="FIPA-Query",
                    conversation_id=conv_id,
                    reply_with=req_air_id,
                    metodo_origen="consultarEventos()",
                    caso_uso="CU-ROL-02",
                ),
                trace,
            )

            # 2. AgenteSensorResiduos inspecciona la imagen asignada a la cámara del contenedor
            nivel_previo = self.sensor_residuos.medirNivelLlenadoContenedores(zid, trace)
            img_custom = cont.get("imagen_custom_base64")
            preset_asignado = None if img_custom else (
                cont.get("ultima_imagen")
                if cont.get("ultima_imagen")
                in ("contenedor_limpio.png", "contenedor_medio.png", "contenedor_critico.png")
                else self.sensor_residuos._preset_para_nivel(nivel_previo)
            )
            vision = self.sensor_residuos.analizarImagenes(
                zona_id=zid,
                nivel=nivel_previo,
                trace=trace,
                image_base64=img_custom,
                preset_imagen=preset_asignado,
                actualizar_entorno=True,
                gemini_api_key=gemini_api_key,
            )
            detectado = bool(vision.get("contenedor_detectado", True))
            if detectado:
                cont = self.db.update_contenedor_vision(
                    contenedor_id=cont["contenedor_id"],
                    nivel_llenado=float(vision["nivel_llenado_visual"]),
                    estado_visual=str(vision["estado_visual"]),
                    bolsas_suelo=int(vision["bolsas_en_suelo"]),
                    ultima_imagen=str(vision["fuente_imagen"]),
                    actualizar_custom=False,
                )

            self.db.insert_historial_vision(
                zona_id=zid,
                zona_nombre=z["nombre"],
                contenedor_id=cont["contenedor_id"],
                contenedor_codigo=cont["codigo"],
                fuente_imagen=str(vision["fuente_imagen"]),
                contenedor_detectado=detectado,
                nivel_llenado_visual=float(vision["nivel_llenado_visual"]),
                bolsas_en_suelo=int(vision["bolsas_en_suelo"]),
                desbordamiento=bool(vision["desbordamiento"]),
                estado_visual=str(vision["estado_visual"]),
                confianza=float(vision["confianza"]),
                annotated_image_base64=str(vision["annotated_image_base64"]),
                motor_vision=str(vision.get("motor_vision", "Motor Matemático HSV Local (100% Offline)")),
                explicacion_ia=str(vision.get("explicacion_ia", "")),
            )

            nivel_efectivo = float(vision["nivel_usado"])
            estado_interno = self.sensor_residuos.evaluarPersistencia(
                zid,
                nivel_efectivo,
                trace,
                estado_visual=str(vision["estado_visual"]),
                bolsas_suelo=int(vision["bolsas_en_suelo"]),
            )
            evento_id = self.db.insert_evento(
                zid,
                "residuos",
                (
                    f"Camara {cont['codigo']} ({vision['fuente_imagen']}): {vision['estado_visual']} "
                    f"nivel={vision['nivel_llenado_visual']}%, bolsas_suelo={vision['bolsas_en_suelo']}"
                ),
                0.0,
            )
            eventos_mapa[zid] = evento_id

            # Respuesta INFORM del Sensor de Residuos al Coordinador
            self.sensor_residuos.emitir_acl(
                ACLMessage(
                    performative="INFORM",
                    sender="AgenteSensorResiduos",
                    receiver="AgenteCoordinador",
                    content={
                        "evento_id": evento_id,
                        "zona": zid,
                        "contenedor": cont["codigo"],
                        "contenedor_detectado": detectado,
                        "llenado_visual": vision["nivel_llenado_visual"],
                        "bolsas_en_suelo": vision["bolsas_en_suelo"],
                        "estado_visual": vision["estado_visual"],
                        "motor_vision": vision.get("motor_vision", "HSV Local"),
                    },
                    protocol="FIPA-Query",
                    conversation_id=conv_id,
                    in_reply_to=req_cam_id,
                    metodo_origen="publicarEventoRiesgo()" if vision["desbordamiento"] else "analizarImagenes()",
                    caso_uso="CU-ROL-02",
                ),
                trace,
            )

            # 3. AgenteSensorAire reporta gases de la zona
            medicion = self.sensor_aire.medirGases(zid, trace)
            self.sensor_aire.registrarMedicion(zid, medicion, trace)
            aumento = self.sensor_aire.detectarAumentoProgresivo(zid, trace)
            self.sensor_aire.emitir_acl(
                ACLMessage(
                    performative="INFORM",
                    sender="AgenteSensorAire",
                    receiver="AgenteCoordinador",
                    content={
                        "zona": zid,
                        "gases_ppm": medicion["concentracionGases"],
                        "aumento_progresivo": aumento,
                    },
                    protocol="FIPA-Query",
                    conversation_id=conv_id,
                    in_reply_to=req_air_id,
                    metodo_origen="publicarMedicion()",
                    caso_uso="CU-ROL-02",
                ),
                trace,
            )

            # 4. Coordinador calcula utilidad/riesgo individual de la zona
            riesgo_z = self.coordinador.calcularRiesgo(zid, bool(z["sensor_aire_activo"]), trace)
            riesgos_mapa[zid] = riesgo_z
            inspecciones.append(
                {
                    "zona_id": zid,
                    "zona_nombre": z["nombre"],
                    "contenedor_id": cont["contenedor_id"],
                    "contenedor_codigo": cont["codigo"],
                    "fuente_imagen": vision["fuente_imagen"],
                    "contenedor_detectado": detectado,
                    "nivel_llenado_visual": float(vision["nivel_llenado_visual"]),
                    "bolsas_en_suelo": int(vision["bolsas_en_suelo"]),
                    "desbordamiento": bool(vision["desbordamiento"]),
                    "estado_visual": str(vision["estado_visual"]),
                    "confianza": float(vision["confianza"]),
                    "motor_vision": str(vision.get("motor_vision", "Motor Matemático HSV Local (100% Offline)")),
                    "explicacion_ia": str(vision.get("explicacion_ia", "")),
                    "telemetria_pixeles": vision.get("telemetria_pixeles"),
                    "annotated_image_base64": vision["annotated_image_base64"],
                    "concentracion_gases": float(medicion["concentracionGases"]),
                    "riesgo": riesgo_z,
                    "estado_interno_tiempo": estado_interno["tiempo_sobre_limite"],
                }
            )

        # 5. Priorización global de todas las zonas inspeccionadas
        inspecciones.sort(key=lambda item: item["riesgo"], reverse=True)
        for pos, item in enumerate(inspecciones, start=1):
            item["posicion"] = pos
            self.db.update_evento_riesgo(
                eventos_mapa[item["zona_id"]],
                item["riesgo"],
                pos,
                atendido=(pos == 1),
            )

        zona_top = inspecciones[0]
        ranking_simple = [{"zona_id": item["zona_id"], "riesgo": item["riesgo"]} for item in inspecciones]
        trace.append(
            {
                "tipo": "METODO",
                "agente": "AgenteCoordinador",
                "metodo": "priorizarZonas()",
                "detalle": f"Priorización coordinada de {len(inspecciones)} zonas tras revisar cámaras: {ranking_simple}",
            }
        )

        # 6. Delegación de alerta para la zona prioritaria (#1)
        top_zid = str(zona_top["zona_id"])
        top_riesgo = float(zona_top["riesgo"])
        top_ev_id = eventos_mapa[top_zid]
        reply_with = self.coordinador.delegarAlerta(
            top_ev_id, top_zid, top_riesgo, conv_id, "CU-ROL-02", False, trace
        )
        nivel_alerta = "ALTO" if top_riesgo >= self.parametros.riesgo_alerta_umbral else "MODERADO"
        acepta = self.alertas.recibirSolicitudAlerta(top_zid, False, reply_with, conv_id, "CU-ROL-02", trace)
        resultado_acl = "REFUSE"
        alerta_id = None
        if acepta:
            self.alertas.emitirAviso(top_zid, trace)
            if esperar_confirmacion_interactiva and comunidad_confirma is None:
                alerta_id = self.db.insert_alerta(
                    top_ev_id,
                    top_zid,
                    nivel_alerta,
                    "PENDIENTE_COMUNIDAD",
                    False,
                    (
                        f"Inspección coordinada de cámaras (#1 {zona_top['zona_nombre']}: "
                        f"{zona_top['nivel_llenado_visual']}% / {zona_top['bolsas_en_suelo']} bolsas). Esperando ACK."
                    ),
                )
                resultado_acl = "PENDIENTE_COMUNIDAD"
            else:
                confirma = self.alertas.gestionarConfirmacion(top_zid, trace)
                if confirma:
                    alerta_id = self.alertas.generarReporteConfirmacion(
                        top_ev_id, top_zid, nivel_alerta, reply_with, conv_id, "CU-ROL-02", trace
                    )
                    resultado_acl = "INFORM-DONE"
                else:
                    alerta_id = self.alertas.generarReporteSinConfirmacion(
                        top_ev_id, top_zid, nivel_alerta, reply_with, conv_id, "CU-ROL-02", trace
                    )
                    resultado_acl = "FAILURE"

        return {
            "caso_uso": "CU-ROL-02",
            "rol": "Coordinador",
            "conversation_id": conv_id,
            "zona_prioritaria": zona_top,
            "priorizacion_zonas": inspecciones,
            "inspecciones_camaras": inspecciones,
            "alerta_id": alerta_id,
            "resultado_acl": resultado_acl,
            "traza": trace,
        }

    def ejecutar_caso_uso_rol(
        self,
        cu_id: str,
        zona_id: str = "zona_3",
        gemini_api_key: Optional[str] = None,
        comunidad_confirma: Optional[bool] = None,
        esperar_confirmacion_interactiva: bool = True,
        simular_sin_confirmacion: Optional[bool] = None,
        simular_sensor_caido: Optional[bool] = None,
    ) -> dict[str, Any]:
        """Ejecuta individualmente cualquiera de los 4 Casos de Uso desglosados por Rol (<<role>>)."""
        code = cu_id.strip().upper()
        if code == "CU-ROL-01":
            trace: list[dict[str, Any]] = []
            conv_id = f"curol01-{zona_id}-{len(self.db.list_eventos(limit=100)) + 1:03d}"
            conts = self.db.list_contenedores(zona_id)
            cont = conts[0] if conts else None
            nivel = self.sensor_residuos.medirNivelLlenadoContenedores(zona_id, trace)
            img_custom = cont.get("imagen_custom_base64") if cont else None
            preset = None if img_custom else (cont.get("ultima_imagen") if cont else self.sensor_residuos._preset_para_nivel(nivel))
            vision = self.sensor_residuos.analizarImagenes(
                zona_id,
                nivel,
                trace,
                image_base64=img_custom,
                preset_imagen=preset,
                actualizar_entorno=True,
                gemini_api_key=gemini_api_key,
            )
            estado = self.sensor_residuos.evaluarPersistencia(
                zona_id,
                float(vision["nivel_usado"]),
                trace,
                estado_visual=str(vision["estado_visual"]),
                bolsas_suelo=int(vision["bolsas_en_suelo"]),
            )
            ev_id = self.sensor_residuos.publicarEventoRiesgo(zona_id, estado, conv_id, "CU-ROL-01", trace)
            med = self.sensor_aire.medirGases(zona_id, trace)
            self.sensor_aire.registrarMedicion(zona_id, med, trace)
            aum = self.sensor_aire.detectarAumentoProgresivo(zona_id, trace)
            self.sensor_aire.publicarMedicion(zona_id, med, aum, conv_id, "CU-ROL-01", trace)
            return {
                "caso_uso": "CU-ROL-01",
                "rol": "MonitorCondicionesAmbientales",
                "conversation_id": conv_id,
                "zona_id": zona_id,
                "evento_id": ev_id,
                "vision": vision,
                "medicion_aire": med,
                "resultado_acl": "INFORM",
                "traza": trace,
            }

        if code == "CU-ROL-02":
            return self.ejecutar_inspeccion_coordinada_camaras(
                gemini_api_key=gemini_api_key,
                comunidad_confirma=comunidad_confirma,
                esperar_confirmacion_interactiva=esperar_confirmacion_interactiva,
            )

        if code == "CU-ROL-03":
            if comunidad_confirma is not None:
                self.db.update_zona(zona_id, comunidad_confirma=comunidad_confirma)
            trace = []
            conv_id = f"curol03-{zona_id}-{len(self.db.list_alertas(limit=100)) + 1:03d}"
            ev = self.db.get_latest_evento(zona_id)
            ev_id = int(ev["id"]) if ev else self.db.insert_evento(zona_id, "residuos", f"Solicitud de emisión comunitaria en {zona_id}", 0.85)
            z = self.db.get_zona(zona_id) or {}
            riesgo = round(float(z.get("nivel_llenado_contenedores", 85.0)) / 100.0, 2)
            nivel_alerta = "ALTO" if riesgo >= self.parametros.riesgo_alerta_umbral else "MODERADO"
            reply_with = f"req-rol03-{ev_id}"
            acepta = self.alertas.recibirSolicitudAlerta(zona_id, False, reply_with, conv_id, "CU-ROL-03", trace)
            resultado = "REFUSE"
            alerta_id = None
            if acepta:
                self.alertas.emitirAviso(zona_id, trace)
                confirma = self.alertas.gestionarConfirmacion(zona_id, trace)
                if confirma:
                    alerta_id = self.alertas.generarReporteConfirmacion(
                        ev_id, zona_id, nivel_alerta, reply_with, conv_id, "CU-ROL-03", trace
                    )
                    resultado = "INFORM-DONE"
                else:
                    alerta_id = self.alertas.generarReporteSinConfirmacion(
                        ev_id, zona_id, nivel_alerta, reply_with, conv_id, "CU-ROL-03", trace
                    )
                    resultado = "FAILURE"
            return {
                "caso_uso": "CU-ROL-03",
                "rol": "EmisorAlertas",
                "conversation_id": conv_id,
                "zona_id": zona_id,
                "alerta_id": alerta_id,
                "resultado_acl": resultado,
                "traza": trace,
            }

        if code == "CU-ROL-04":
            res = self.ejecutar_caso_uso_2(
                zona_id=zona_id,
                simular_sin_confirmacion=simular_sin_confirmacion,
                simular_sensor_caido=simular_sensor_caido,
            )
            res["caso_uso"] = "CU-ROL-04"
            res["rol"] = "Supervisor"
            res["resultado_acl"] = "FAILURE" if not res["alerta_confirmada"] else "CONFIRM"
            return res

        raise ValueError(f"Caso de uso por rol desconocido: {cu_id}")
