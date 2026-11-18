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

                CREATE TABLE IF NOT EXISTS contenedores_zona (
                    contenedor_id TEXT PRIMARY KEY,
                    zona_id TEXT NOT NULL,
                    codigo TEXT NOT NULL,
                    tipo TEXT NOT NULL,
                    nivel_llenado REAL NOT NULL DEFAULT 0.0,
                    estado_visual TEXT NOT NULL DEFAULT 'contenedor_estable',
                    bolsas_suelo INTEGER NOT NULL DEFAULT 0,
                    ultima_imagen TEXT,
                    imagen_custom_base64 TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS historial_vision (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    zona_id TEXT NOT NULL,
                    zona_nombre TEXT NOT NULL,
                    contenedor_id TEXT NOT NULL,
                    contenedor_codigo TEXT NOT NULL,
                    fuente_imagen TEXT NOT NULL,
                    contenedor_detectado INTEGER NOT NULL,
                    nivel_llenado_visual REAL NOT NULL,
                    bolsas_en_suelo INTEGER NOT NULL,
                    desbordamiento INTEGER NOT NULL,
                    estado_visual TEXT NOT NULL,
                    confianza REAL NOT NULL,
                    motor_vision TEXT NOT NULL DEFAULT 'Motor Matemático HSV Local (100% Offline)',
                    explicacion_ia TEXT NOT NULL DEFAULT '',
                    annotated_image_base64 TEXT NOT NULL,
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
            cont_cols = {
                row[1]
                for row in conn.execute("PRAGMA table_info(contenedores_zona)").fetchall()
            }
            if "imagen_custom_base64" not in cont_cols:
                conn.execute("ALTER TABLE contenedores_zona ADD COLUMN imagen_custom_base64 TEXT")
            hist_cols = {
                row[1]
                for row in conn.execute("PRAGMA table_info(historial_vision)").fetchall()
            }
            if "motor_vision" not in hist_cols:
                conn.execute(
                    "ALTER TABLE historial_vision ADD COLUMN motor_vision TEXT NOT NULL DEFAULT 'Motor Matemático HSV Local (100% Offline)'"
                )
            if "explicacion_ia" not in hist_cols:
                conn.execute("ALTER TABLE historial_vision ADD COLUMN explicacion_ia TEXT NOT NULL DEFAULT ''")

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

            cont_count = conn.execute("SELECT COUNT(*) FROM contenedores_zona").fetchone()[0]
            if cont_count == 0:
                default_conts = [
                    ("cont_z3_01", "zona_3", "CONT-Z3-01 (Pescadería Norte)", "Contenedor Verde 1100L", 98.0, "desbordamiento_detectado", 4, "contenedor_critico.png", None, now),
                    ("cont_z3_02", "zona_3", "CONT-Z3-02 (Muelle Central)", "Contenedor Negro 1100L", 94.0, "desbordamiento_detectado", 3, "contenedor_critico.png", None, now),
                    ("cont_z5_01", "zona_5", "CONT-Z5-01 (Verduras Sur)", "Contenedor Gris 1100L", 65.2, "contenedor_estable", 0, "contenedor_medio.png", None, now),
                    ("cont_z2_01", "zona_2", "CONT-Z2-01 (Callejón Carnes)", "Contenedor Verde 1100L", 16.9, "contenedor_estable", 0, "contenedor_limpio.png", None, now),
                ]
                conn.executemany(
                    """
                    INSERT INTO contenedores_zona (
                        contenedor_id, zona_id, codigo, tipo, nivel_llenado,
                        estado_visual, bolsas_suelo, ultima_imagen, imagen_custom_base64, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    default_conts,
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
                "contenedores_zona",
                "historial_vision",
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

    def create_zona(
        self,
        zona_id: str,
        nombre: str,
        nivel_llenado_contenedores: float = 25.0,
        concentracion_gases: float = 450.0,
        temperatura: float = 30.0,
        humedad: float = 72.0,
    ) -> dict[str, Any]:
        clean_id = zona_id.strip().lower().replace(" ", "_")
        if not clean_id or not nombre.strip():
            raise ValueError("El ID y el nombre de la zona son obligatorios.")
        if self.get_zona(clean_id):
            raise ValueError(f"La zona '{clean_id}' ya existe en MercadoBazurto.")
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO zonas_entorno (
                    zona_id, nombre, nivel_llenado_contenedores,
                    concentracion_gases, temperatura, humedad,
                    sensor_aire_activo, comunidad_confirma, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, 1, ?)
                """,
                (
                    clean_id,
                    nombre.strip(),
                    nivel_llenado_contenedores,
                    concentracion_gases,
                    temperatura,
                    humedad,
                    now,
                ),
            )
            default_cont_id = f"cont_{clean_id}_01"
            existing_cont = conn.execute(
                "SELECT 1 FROM contenedores_zona WHERE contenedor_id = ?", (default_cont_id,)
            ).fetchone()
            if not existing_cont:
                default_preset = (
                    "contenedor_critico.png"
                    if nivel_llenado_contenedores >= 80.0
                    else ("contenedor_medio.png" if nivel_llenado_contenedores >= 45.0 else "contenedor_limpio.png")
                )
                conn.execute(
                    """
                    INSERT INTO contenedores_zona (
                        contenedor_id, zona_id, codigo, tipo, nivel_llenado,
                        estado_visual, bolsas_suelo, ultima_imagen, imagen_custom_base64, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'contenedor_estable', 0, ?, NULL, ?)
                    """,
                    (
                        default_cont_id,
                        clean_id,
                        f"CONT-{clean_id.upper()}-01",
                        "Contenedor Municipal 1100L",
                        nivel_llenado_contenedores,
                        default_preset,
                        now,
                    ),
                )
        return self.get_zona(clean_id) or {}

    def list_contenedores(self, zona_id: Optional[str] = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if zona_id:
                rows = conn.execute(
                    "SELECT * FROM contenedores_zona WHERE zona_id = ? ORDER BY contenedor_id",
                    (zona_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM contenedores_zona ORDER BY zona_id, contenedor_id"
                ).fetchall()
            return [dict(r) for r in rows]

    def get_contenedor(self, contenedor_id: str) -> Optional[dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM contenedores_zona WHERE contenedor_id = ?", (contenedor_id,)
            ).fetchone()
            return dict(row) if row else None

    def create_contenedor(
        self,
        contenedor_id: str,
        zona_id: str,
        codigo: str,
        tipo: str = "Contenedor Municipal 1100L",
        nivel_llenado: float = 15.0,
    ) -> dict[str, Any]:
        if not self.get_zona(zona_id):
            raise ValueError(f"Zona desconocida para contenedor: {zona_id}")
        clean_id = contenedor_id.strip().lower().replace(" ", "_")
        if not clean_id or not codigo.strip():
            raise ValueError("El ID y código del contenedor son obligatorios.")
        if self.get_contenedor(clean_id):
            raise ValueError(f"El contenedor '{clean_id}' ya existe.")
        now = datetime.now(timezone.utc).isoformat()
        default_preset = (
            "contenedor_critico.png"
            if nivel_llenado >= 80.0
            else ("contenedor_medio.png" if nivel_llenado >= 45.0 else "contenedor_limpio.png")
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO contenedores_zona (
                    contenedor_id, zona_id, codigo, tipo, nivel_llenado,
                    estado_visual, bolsas_suelo, ultima_imagen, imagen_custom_base64, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'contenedor_estable', 0, ?, NULL, ?)
                """,
                (clean_id, zona_id, codigo.strip(), tipo.strip() or "Contenedor Municipal 1100L", nivel_llenado, default_preset, now),
            )
        return self.get_contenedor(clean_id) or {}

    def asignar_imagen_contenedor(
        self,
        contenedor_id: str,
        preset_imagen: Optional[str] = None,
        imagen_custom_base64: Optional[str] = None,
    ) -> dict[str, Any]:
        """Asigna a un contenedor una de las 3 escenas base o una fotografía subida por el usuario."""
        cont = self.get_contenedor(contenedor_id)
        if not cont:
            raise ValueError(f"Contenedor desconocido: {contenedor_id}")
        now = datetime.now(timezone.utc).isoformat()
        fuente = "imagen_usuario_o_webcam" if imagen_custom_base64 else (preset_imagen or cont.get("ultima_imagen") or "contenedor_limpio.png")
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE contenedores_zona
                SET ultima_imagen = ?, imagen_custom_base64 = ?, updated_at = ?
                WHERE contenedor_id = ?
                """,
                (fuente, imagen_custom_base64 if imagen_custom_base64 else None, now, contenedor_id),
            )
        return self.get_contenedor(contenedor_id) or {}

    def update_contenedor_vision(
        self,
        contenedor_id: str,
        nivel_llenado: float,
        estado_visual: str,
        bolsas_suelo: int,
        ultima_imagen: str,
        imagen_custom_base64: Optional[str] = None,
        actualizar_custom: bool = False,
    ) -> dict[str, Any]:
        cont = self.get_contenedor(contenedor_id)
        if not cont:
            raise ValueError(f"Contenedor desconocido: {contenedor_id}")
        now = datetime.now(timezone.utc).isoformat()
        custom_val = imagen_custom_base64 if actualizar_custom else cont.get("imagen_custom_base64")
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE contenedores_zona
                SET nivel_llenado = ?, estado_visual = ?, bolsas_suelo = ?,
                    ultima_imagen = ?, imagen_custom_base64 = ?, updated_at = ?
                WHERE contenedor_id = ?
                """,
                (nivel_llenado, estado_visual, bolsas_suelo, ultima_imagen, custom_val, now, contenedor_id),
            )
        return self.get_contenedor(contenedor_id) or {}

    def insert_historial_vision(
        self,
        zona_id: str,
        zona_nombre: str,
        contenedor_id: str,
        contenedor_codigo: str,
        fuente_imagen: str,
        contenedor_detectado: bool,
        nivel_llenado_visual: float,
        bolsas_en_suelo: int,
        desbordamiento: bool,
        estado_visual: str,
        confianza: float,
        annotated_image_base64: str,
        motor_vision: str = "Motor Matemático HSV Local (100% Offline)",
        explicacion_ia: str = "",
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO historial_vision (
                    zona_id, zona_nombre, contenedor_id, contenedor_codigo,
                    fuente_imagen, contenedor_detectado, nivel_llenado_visual,
                    bolsas_en_suelo, desbordamiento, estado_visual,
                    confianza, motor_vision, explicacion_ia, annotated_image_base64, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    zona_id,
                    zona_nombre,
                    contenedor_id,
                    contenedor_codigo,
                    fuente_imagen,
                    int(contenedor_detectado),
                    nivel_llenado_visual,
                    bolsas_en_suelo,
                    int(desbordamiento),
                    estado_visual,
                    confianza,
                    motor_vision,
                    explicacion_ia,
                    annotated_image_base64,
                    now,
                ),
            )
            row = conn.execute("SELECT * FROM historial_vision WHERE id = ?", (cur.lastrowid,)).fetchone()
            return dict(row) if row else {}

    def list_historial_vision(self, zona_id: Optional[str] = None, limit: int = 25) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if zona_id:
                rows = conn.execute(
                    "SELECT * FROM historial_vision WHERE zona_id = ? ORDER BY id DESC LIMIT ?",
                    (zona_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM historial_vision ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
