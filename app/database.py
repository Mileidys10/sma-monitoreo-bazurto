"""Capa de persistencia SQLite para el SMA del Mercado de Bazurto."""

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Any, Optional

from app.fipa_acl import ACLMessage


class BazurtoDatabase:
    """Gestiona la persistencia de entorno, modelos internos de agentes, eventos, alertas, incidencias y mensajes FIPA-ACL."""

    def __init__(self, db_path: str | Path = "bazurto_sma.db") -> None:
        self.db_path = Path(db_path)
        self._init_schema()
        self._seed_default_zones()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS zonas_entorno (
                    zona_id TEXT PRIMARY KEY,
                    nombre TEXT NOT NULL,
                    nivel_llenado_contenedores REAL NOT NULL,
                    concentracion_gases REAL NOT NULL,
                    temperatura REAL NOT NULL,
                    humedad REAL NOT NULL,
                    sensor_aire_activo INTEGER NOT NULL DEFAULT 1,
                    comunidad_confirma INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS estado_interno_residuos (
                    zona_id TEXT PRIMARY KEY,
                    nivel REAL NOT NULL,
                    tiempo_sobre_limite INTEGER NOT NULL,
                    ritmo_llenado REAL NOT NULL,
                    ciclos_consecutivos INTEGER NOT NULL,
                    estado_visual TEXT NOT NULL DEFAULT 'contenedor_estable',
                    bolsas_suelo INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS historial_mediciones_aire (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    zona_id TEXT NOT NULL,
                    concentracion_gases REAL NOT NULL,
                    temperatura REAL NOT NULL,
                    humedad REAL NOT NULL,
                    timestamp TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS eventos_riesgo (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    zona_id TEXT NOT NULL,
                    origen TEXT NOT NULL,
                    descripcion TEXT NOT NULL,
                    riesgo_calculado REAL NOT NULL DEFAULT 0.0,
                    prioridad INTEGER NOT NULL DEFAULT 1,
                    atendido INTEGER NOT NULL DEFAULT 0,
                    timestamp TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS alertas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    evento_id INTEGER NOT NULL,
                    zona_id TEXT NOT NULL,
                    nivel TEXT NOT NULL,
                    estado TEXT NOT NULL,
                    confirmada_comunidad INTEGER NOT NULL DEFAULT 0,
                    reporte TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS incidencias_supervisor (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agente_afectado TEXT NOT NULL,
                    zona_id TEXT NOT NULL,
                    descripcion TEXT NOT NULL,
                    accion_correctiva TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS mensajes_acl (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    caso_uso TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    performative TEXT NOT NULL,
                    sender TEXT NOT NULL,
                    receiver TEXT NOT NULL,
                    content_str TEXT NOT NULL,
                    content_json TEXT NOT NULL,
                    acl_sexpr TEXT NOT NULL,
                    ontology TEXT NOT NULL,
                    protocol TEXT NOT NULL,
                    reply_with TEXT,
                    in_reply_to TEXT,
                    metodo_origen TEXT,
                    timestamp TEXT NOT NULL
                );
                """
            )
            cols = {
                row[1]
                for row in conn.execute("PRAGMA table_info(estado_interno_residuos)").fetchall()
            }
            if "estado_visual" not in cols:
                conn.execute(
                    "ALTER TABLE estado_interno_residuos ADD COLUMN estado_visual TEXT NOT NULL DEFAULT 'contenedor_estable'"
                )
            if "bolsas_suelo" not in cols:
                conn.execute(
                    "ALTER TABLE estado_interno_residuos ADD COLUMN bolsas_suelo INTEGER NOT NULL DEFAULT 0"
                )

    def _seed_default_zones(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        defaults = [
            ("zona_3", "Sector Pescaderia y Acopio Central", 92.0, 850.0, 32.0, 78.0, 1, 1),
            ("zona_5", "Sector Verduras y Contenedores Sur", 68.0, 540.0, 30.5, 74.0, 1, 1),
            ("zona_2", "Callejon de Carnes y Carga", 45.0, 410.0, 29.0, 70.0, 1, 1),
        ]
        with self._connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM zonas_entorno").fetchone()[0]
            if count == 0:
                conn.executemany(
                    """
                    INSERT INTO zonas_entorno (
                        zona_id, nombre, nivel_llenado_contenedores,
                        concentracion_gases, temperatura, humedad,
                        sensor_aire_activo, comunidad_confirma, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [(z[0], z[1], z[2], z[3], z[4], z[5], z[6], z[7], now) for z in defaults],
                )
                # Sembrar un historial previo en zona_3 para permitir detectar aumento progresivo desde la primera ejecucion
                conn.executemany(
                    """
                    INSERT INTO historial_mediciones_aire (
                        zona_id, concentracion_gases, temperatura, humedad, timestamp
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    [
                        ("zona_3", 610.0, 30.0, 72.0, now),
                        ("zona_3", 720.0, 31.0, 75.0, now),
                    ],
                )
                # Sembrar estado interno base en zona_3 para demostrar persistencia continua
                conn.execute(
                    """
                    INSERT INTO estado_interno_residuos (
                        zona_id, nivel, tiempo_sobre_limite, ritmo_llenado, ciclos_consecutivos,
                        estado_visual, bolsas_suelo, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("zona_3", 82.0, 30, 8.0, 2, "desbordamiento_detectado", 4, now),
                )

    def reset_all(self) -> None:
        """Restaura la base de datos a su estado inicial limpio."""
        with self._connect() as conn:
            for table in (
                "zonas_entorno",
                "estado_interno_residuos",
                "historial_mediciones_aire",
                "eventos_riesgo",
                "alertas",
                "incidencias_supervisor",
                "mensajes_acl",
            ):
                conn.execute(f"DELETE FROM {table}")
        self._seed_default_zones()

    def get_zona(self, zona_id: str) -> Optional[dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM zonas_entorno WHERE zona_id = ?", (zona_id,)).fetchone()
            return dict(row) if row else None

    def list_zonas(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM zonas_entorno ORDER BY zona_id").fetchall()
            return [dict(r) for r in rows]

    def update_zona(
        self,
        zona_id: str,
        nivel_llenado_contenedores: Optional[float] = None,
        concentracion_gases: Optional[float] = None,
        temperatura: Optional[float] = None,
        humedad: Optional[float] = None,
        sensor_aire_activo: Optional[bool] = None,
        comunidad_confirma: Optional[bool] = None,
    ) -> dict[str, Any]:
        zona = self.get_zona(zona_id)
        if not zona:
            raise ValueError(f"Zona desconocida: {zona_id}")
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE zonas_entorno
                SET nivel_llenado_contenedores = ?,
                    concentracion_gases = ?,
                    temperatura = ?,
                    humedad = ?,
                    sensor_aire_activo = ?,
                    comunidad_confirma = ?,
                    updated_at = ?
                WHERE zona_id = ?
                """,
                (
                    nivel_llenado_contenedores if nivel_llenado_contenedores is not None else zona["nivel_llenado_contenedores"],
                    concentracion_gases if concentracion_gases is not None else zona["concentracion_gases"],
                    temperatura if temperatura is not None else zona["temperatura"],
                    humedad if humedad is not None else zona["humedad"],
                    int(sensor_aire_activo) if sensor_aire_activo is not None else zona["sensor_aire_activo"],
                    int(comunidad_confirma) if comunidad_confirma is not None else zona["comunidad_confirma"],
                    now,
                    zona_id,
                ),
            )
        return self.get_zona(zona_id) or {}

    def get_estado_residuos(self, zona_id: str) -> Optional[dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM estado_interno_residuos WHERE zona_id = ?", (zona_id,)).fetchone()
            return dict(row) if row else None

    def upsert_estado_residuos(
        self,
        zona_id: str,
        nivel: float,
        tiempo_sobre_limite: int,
        ritmo_llenado: float,
        ciclos_consecutivos: int,
        estado_visual: str = "contenedor_estable",
        bolsas_suelo: int = 0,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO estado_interno_residuos (
                    zona_id, nivel, tiempo_sobre_limite, ritmo_llenado, ciclos_consecutivos,
                    estado_visual, bolsas_suelo, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(zona_id) DO UPDATE SET
                    nivel = excluded.nivel,
                    tiempo_sobre_limite = excluded.tiempo_sobre_limite,
                    ritmo_llenado = excluded.ritmo_llenado,
                    ciclos_consecutivos = excluded.ciclos_consecutivos,
                    estado_visual = excluded.estado_visual,
                    bolsas_suelo = excluded.bolsas_suelo,
                    updated_at = excluded.updated_at
                """,
                (
                    zona_id,
                    nivel,
                    tiempo_sobre_limite,
                    ritmo_llenado,
                    ciclos_consecutivos,
                    estado_visual,
                    bolsas_suelo,
                    now,
                ),
            )
        return self.get_estado_residuos(zona_id) or {}

    def list_estados_residuos(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM estado_interno_residuos ORDER BY zona_id").fetchall()
            return [dict(r) for r in rows]

    def insert_medicion_aire(
        self, zona_id: str, concentracion_gases: float, temperatura: float, humedad: float
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO historial_mediciones_aire (
                    zona_id, concentracion_gases, temperatura, humedad, timestamp
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (zona_id, concentracion_gases, temperatura, humedad, now),
            )
            return int(cur.lastrowid or 0)

    def list_historial_aire(self, zona_id: Optional[str] = None, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if zona_id:
                rows = conn.execute(
                    "SELECT * FROM historial_mediciones_aire WHERE zona_id = ? ORDER BY id DESC LIMIT ?",
                    (zona_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM historial_mediciones_aire ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]

    def insert_evento(
        self, zona_id: str, origen: str, descripcion: str, riesgo_calculado: float = 0.0, atendido: bool = False
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO eventos_riesgo (
                    zona_id, origen, descripcion, riesgo_calculado, prioridad, atendido, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (zona_id, origen, descripcion, riesgo_calculado, 1, int(atendido), now),
            )
            return int(cur.lastrowid or 0)

    def update_evento_riesgo(self, evento_id: int, riesgo: float, prioridad: int, atendido: bool) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE eventos_riesgo
                SET riesgo_calculado = ?, prioridad = ?, atendido = ?
                WHERE id = ?
                """,
                (riesgo, prioridad, int(atendido), evento_id),
            )

    def list_eventos(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM eventos_riesgo ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]

    def get_latest_evento(self, zona_id: Optional[str] = None) -> Optional[dict[str, Any]]:
        with self._connect() as conn:
            if zona_id:
                row = conn.execute(
                    "SELECT * FROM eventos_riesgo WHERE zona_id = ? ORDER BY id DESC LIMIT 1",
                    (zona_id,),
                ).fetchone()
            else:
                row = conn.execute("SELECT * FROM eventos_riesgo ORDER BY id DESC LIMIT 1").fetchone()
            return dict(row) if row else None

    def insert_alerta(
        self, evento_id: int, zona_id: str, nivel: str, estado: str, confirmada_comunidad: bool, reporte: str
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO alertas (
                    evento_id, zona_id, nivel, estado, confirmada_comunidad, reporte, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (evento_id, zona_id, nivel, estado, int(confirmada_comunidad), reporte, now),
            )
            return int(cur.lastrowid or 0)

    def get_active_alerta_zona(self, zona_id: str) -> Optional[dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM alertas WHERE zona_id = ? AND estado = 'CONFIRMADA' ORDER BY id DESC LIMIT 1",
                (zona_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_latest_alerta(self, zona_id: Optional[str] = None) -> Optional[dict[str, Any]]:
        with self._connect() as conn:
            if zona_id:
                row = conn.execute(
                    "SELECT * FROM alertas WHERE zona_id = ? ORDER BY id DESC LIMIT 1",
                    (zona_id,),
                ).fetchone()
            else:
                row = conn.execute("SELECT * FROM alertas ORDER BY id DESC LIMIT 1").fetchone()
            return dict(row) if row else None

    def get_alerta_by_id(self, alerta_id: int) -> Optional[dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM alertas WHERE id = ?", (alerta_id,)).fetchone()
            return dict(row) if row else None

    def update_alerta_confirmacion(
        self, alerta_id: int, estado: str, confirmada_comunidad: bool, reporte: str
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE alertas
                SET estado = ?, confirmada_comunidad = ?, reporte = ?, timestamp = ?
                WHERE id = ?
                """,
                (estado, int(confirmada_comunidad), reporte, now, alerta_id),
            )
        alerta = self.get_alerta_by_id(alerta_id)
        if not alerta:
            raise ValueError(f"Alerta #{alerta_id} no encontrada")
        return alerta

    def list_alertas(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM alertas ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]

    def insert_incidencia(self, agente_afectado: str, zona_id: str, descripcion: str, accion_correctiva: str) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO incidencias_supervisor (
                    agente_afectado, zona_id, descripcion, accion_correctiva, timestamp
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (agente_afectado, zona_id, descripcion, accion_correctiva, now),
            )
            return int(cur.lastrowid or 0)

    def list_incidencias(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM incidencias_supervisor ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def save_acl_message(self, msg: ACLMessage) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO mensajes_acl (
                    caso_uso, conversation_id, performative, sender, receiver,
                    content_str, content_json, acl_sexpr, ontology, protocol,
                    reply_with, in_reply_to, metodo_origen, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    msg.caso_uso,
                    msg.conversation_id,
                    msg.performative.upper(),
                    msg.sender,
                    msg.receiver,
                    msg.content_as_sexpr(),
                    msg.to_json(),
                    msg.to_sexpr(),
                    msg.ontology,
                    msg.protocol,
                    msg.reply_with,
                    msg.in_reply_to,
                    msg.metodo_origen,
                    msg.timestamp,
                ),
            )
            return int(cur.lastrowid or 0)

    def list_acl_messages(self, limit: int = 50, caso_uso: Optional[str] = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if caso_uso:
                rows = conn.execute(
                    "SELECT * FROM mensajes_acl WHERE caso_uso = ? ORDER BY id DESC LIMIT ?",
                    (caso_uso, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM mensajes_acl ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
