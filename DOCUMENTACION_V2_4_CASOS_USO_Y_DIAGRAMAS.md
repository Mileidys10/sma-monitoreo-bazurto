# SMAMonitoreoBazurto (Versión 2 Completa) — IA Multimodal Híbrida + 4 Casos de Uso por Rol

## 1. Arquitectura Híbrida de Visión (`AgenteSensorResiduos.analizarImagenes()`)
Para responder a escenarios reales con conectividad y escenarios portátiles sin internet (como una sustentación en sala de clase con `.zip`), el agente `AgenteSensorResiduos` opera en modo híbrido:

1. **IA Multimodal Real (Gemini 2.5 Flash):** Cuando hay conexión a internet y una `Gemini API Key` configurada en la consola (o en la variable de entorno `GEMINI_API_KEY`), el agente envía el fotograma al modelo multimodal para identificar semánticamente contenedores, nivel de llenado real, bolsas/residuos en el suelo, coordenadas delimitadoras (`box_2d`) y una explicación redactada en lenguaje natural (`explicacion_ia`).
2. **Motor Matemático HSV Local (100% Offline):** Cuando no hay clave o no hay conexión, el sistema conmuta automáticamente al analizador cromático local (`200×200` en Pillow para Python / `<canvas>` en el navegador), midiendo píxeles en espacios HSV (`estructura_px`, `boca_residuos_px`, `cavidad_residuos_px`, `suelo_residuos_px`, `cavidad_vacia_px`), descartando imágenes sin contenedores y calculando el porcentaje y número de bolsas sin valores fijos pregrabados.

---

## 2. Diagrama de Clases MAS-ML (Base y Regla de Dependencia)

```mermaid
classDiagram
    class SMAMonitoreoBazurto {
        <<organization>>
        +objetivo: ReducirRiesgoAmbientalBazurto
        +politica: PriorizacionCoordinada
        +parametros: UmbralesConfigurables
    }

    class MercadoBazurto {
        <<environment>>
        +zonas: Lista~Zona~
        +nivelLlenadoContenedores: Real
        +concentracionGases: Real
        +temperatura: Real
        +humedad: Real
    }

    class MonitorCondicionesAmbientales {
        <<role>>
        +duties: obtener mediciones ambientales, analizar condiciones del entorno, identificar situaciones de riesgo, reportar eventos ambientales
        +rights: acceder a los datos de los sensores, consultar mediciones ambientales, comunicar eventos al coordinador
    }

    class Coordinador {
        <<role>>
        +duties: calcular riesgo ambiental, priorizar zonas, delegar emisión de alertas, escalar situaciones
        +rights: consultar eventos ambientales, solicitar emisión de alertas
    }

    class EmisorAlertas {
        <<role>>
        +duties: emitir mensajes a la comunidad, gestionar confirmaciones de recepción, generar reportes de confirmación o falta de confirmación
        +rights: recibir solicitudes de alerta, acceder a mecanismos de comunicación, consultar estado de alertas
    }

    class Supervisor {
        <<role>>
        +duties: supervisar funcionamiento de agentes, verificar atención de eventos, registrar incidencias, notificar fallos
        +rights: consultar estado general del sistema, solicitar acciones correctivas
    }

    class AgenteSensorResiduos {
        <<agent>>
        -arquitectura: Basado en modelos
        -estadoInterno: nivel, tiempoSobreLimite, ritmoLlenado
        +medirNivelLlenadoContenedores()
        +analizarImagenes()
        +evaluarPersistencia()
        +publicarEventoRiesgo()
    }

    class AgenteSensorAire {
        <<agent>>
        -arquitectura: Basado en modelos
        -historialMediciones: Lista~Medicion~
        +medirGases()
        +registrarMedicion()
        +detectarAumentoProgresivo()
        +publicarMedicion()
    }

    class AgenteCoordinador {
        <<agent>>
        -arquitectura: Basado en utilidad
        +consultarEventos()
        +calcularRiesgo()
        +priorizarZonas()
        +delegarAlerta()
    }

    class AgenteAlertas {
        <<agent>>
        -arquitectura: Basado en metas
        +recibirSolicitudAlerta()
        +emitirAviso()
        +gestionarConfirmacion()
        +generarReporteConfirmacion()
        +generarReporteSinConfirmacion()
    }

    class AgenteSupervisor {
        <<agent>>
        -arquitectura: Basado en utilidad
        +supervisarAgentes()
        +verificarAtencionEventos()
        +registrarIncidencias()
        +notificarFallos()
        +solicitarAccionesCorrectivas()
    }

    SMAMonitoreoBazurto "1" -- "1" MercadoBazurto : inhabit
    SMAMonitoreoBazurto *-- MonitorCondicionesAmbientales : owns
    SMAMonitoreoBazurto *-- Coordinador : owns
    SMAMonitoreoBazurto *-- EmisorAlertas : owns
    SMAMonitoreoBazurto *-- Supervisor : owns

    AgenteSensorResiduos --> MonitorCondicionesAmbientales : play
    AgenteSensorAire --> MonitorCondicionesAmbientales : play
    AgenteCoordinador --> Coordinador : play
    AgenteAlertas --> EmisorAlertas : play
    AgenteSupervisor --> Supervisor : play

    Supervisor --> MonitorCondicionesAmbientales : control
    Supervisor --> Coordinador : control
    Supervisor --> EmisorAlertas : control

    MonitorCondicionesAmbientales ..> Coordinador : dependency
    Coordinador ..> EmisorAlertas : dependency
```

> **Regla de flechas `dependency` (criterio del docente):** En `A ..> B : dependency`, el rol en la punta (`B`) depende del rol en el rabo (`A`). Por ello, `Coordinador` depende de `MonitorCondicionesAmbientales`, y `EmisorAlertas` depende de `Coordinador`.

---

## 3. Desglose Formal: 4 Casos de Uso por cada `<<role>>`

### Ficha CU-ROL-01 — Rol `MonitorCondicionesAmbientales`
- **Nombre:** Monitoreo visual de contenedores y medición continua de gases en `MercadoBazurto`.
- **Rol involucrado:** `MonitorCondicionesAmbientales` (`AgenteSensorResiduos`, `AgenteSensorAire`).
- **Actores externos / Entorno:** `MercadoBazurto` (`zonas`, `nivelLlenadoContenedores`, `concentracionGases`, `temperatura`, `humedad`).
- **Precondiciones:** Zonas y cámaras de contenedores registradas en el entorno.
- **Flujo principal:**
  1. `AgenteSensorResiduos` consulta `MercadoBazurto` (`medirNivelLlenadoContenedores()`).
  2. Ejecuta `analizarImagenes()` sobre la imagen asignada al contenedor (IA Gemini 2.5 Flash o cálculo HSV offline).
  3. Descarta imágenes sin contenedor (`sin_contenedor_detectado`) o actualiza la persistencia (`evaluarPersistencia()`).
  4. Publica evento de riesgo al Coordinador (`publicarEventoRiesgo()`, ACL `INFORM`).
  5. `AgenteSensorAire` ejecuta `medirGases()`, `registrarMedicion()`, `detectarAumentoProgresivo()` y `publicarMedicion()` (`INFORM`).

### Ficha CU-ROL-02 — Rol `Coordinador` (Inspección Coordinada de las 3 Cámaras)
- **Nombre:** Consulta activa de cámaras de todas las zonas, cálculo de utilidad ambiental y priorización coordinada.
- **Rol involucrado:** `Coordinador` (`AgenteCoordinador`).
- **Precondiciones:** Cada zona cuenta con una imagen asignada (por defecto `contenedor_limpio.png` en Zona 2, `contenedor_critico.png` en Zona 3 y `contenedor_medio.png` en Zona 5, o fotografías cargadas por el usuario).
- **Flujo principal:**
  1. `AgenteCoordinador` ejecuta `consultarEventos()` y envía un `ACL:QUERY-REF` (`FIPA-Query`) a `AgenteSensorResiduos` solicitando revisar la cámara de cada zona, y a `AgenteSensorAire` solicitando los niveles de gases.
  2. `AgenteSensorResiduos` inspecciona cada imagen (`analizarImagenes()`) y responde mediante `ACL:INFORM` reportando nivel de llenado, bolsas en el suelo y explicación.
  3. `AgenteCoordinador` calcula el índice de riesgo por utilidad (`calcularRiesgo()`) para todas las zonas inspeccionadas.
  4. Ordena todas las zonas según `PriorizacionCoordinada` (`priorizarZonas()`).
  5. Delega la emisión de alerta para la zona prioritaria `#1` mediante `delegarAlerta()` (`ACL:REQUEST` a `AgenteAlertas`).

### Ficha CU-ROL-03 — Rol `EmisorAlertas`
- **Nombre:** Recepción de solicitudes de alerta, aviso comunitario y gestión de confirmaciones.
- **Rol involucrado:** `EmisorAlertas` (`AgenteAlertas`).
- **Flujo principal:**
  1. `AgenteAlertas` recibe la delegación (`recibirSolicitudAlerta()`) y valida no duplicidad (`AGREE` o `REFUSE`).
  2. Emite el aviso al panel comunitario (`emitirAviso()`).
  3. Gestiona la confirmación de líderes de zona (`gestionarConfirmacion()`).
  4. Si confirman (`ACK`), ejecuta `generarReporteConfirmacion()` y cierra con `ACL:INFORM-DONE`. Si no confirman, ejecuta `generarReporteSinConfirmacion()` y cierra con `ACL:FAILURE`.

### Ficha CU-ROL-04 — Rol `Supervisor`
- **Nombre:** Supervisión integral de agentes, auditoría de eventos sin confirmación y acciones correctivas.
- **Rol involucrado:** `Supervisor` (`AgenteSupervisor`).
- **Flujo principal:**
  1. `AgenteSupervisor` ejecuta `supervisarAgentes()` y `verificarAtencionEventos()`.
  2. Envía `ACL:QUERY-IF` (`FIPA-Query`) a `AgenteCoordinador` (`CONFIRM`), a `AgenteAlertas` (`CONFIRM` / `DISCONFIRM`) y a `AgenteSensorAire` (`CONFIRM` / timeout).
  3. Si detecta falta de confirmación o sensor caído, registra la incidencia (`registrarIncidencias()`), notifica fallos (`notificarFallos()`) y envía `ACL:REQUEST` con `solicitarAccionesCorrectivas()` (escalamiento comunitario o recálculo de riesgo sin sensor de aire).

---

## 4. Diagramas de Secuencia en PlantUML (4 Casos de Uso por Rol)

### 4.1 Diagrama de Secuencia `CU-ROL-01` (`MonitorCondicionesAmbientales`)

```plantuml
@startuml CU_ROL_01_MonitorCondicionesAmbientales
autonumber
participant "AgenteSensorResiduos\n(rol: MonitorCondicionesAmbientales)" as Res
participant "AgenteSensorAire\n(rol: MonitorCondicionesAmbientales)" as Air
participant "MercadoBazurto\n<<environment>>" as Env
participant "AgenteCoordinador\n(rol: Coordinador)" as Coord

Res -> Env : consultar nivelLlenadoContenedores y cámara zona
Env --> Res : nivelLlenadoContenedores, imagen asignada

Res -> Res : medirNivelLlenadoContenedores()
Res -> Res : analizarImagenes()
alt Contenedor detectado en imagen
    Res -> Env : actualizar nivelLlenadoContenedores
    Res -> Res : evaluarPersistencia()
    Res -> Coord : INFORM(eventoRiesgo, nivel, bolsasSuelo)\n<<ACL:INFORM>> / publicarEventoRiesgo()
else Imagen sin contenedor
    Res -> Res : descartar lectura sin alterar MercadoBazurto
end

Air -> Env : consultar concentracionGases, temperatura, humedad
Env --> Air : lectura actual de gases

Air -> Air : medirGases()
Air -> Air : registrarMedicion()
Air -> Air : detectarAumentoProgresivo()
Air -> Coord : INFORM(medicionGases, tendencia)\n<<ACL:INFORM>> / publicarMedicion()
@enduml
```

### 4.2 Diagrama de Secuencia `CU-ROL-02` (`Coordinador` — Orden de Revisión de Cámaras)

```plantuml
@startuml CU_ROL_02_Coordinador_Inspeccion_Camaras
autonumber
participant "AgenteCoordinador\n(rol: Coordinador)" as Coord
participant "AgenteSensorResiduos\n(rol: MonitorCondicionesAmbientales)" as Res
participant "AgenteSensorAire\n(rol: MonitorCondicionesAmbientales)" as Air
participant "MercadoBazurto\n<<environment>>" as Env
participant "AgenteAlertas\n(rol: EmisorAlertas)" as Alert

Coord -> Coord : consultarEventos()
loop Por cada zona en MercadoBazurto (Zona 2, Zona 3, Zona 5, ...)
    Coord -> Res : QUERY-REF(revisar_camara_zona, zona, contenedor)\n<<ACL:QUERY-REF>>
    Res -> Env : leer imagen asignada a la cámara del contenedor
    Env --> Res : fotograma asignado (escena base o foto del usuario)
    Res -> Res : medirNivelLlenadoContenedores()
    Res -> Res : analizarImagenes()
    Res -> Res : evaluarPersistencia()
    Res --> Coord : INFORM(llenadoVisual, bolsasSuelo, estadoVisual, explicacion)\n<<ACL:INFORM>>

    Coord -> Air : QUERY-REF(consultar_gases_zona, zona)\n<<ACL:QUERY-REF>>
    Air -> Env : leer concentracionGases, temperatura, humedad
    Env --> Air : medicion actual
    Air -> Air : medirGases(), registrarMedicion(), detectarAumentoProgresivo()
    Air --> Coord : INFORM(concentracionGases, aumentoProgresivo)\n<<ACL:INFORM>>

    Coord -> Coord : calcularRiesgo()
end

Coord -> Coord : priorizarZonas()
Coord -> Alert : REQUEST(emitirAlerta, zonaPrioritaria #1, riesgo)\n<<ACL:REQUEST>> / delegarAlerta()
@enduml
```

### 4.3 Diagrama de Secuencia `CU-ROL-03` (`EmisorAlertas`)

```plantuml
@startuml CU_ROL_03_EmisorAlertas
autonumber
participant "AgenteCoordinador\n(rol: Coordinador)" as Coord
participant "AgenteAlertas\n(rol: EmisorAlertas)" as Alert
participant "MercadoBazurto\n<<environment>>" as Env

Coord -> Alert : REQUEST(emitirAlerta, zona, nivelAlerta)\n<<ACL:REQUEST>>
Alert -> Alert : recibirSolicitudAlerta()

alt Zona ya posee alerta activa (duplicada)
    Alert --> Coord : REFUSE(alerta_duplicada_activa)\n<<ACL:REFUSE>>
else Solicitud válida
    Alert --> Coord : AGREE(solicitud_aceptada)\n<<ACL:AGREE>>
    Alert -> Alert : emitirAviso()
    Alert -> Env : consultar estado de recepción comunitaria (ACK)
    Env --> Alert : comunidad_confirma
    Alert -> Alert : gestionarConfirmacion()

    alt Comunidad confirma recepción (ACK)
        Alert -> Alert : generarReporteConfirmacion()
        Alert --> Coord : INFORM-DONE(alerta_confirmada)\n<<ACL:INFORM-DONE>>
    else Comunidad NO confirma recepción
        Alert -> Alert : generarReporteSinConfirmacion()
        Alert --> Coord : FAILURE(sin_confirmacion_comunidad)\n<<ACL:FAILURE>>
    end
end
@enduml
```

### 4.4 Diagrama de Secuencia `CU-ROL-04` (`Supervisor`)

```plantuml
@startuml CU_ROL_04_Supervisor
autonumber
participant "AgenteSupervisor\n(rol: Supervisor)" as Sup
participant "AgenteCoordinador\n(rol: Coordinador)" as Coord
participant "AgenteAlertas\n(rol: EmisorAlertas)" as Alert
participant "AgenteSensorAire\n(rol: MonitorCondicionesAmbientales)" as Air

Sup -> Sup : verificarAtencionEventos()
Sup -> Sup : supervisarAgentes()

Sup -> Coord : QUERY-IF(atendido_evento, zona)\n<<ACL:QUERY-IF>>
Coord --> Sup : CONFIRM(alerta_delegada=true)\n<<ACL:CONFIRM>>

Sup -> Alert : QUERY-IF(alerta_confirmada_por_comunidad, zona)\n<<ACL:QUERY-IF>>
alt Sin confirmación comunitaria
    Alert --> Sup : DISCONFIRM(confirmada=false)\n<<ACL:DISCONFIRM>>
    Sup -> Sup : registrarIncidencias()
    Sup -> Sup : notificarFallos()
    Sup -> Alert : REQUEST(reenviar_alerta_escalada)\n<<ACL:REQUEST>> / solicitarAccionesCorrectivas()
    Alert --> Sup : AGREE(reenvio_escalado)\n<<ACL:AGREE>>
else Alerta confirmada
    Alert --> Sup : CONFIRM(confirmada=true)\n<<ACL:CONFIRM>>
end

Sup -> Air : QUERY-IF(estado_sensor_aire, zona)\n<<ACL:QUERY-IF>>
alt Sensor caído / sin respuesta
    Sup -> Sup : registrarIncidencias()
    Sup -> Sup : notificarFallos()
    Sup -> Coord : REQUEST(recalcular_riesgo_sin_sensor_aire)\n<<ACL:REQUEST>> / solicitarAccionesCorrectivas()
    Coord --> Sup : AGREE(recalcular_riesgo)\n<<ACL:AGREE>>
    Coord -> Coord : calcularRiesgo(incluir_sensor_aire=false)
    Coord -> Coord : priorizarZonas()
else Sensor activo
    Air --> Sup : CONFIRM(sensor_operativo=true)\n<<ACL:CONFIRM>>
end
@enduml
```

---

## 5. Motor Multiagente Real en LangGraph (`StateGraph` de 5 Nodos)

El proyecto utiliza **LangGraph** como única tecnología multiagente de orquestación. El módulo [`app/motor_langgraph.py`](app/motor_langgraph.py) implementa un **Grafo de Estados (`BazurtoStateGraphRunner`)** sobre `StateGraph(BazurtoAgentState)` con checkpointer `MemorySaver` y persistencia de dominio en SQLite (`bazurto_sma.db`), conservando entre rondas el estado interno de los agentes (`tiempoSobreLimite`, `ritmoLlenado`, `ciclosConsecutivos`, `historialMediciones`), los eventos de riesgo, las alertas, las incidencias y todos los mensajes `FIPA-ACL`.

### 5.1 Arquitectura del `StateGraph` de 5 Nodos (Conectado al Backend Real)

```mermaid
flowchart TD
    START([START]) --> nodo_sensor_residuos[nodo_sensor_residuos<br/>AgenteSensorResiduos]
    nodo_sensor_residuos -->|ACL:INFORM| nodo_sensor_aire[nodo_sensor_aire<br/>AgenteSensorAire]
    nodo_sensor_aire -->|ACL:INFORM| nodo_coordinador[nodo_coordinador<br/>AgenteCoordinador]
    nodo_coordinador -->|sin evento de riesgo persistente| END([END])
    nodo_coordinador -->|sensor de aire sin respuesta: CU-02 A2| nodo_supervisor
    nodo_coordinador -->|ACL:REQUEST si hay evento| nodo_alertas[nodo_alertas<br/>AgenteAlertas]
    nodo_alertas -->|decidir_ruta_supervision: FAILURE / REFUSE / Auditar| nodo_supervisor[nodo_supervisor<br/>AgenteSupervisor]
    nodo_alertas -->|INFORM-DONE sin auditoría extra| END([END])
    nodo_supervisor -->|REQUEST / CONFIRM| END
```

Cada ejecución recibe un `thread_id` único en el `MemorySaver` de LangGraph y ejecuta los nodos reales conectados a `SMAMonitoreoBazurto`:
1. `nodo_sensor_residuos` (`AgenteSensorResiduos`): mide el nivel, ejecuta `analizarImagenes()` y evalúa persistencia (`nivel > 80 %` durante `>= 30 min`, contando `15 min` simulados por visita). Solo publica evento e `INFORM` si se cumple la persistencia.
2. `nodo_sensor_aire` (`AgenteSensorAire`): si el sensor de la zona está activo, mide CO₂, temperatura y humedad, registra historial y envía `INFORM` en cada ronda. Si está fuera de servicio, no mide ni envía `INFORM`.
3. `nodo_coordinador` (`AgenteCoordinador`): consulta eventos, calcula el riesgo compuesto y prioriza las zonas. Si hubo evento persistente, delega `REQUEST` hacia `nodo_alertas`; si no hubo evento pero `sensor_aire_caido` es verdadero, transiciona directo hacia `nodo_supervisor` (`CU-02 A2`); de lo contrario finaliza en `END`.
4. `nodo_alertas` (`AgenteAlertas`): responde `REFUSE` si ya hay una alerta activa en la zona; si acepta (`AGREE`), emite el aviso comunitario y cierra con `INFORM-DONE` (confirmado) o `FAILURE` (sin confirmación).
5. `nodo_supervisor` (`AgenteSupervisor`): ejecuta `auditar_supervision()` (`CU-02`) con consultas `QUERY-IF` hacia Coordinador, Alertas y Sensor de Aire (`reply-by` de `5 s`), registrando incidencias y solicitando acciones correctivas ante `DISCONFIRM` (`A1`) o timeout del sensor de aire (`A2`).

### 5.2 Endpoints Activos del Sistema

- `GET /`: Sala de Control en vivo (observador SSE de eventos reales del motor LangGraph).
- `GET /diagramas`: Diagramas UML MAS-ML, secuencias `CU-01` / `CU-02` y el grafo real servido desde `/api/motor`.
- `GET /documentacion`: Consola manual para ejecutar `CU-01`, `CU-02` y los 4 casos por rol, subir fotos y consultar tablas SQLite.
- `GET /api/motor`: Devuelve la versión instalada de LangGraph, el checkpointer y `mermaid_graph`.
- `GET /api/sala/snapshot` y `GET /api/stream`: Snapshot inicial y flujo SSE continuo de los 9 tipos de evento.
- `GET /health`: Estado operativo de la aplicación (`{"status": "ok", ...}`).
