# SMAMonitoreoBazurto V2 — Sala de Control Multiagente

## 1. ¿Qué es el SMA Bazurto y cuáles son sus 5 agentes?

`SMAMonitoreoBazurto` es un Sistema Multiagente (SMA) de monitoreo ambiental para el Mercado de Bazurto bajo la organización `AmbientalBazurto`, modelado con **MAS-ML** y comunicación **FIPA-ACL**:
1. **`AgenteSensorResiduos`** (*MonitorCondicionesAmbientales*): mide llenado, evalúa persistencia de sobrecarga (`tiempoSobreLimite`, `ritmoLlenado`) y analiza imágenes con `analizarImagenes()`.
2. **`AgenteSensorAire`** (*MonitorCondicionesAmbientales*): mide gases CO₂, temperatura y humedad, registra historial y detecta aumentos progresivos.
3. **`AgenteCoordinador`** (*Coordinador*): consulta eventos de riesgo, calcula el riesgo compuesto, prioriza zonas y delega alertas al emisor.
4. **`AgenteAlertas`** (*EmisorAlertas*): recibe solicitudes de alerta, emite avisos a la comunidad y reporta `INFORM-DONE`, `FAILURE` o `REFUSE`.
5. **`AgenteSupervisor`** (*Supervisor*): audita el cumplimiento mediante `FIPA-Query` (`QUERY-IF` / `CONFIRM` / `DISCONFIRM`), registra incidencias y solicita acciones correctivas.

---

## 2. Motor de ejecución

El backend corre sobre un motor real en **Python** compuesto por:
- **LangGraph (`StateGraph` de 5 nodos)**: implementado en `BazurtoStateGraphRunner` (`app/motor_langgraph.py`) sobre `BazurtoAgentState` con checkpointer `MemorySaver` y transición condicional `decidir_ruta_supervision`.
- **FastAPI + SSE (`EventBus`)**: `app/main.py` ejecuta el bucle autónomo (`LoopAutonomo`) en un hilo de fondo y difunde eventos tipados en tiempo real hacia la Sala de Control vía Server-Sent Events (`/api/stream`).
- **SQLite (`bazurto_sma.db`)**: `app/database.py` persiste zonas, contenedores, historial de visión, estado interno de residuos, historial de gases, eventos de riesgo, alertas, incidencias y mensajes FIPA-ACL.

---

## 3. ¿Qué es real y qué es simulado?

| Componente | Estado | Detalle verificado en el código |
| :--- | :--- | :--- |
| **5 Agentes MAS-ML** | **Real** | Clases y métodos reales ejecutados como nodos de `StateGraph` (`app/models_masml.py`, `app/motor_langgraph.py`). |
| **Grafo LangGraph** | **Real** | `StateGraph(BazurtoAgentState)` compilado con `MemorySaver`, `START`, `END` y aristas condicionales. |
| **Mensajes FIPA-ACL** | **Real** | `ACLMessage` emitidos por los agentes (`INFORM`, `REQUEST`, `AGREE`, `REFUSE`, `INFORM-DONE`, `FAILURE`, `QUERY-IF`, `CONFIRM`, `DISCONFIRM`) y persistidos en SQLite. |
| **Riesgo y alertas** | **Real** | `calcularRiesgo()`, `priorizarZonas()`, alertas e incidencias reales calculadas y almacenadas en `bazurto_sma.db`. |
| **Análisis de imagen** | **Real** | Procesamiento real con `analizar_imagen_contenedor()` (`app/vision_analyzer.py`): motor HSV local píxel a píxel o IA Gemini si hay clave. |
| **Sensores del entorno** | **Simulado** | `SimuladorEntorno` (`app/autonomo.py`) evoluciona llenado, gases, temperatura y humedad en `MercadoBazurto`. El llenado solo baja cuando un camión recolector llega, unas rondas después de una alerta confirmada. |
| **Respuesta comunitaria** | **Simulado** | En las rondas autónomas (`LoopAutonomo`), la comunidad confirma con probabilidad `prob_confirma = 0.7` (70%). |
| **Imágenes iniciales** | **De muestra** | En la Sala de Control la cámara analiza una de 3 imágenes de muestra (`contenedor_limpio.png`, `contenedor_medio.png`, `contenedor_critico.png`) elegida según el nivel simulado; la imagen no modifica el entorno. En `/documentacion` se pueden subir fotos o usar la webcam, y ahí la foto sí fija el nivel de la zona. |

### ¿Cuándo se genera una alerta? (regla del CU-01)

1. `AgenteSensorResiduos` publica el evento de riesgo e informa al Coordinador **solo si** el nivel supera el umbral (80 %) y persiste al menos 30 min (`nivel > umbral AND persiste`). Cada visita a una zona cuenta como 15 min simulados.
2. `AgenteSensorAire` informa su medición en cada ronda. `AgenteCoordinador` calcula riesgo y prioriza zonas siempre, pero **solo delega la alerta** (`REQUEST`) si hubo evento de riesgo.
3. `AgenteAlertas` responde `REFUSE` si ya hay una alerta activa en esa zona (alerta duplicada, flujo alterno A2). Si acepta (`AGREE`), emite el aviso y reporta `INFORM-DONE` si la comunidad confirma o `FAILURE` si no.
4. Sin evento de riesgo el grafo termina en el Coordinador: no se alerta.

### Fotos para la cámara

Puedes añadir más fotos de contenedores (`.png`, `.jpg`, `.webp`) en `app/static/fotos_locales/`. Al arrancar, cada foto se analiza una vez; las que no tienen un contenedor se descartan, y en cada ronda la cámara usa la foto cuyo nivel se parece más al nivel simulado de la zona (la foto solo se analiza, no cambia el entorno). El repositorio ya incluye 8 fotos de prueba (ver `app/static/fotos_locales/LEEME.md` para su procedencia y licencia). Sin fotos se usan las 3 imágenes de muestra. En Docker las fotos viajan dentro de la imagen.

---

## 4. Cómo ejecutarlo

Todas las opciones levantan el servidor y dejan la Sala de Control disponible en **`http://127.0.0.1:8000`**:

1. **Windows**: Haz doble clic en [`INICIAR.bat`](INICIAR.bat) (crea `.venv`, instala `requirements.txt`, abre el navegador y lanza `uvicorn app.main:app`).
2. **Linux / macOS**:
   ```bash
   chmod +x iniciar.sh
   ./iniciar.sh
   ```
3. **Docker**:
   ```bash
   docker compose up --build
   ```

---

## 5. Clave opcional `GEMINI_API_KEY`

Si deseas que `AgenteSensorResiduos` complemente el análisis visual con Gemini, configura `GEMINI_API_KEY` únicamente como variable de entorno antes de arrancar:

- **Windows (PowerShell)**:
  ```powershell
  $env:GEMINI_API_KEY="tu_clave_aqui"
  .\INICIAR.bat
  ```
- **Linux / macOS / Docker**:
  ```bash
  export GEMINI_API_KEY="tu_clave_aqui"
  ./iniciar.sh   # o: docker compose up --build
  ```

Sin `GEMINI_API_KEY`, el sistema funciona de forma autónoma y offline usando el análisis matemático HSV local (`app/vision_analyzer.py`). **NUNCA escribas tu API key dentro de archivos del repositorio ni la subas a Git.**

---

## 6. Cómo leer la Sala de Control (`http://127.0.0.1:8000`)

1. **Cabecera**: muestra si la conexión SSE está `EN VIVO` o `reconectando...` y el chip con la versión activa de `LangGraph`.
2. **Narrador**: traduce en una frase simple lo que está haciendo cada agente en ese instante.
3. **Mapa de zonas (izquierda)**: lista las zonas con su barra de llenado, etiqueta fija de entorno simulado y semáforo de riesgo (`< 40` bajo/verde, `40–70` medio/ámbar, `> 70` alto/rojo).
4. **Red de agentes (derecha)**: diagrama SVG donde cada nodo se ilumina según su estado (`reposo`, `analizando`, `comunicando`, `esperando`) y los pulsos animados muestran mensajes FIPA-ACL con su performativa.
5. **Bitácora FIPA-ACL (abajo)**: registra las últimas 8 interacciones reales (`hora`, `PERFORMATIVA`, `emisor -> receptor` y resumen del contenido) con la más reciente arriba.
6. **Cajones bajo demanda**: al pulsar un nodo del grafo se muestran sus últimos 5 mensajes; al pulsar una zona se abre su última imagen analizada anotada, el motor usado (`IA Gemini` o `Análisis local HSV`) y la explicación.

---

## 7. Pruebas automatizadas

Con el entorno virtual creado, ejecuta la suite de pruebas con `pytest`:

```powershell
# Windows
.\.venv\Scripts\python.exe -m pytest -v
```

```bash
# Linux / macOS
.venv/bin/python -m pytest -v
```

---

## 8. Mapa de archivos y endpoints

### Estructura principal (`app/`)
- [`app/main.py`](app/main.py): aplicación FastAPI, ciclo de vida (`lifespan`), endpoints REST/SSE y servicio de vistas estáticas.
- [`app/motor_langgraph.py`](app/motor_langgraph.py): grafo `StateGraph` de 5 nodos (`BazurtoStateGraphRunner`), `MemorySaver` e `info_motor()`.
- [`app/autonomo.py`](app/autonomo.py): bucle autónomo (`LoopAutonomo`), observador de mensajes ACL y `SimuladorEntorno`.
- [`app/eventos.py`](app/eventos.py): esquemas Pydantic de los 9 tipos de evento y `EventBus` seguro entre hilos para SSE.
- [`app/models_masml.py`](app/models_masml.py): implementación de los 5 agentes MAS-ML, `SMAMonitoreoBazurto` y casos de uso.
- [`app/fipa_acl.py`](app/fipa_acl.py): clase `ACLMessage` y formato FIPA-ACL (S-expression y JSON).
- [`app/vision_analyzer.py`](app/vision_analyzer.py): análisis de imágenes HSV local / Gemini y generación de imágenes anotadas.
- [`app/database.py`](app/database.py): capa de persistencia SQLite (`bazurto_sma.db`).
- `app/static/sala/`: interfaz de la Sala de Control (`sala.html`, `sala.css`, `sala.js`).

### Endpoints principales
- `GET /` — Sala de Control en vivo (observador SSE).
- `GET /api/sala/snapshot` — Estado inicial de zonas, agentes y últimos ~40 eventos al abrir la página.
- `GET /api/stream` — Flujo SSE continuo de eventos (soporta `Last-Event-ID` y `?desde=<id>`).
- `GET /api/sala/vision/{zona_id}.png` — Última imagen PNG anotada por el analizador de visión para esa zona.
- `GET /api/motor` — Metadatos verificables del motor LangGraph activo y nodos del grafo.
- `GET /documentacion` — Consola manual de casos de uso (`CU-01`, `CU-02`, 4 casos por rol MAS-ML) y visor de tablas SQLite.
- `GET /health` — Verificación de salud (`{"status": "ok", ...}`).

---

## 9. Documentación técnica y diagramas

- [Contrato de la Sala de Control y eventos SSE](docs/CONTRATO_SALA_CONTROL.md)
- [Documentación MAS-ML y FIPA-ACL de Bazurto](docs/DOCUMENTACION_MASML_FIPA_BAZURTO.md)
- [Documentación V2: 4 Casos de Uso y Diagramas](DOCUMENTACION_V2_4_CASOS_USO_Y_DIAGRAMAS.md)

---

## 10. Para sustentar (4 frases clave)

1. *"Los 5 agentes están implementados como nodos independientes dentro de un `StateGraph` real de LangGraph con memoria compartida (`BazurtoAgentState`). Una arista condicional (`decidir_ruta_supervision`) lleva a `AgenteSupervisor`: en las rondas autónomas siempre audita, y está garantizado que audita cuando la alerta termina en `FAILURE` o `REFUSE`."*
2. *"La comunicación no está cableada con llamadas directas sin protocolo: cada transición relevante emite un `ACLMessage` estándar FIPA-ACL (`INFORM`, `REQUEST`, `AGREE`, `INFORM-DONE`, `FAILURE`, `QUERY-IF`, `CONFIRM`, `DISCONFIRM`) que queda persistido en SQLite y se transmite en vivo por SSE."*
3. *"Solo el entorno físico del mercado (`SimuladorEntorno`) y la respuesta comunitaria en modo autónomo (70%) son simulados; la percepción visual, el cálculo de riesgo, la priorización de zonas, las alertas y la auditoría son código real ejecutándose en el servidor."*
4. *"Los agentes de monitoreo tienen estado persistente en `bazurto_sma.db` (`tiempoSobreLimite`, `ritmoLlenado`, `historialMediciones`), lo que les permite evaluar persistencia temporal y tendencias progresivas de gases entre rondas y no reaccionar solo a una lectura aislada."*
