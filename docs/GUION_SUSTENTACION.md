# Guion de Sustentación en Vivo (5 minutos) — SMAMonitoreoBazurto V2

Guía práctica para presentar la Sala de Control (`/`), los cajones de detalle y la página de diagramas (`/diagramas`) en tiempo real.

---

## Minuto 1 — Qué es el sistema y vista general en `/`

- **En pantalla**: Abrir `http://127.0.0.1:8000` (`/`). Señalar la cabecera con el indicador `EN VIVO` y el chip `Motor: LangGraph <version>`, la barra del narrador, la etiqueta `"Sensores del entorno: simulados"` en el panel izquierdo y las tarjetas de zonas con su barra de llenado y semáforo de riesgo (`< 40` bajo/verde, `40-70` medio/ámbar, `> 70` alto/rojo).
- **Qué decir**:
  - *"Este es el Sistema Multiagente de Monitoreo Ambiental del Mercado de Bazurto bajo el estándar MAS-ML y FIPA-ACL."*
  - *"La página no simula agentes: es solo un observador por SSE de un grafo real en LangGraph de cinco nodos que corre en el servidor y guarda su estado en SQLite."*
  - *"Lo único simulado es el entorno físico del mercado (llenado, gases, temperatura, humedad, respuesta de la comunidad al 70 % y fallas ocasionales del sensor de aire); los agentes, sus mensajes FIPA-ACL, el cálculo de riesgo, las alertas y las incidencias son código real."*

---

## Minuto 2 — Red de los 5 agentes y cajones bajo demanda

- **En pantalla**:
  1. Señalar el diagrama SVG `#red-agentes` en la columna derecha mientras los nodos cambian de estado (`reposo`, `analizando`, `comunicando`) y viajan los pulsos con el nombre de cada performativa.
  2. Hacer clic en una **tarjeta de zona** (`#mapa-zonas`) para abrir `#cajon-zona`: mostrar la imagen anotada con cajas de detección, el rótulo `"Imagen de muestra analizada"`, el motor usado (`Análisis local HSV` o `IA Gemini`) y la explicación. Cerrar con `Esc`.
  3. Hacer clic en un **nodo del grafo** (por ejemplo `AgenteCoordinador` o `AgenteSupervisor`) para abrir `#cajon-agente` y mostrar su estado actual y sus últimos 5 mensajes FIPA-ACL. Cerrar con `Esc`.
- **Qué decir**:
  - *"El sensor de residuos no se queda en una lectura numérica: inspecciona la imagen del contenedor píxel a píxel con HSV local (o Gemini si hay clave) y cuenta bolsas en el suelo."*
  - *"Cada nodo tiene memoria en SQLite; por eso el sensor de residuos evalúa persistencia temporal y el sensor de aire detecta aumentos progresivos entre rondas."*

---

## Minuto 3 — Cómo reconocer en vivo el Caso de Uso 1 (`CU-01`) y `REFUSE`

- **En pantalla**: Fijarse en la bitácora inferior (`#lista-bitacora`), donde cada mensaje del monitoreo y alerta lleva la etiqueta azul petróleo **`CU-01`**, y en la frase superior del **narrador**.
- **Cómo reconocer `CU-01` normal en vivo**:
  1. **Sin evento de riesgo**: `AgenteSensorAire` envía `INFORM` al `AgenteCoordinador`, pero `AgenteSensorResiduos` no envía evento si el nivel es `<= 80 %` o no ha superado `30 minutos` simulados (`15 min` por visita). El narrador explica: *"<zona> está por debajo del umbral (80 %)..."* o *"supera el umbral pero aún no lleva el tiempo mínimo seguido..."*.
  2. **Con evento persistente (`nivel > 80 %` y `>= 30 min`)**: en la bitácora aparecen seguidos `CU-01` **`INFORM`** (`SensorResiduos -> Coordinador`), `CU-01` **`INFORM`** (`SensorAire -> Coordinador`), `CU-01` **`REQUEST`** (`Coordinador -> Alertas`), `CU-01` **`AGREE`** (`Alertas -> Coordinador`) y el cierre:
     - **`INFORM-DONE`** si la comunidad confirma (70 %): el narrador anuncia *"Alerta atendida: se envió un camión recolector a <zona>; llegará en unas rondas."*
     - **`FAILURE`** si no confirma (30 %): el narrador avisa en rojo *"El agente de alertas avisa al Coordinador: la comunidad no confirmó la alerta."*
- **Cómo reconocer `REFUSE` (`A2` de `CU-01`) en vivo**:
  - Si la misma zona se revisa antes de que llegue el camión recolector (todavía tiene una alerta activa en SQLite), en la bitácora aparece `CU-01` **`REFUSE`** (`Alertas -> Coordinador`) y el narrador dice: *"El agente de alertas rechaza la solicitud al Coordinador: ya hay una alerta activa en esa zona."*

---

## Minuto 4 — Cómo reconocer en vivo la Supervisión (`CU-02`: flujos `A1` y `A2`)

- **En pantalla**: Observar los mensajes con etiqueta ámbar **`CU-02`** en `#lista-bitacora` cuando entra el `AgenteSupervisor` (`auditar_supervision()`).
- **Auditoría base**: El Supervisor envía **`QUERY-IF`** al Coordinador (`CONFIRM`), a `AgenteAlertas` y a `AgenteSensorAire` con plazo `reply-by` de `5 s` (el narrador dice: *"El Supervisor pregunta al sensor de aire si sigue funcionando (plazo: 5 s)."*).
- **Cómo reconocer el flujo `A1` (sin confirmación comunitaria)**:
  1. Después de un `FAILURE` en `CU-01`, en la bitácora con etiqueta `CU-02` aparece **`DISCONFIRM`** (`Alertas -> Supervisor`). El narrador dice: *"El agente de alertas le dice al Supervisor que la alerta no fue confirmada."*
  2. El Supervisor registra la incidencia y envía **`REQUEST`** de acción correctiva (`Supervisor -> Coordinador`); el Coordinador responde **`AGREE`** (`Coordinador -> Supervisor`) y reenvía **`REQUEST`** (`Coordinador -> Alertas`) con `reintento=True`. El narrador dice: *"El Coordinador pide al agente de alertas reintentar la alerta."*
- **Cómo reconocer el flujo `A2` (sensor de aire caído, 3 % de probabilidad por zona y ronda, dura 3 a 5 rondas)**:
  1. En esa ronda `AgenteSensorAire` no envía `INFORM` en `CU-01`.
  2. En `CU-02` el Supervisor lanza **`QUERY-IF`** hacia `AgenteSensorAire`, vence el `reply-by` de `5 s`, registra la incidencia y envía **`INFORM`** (`Supervisor -> Coordinador`: *"El Supervisor notifica al Coordinador una falla en un agente."*) más **`REQUEST`** (`recalcular_riesgo_sin_sensor_aire`), el Coordinador responde **`AGREE`** y recalcula el riesgo sin el sensor de aire. El narrador resume en nivel crítico: *"El sensor de aire de <zona> no respondió antes del plazo: el Supervisor registra la incidencia y el Coordinador recalcula el riesgo sin ese sensor."*
  3. Si el sensor cae en una ronda sin evento de riesgo, el grafo pasa directo de `AgenteCoordinador` a `AgenteSupervisor` para ejecutar `A2`.

---

## Minuto 5 — Página `/diagramas` y cierre

- **En pantalla**: Hacer clic en el enlace **`Diagramas`** en el footer para abrir `/diagramas`. Mostrar:
  1. El **Diagrama de Clases MAS-ML** (organización, entorno, 4 roles y 5 agentes).
  2. Los **Diagramas de Secuencia `CU-01` y `CU-02`** con las performativas exactas que se acaban de observar en la Sala de Control.
  3. El **Grafo real del motor**, cargado en vivo desde `/api/motor`, donde se ve la arista condicional hacia `nodo_supervisor` tanto desde `nodo_alertas` como desde `nodo_coordinador` cuando cae el sensor de aire (`CU-02 A2`).
- **Qué decir**: *"El diseño en Mermaid y el grafo real compilado en LangGraph coinciden uno a uno con los mensajes FIPA-ACL que acabamos de ver en vivo."*

---

## Preguntas probables del profesor

1. **¿Qué partes del proyecto son reales y qué partes son simuladas?**
   - Son reales los 5 agentes MAS-ML, el grafo `StateGraph` de LangGraph, el checkpointer `MemorySaver`, la persistencia en SQLite (`bazurto_sma.db`), los mensajes `ACLMessage` FIPA-ACL, el cálculo de riesgo y priorización, la generación de alertas e incidencias, y el analizador de imágenes (`HSV` local o `Gemini`). Son simulados únicamente el avance de sensores del entorno `MercadoBazurto` (`SimuladorEntorno`), la probabilidad de confirmación comunitaria (`70 %` en modo autónomo) y la probabilidad de falla temporal del sensor de aire (`3 %` por zona y ronda, recuperándose tras `3 a 5` rondas).

2. **¿Por qué usaron LangGraph como motor multiagente y cómo maneja el estado?**
   - Porque LangGraph modela explícitamente los 5 agentes como nodos de un `StateGraph` tipado (`BazurtoAgentState`) con aristas condicionales reales (por ejemplo, omitir alertas si no hay persistencia, ir directo a supervisión ante falla del sensor de aire, o auditar alertas con `FAILURE`/`REFUSE`), conserva el estado de ejecución mediante `MemorySaver` por `thread_id` y se apoya en SQLite para mantener memoria histórica entre rondas.

3. **¿Qué significa el campo `reply-by` en FIPA-ACL y cómo se aplica en el Caso de Uso 2?**
   - En FIPA-ACL, `reply-by` fija el tiempo límite máximo en que el emisor espera una respuesta del receptor antes de considerar que hubo un timeout. En `CU-02` (`auditar_supervision()`), `AgenteSupervisor` envía un `QUERY-IF` a `AgenteSensorAire` con `reply_by="5s"`; si el sensor está caído y no responde dentro del plazo, el Supervisor registra un timeout e incidencia, notifica la falla al Coordinador con `INFORM` y solicita el recálculo de riesgo sin ese sensor.

4. **En el diagrama de clases MAS-ML, ¿cómo se leen las flechas punteadas `dependency` (`A ..> B : dependency`)?**
   - Según la regla del diagrama MAS-ML vista en clase, la lectura va de la punta al rabo (`Punta depende del Rabo`). Por lo tanto, en `MonitorCondicionesAmbientales ..> Coordinador : dependency`, el `Coordinador` (punta) depende de `MonitorCondicionesAmbientales` (rabo) para recibir mediciones y eventos de riesgo; y en `Coordinador ..> EmisorAlertas : dependency`, `EmisorAlertas` (punta) depende de `Coordinador` (rabo) porque solo actúa tras recibir la delegación de alerta.

5. **¿Por qué `AgenteSensorResiduos` no dispara una alerta apenas ve un contenedor por encima del 80 % una sola vez?**
   - Porque es un agente basado en modelos con estado interno persistido (`tiempoSobreLimite`, `ritmoLlenado`, `ciclosConsecutivos`). Su método `evaluarPersistencia()` exige que se cumpla la condición del diagrama de secuencia `nivel > umbral AND persiste` (`nivel > 80 %` durante al menos `30 min` simulados, sumando `15 min` por cada visita consecutiva sobre el límite), evitando alertas falsas por picos momentáneos.

6. **¿Cuál es la diferencia entre `REFUSE` y `FAILURE` cuando `AgenteAlertas` responde al Coordinador?**
   - `REFUSE` pertenece a la perspectiva social de FIPA-ACL: el agente rechaza la solicitud antes de ejecutarla porque ya existe una alerta activa sin resolver en esa zona (`A2` de `CU-01`). `FAILURE` pertenece a la perspectiva accional: el agente primero acepta el compromiso con `AGREE`, emite el aviso a la comunidad, pero falla al gestionar la confirmación comunitaria (`A1` de `CU-01`), lo que luego activa el escalamiento en `CU-02`.
