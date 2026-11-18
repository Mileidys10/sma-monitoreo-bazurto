# Contrato de la Sala de Control — SMAMonitoreoBazurto V2

Autor del contrato: Claude (Orquestador). Quien construya la interfaz (Gemini) **debe respetarlo al pie de la letra**.
La pagina es un **observador**: no dispara agentes. Los agentes corren en el servidor (LangGraph real) y la pagina
solo muestra lo que llega por SSE. Prohibido simular eventos en el navegador.

## 1. Archivos a producir (todos en `app/static/sala/`)
- `sala.html`: estructura semantica (sin estilos ni scripts en linea, solo `<link>` y `<script defer>`).
- `sala.css`: estilos.
- `sala.js`: logica (JavaScript puro, sin librerias externas ni CDN, sin `eval`, sin `innerHTML` con datos del servidor: usar `textContent`).

El backend sirve la pagina en `/` y los archivos en `/static/sala/...`.

## 2. Endpoints
| Metodo | Ruta | Descripcion |
| :-- | :-- | :-- |
| GET | `/api/stream` | SSE. Cabecera `Last-Event-ID` o `?desde=<id>` reanuda. Cada mensaje: `id`, `event` (= tipo) y `data` (JSON `Evento`). |
| GET | `/api/sala/snapshot` | JSON con el estado actual para pintar al abrir (ver 4). |
| GET | `/health` | `{"status":"ok"}` |

`EventSource` reconecta solo; al reconectar, mostrar un indicador discreto "reconectando..." y volver a "EN VIVO" al llegar un evento.

## 3. Evento (sobre del SSE)
```json
{ "id": 42, "tipo": "mensaje_acl", "ts": 1763481600.12, "datos": { ... } }
```
Tipos y `datos` (todos los campos listados siempre estan presentes salvo los marcados `?` que pueden ser `null`):

- `sistema` (tambien viene en `snapshot.sistema`): `motor` (str, ej. "LangGraph"), `version_langgraph` (str), `intervalo_s` (num), `mensaje` (str).
- `ronda_inicio`: `ronda` (int), `zona_id` (str), `zona_nombre` (str).
- `agente_estado`: `agente` (uno de `AgenteSensorResiduos|AgenteSensorAire|AgenteCoordinador|AgenteAlertas|AgenteSupervisor`), `estado` (`reposo|analizando|comunicando|esperando`), `detalle` (str).
- `mensaje_acl`: `msg_id`, `performativa` (ej. `INFORM`, `REQUEST`, `AGREE`, `CONFIRM`, `REFUSE`, `FAILURE`, `INFORM-DONE`), `emisor`, `receptor` (nombres de agente), `contenido` (str), `conversation_id`, `protocolo`, `ronda`, `caso_uso` (`CU-01` monitoreo y alerta, `CU-02` supervisión).
- `medicion` (una por zona en cada ronda; todas del mismo instante): `zona_id`, `nivel_llenado` (0-100), `concentracion_gases` (ppm), `temperatura` (C), `humedad` (%), `riesgo?` (0-100).
- `vision`: `zona_id`, `contenedor_id`, `porcentaje_llenado`, `bolsas` (int), `motor` (`gemini|hsv`), `imagen_anotada_url?` (ruta relativa, ej. `/api/sala/vision/zona_3.png?v=7`: **imagen ya anotada por el analizador con las cajas dibujadas**; mostrarla tal cual con `<img>`, NO dibujar cajas encima), `imagen_url?` (imagen de muestra original, respaldo si no hay anotada), `cajas` (lista siempre vacia: IGNORAR), `explicacion` (str).
- `alerta`: `alerta_id?`, `zona_id`, `estado` (str), `mensaje` (str).
- `narracion`: `texto` (frase en lenguaje simple, 1 linea), `nivel` (`info|atencion|critico`).
- `ronda_fin`: `ronda`, `zona_id`, `riesgo?`, `ranking` (lista de objetos `{zona_id, riesgo, ...}`, puede traer campos extra: ignorarlos).

## 4. Snapshot (`GET /api/sala/snapshot`)
```json
{
  "ultimo_evento_id": 42,
  "zonas": [ { "zona_id":"zona_3", "nombre":"Sector Pescaderia y Acopio Central",
               "nivel_llenado":92.0, "concentracion_gases":850.0, "temperatura":32.0, "humedad":78.0, "riesgo":71.5 } ],
  "agentes": [ { "agente":"AgenteCoordinador", "estado":"reposo", "detalle":"" } ],
  "recientes": [ /* ultimos ~40 Evento, de mas antiguo a mas nuevo */ ]
}
```
Al abrir: pintar el snapshot, luego abrir `EventSource('/api/stream?desde=' + ultimo_evento_id)`.

## 5. Estructura de la pantalla ("Sala de control", sin saturar)
Cuadricula fija en 3 bandas dentro de `<main>`:
1. **Cabecera**: titulo "SMA Bazurto", indicador de conexion (`EN VIVO` / `reconectando...`), chip "Motor: LangGraph <version>" (del evento `sistema`), y la **frase narrador** (`#narrador`, `aria-live="polite"`) con el ultimo `narracion`.
2. **Banda media (2 columnas)**:
   - Izquierda `#mapa-zonas`: una tarjeta por zona (nombre corto, barra de llenado, semaforo verde/ambar/rojo por `riesgo`: <40 verde, 40-70 ambar, >70 rojo, y **texto** ademas del color). La zona de la ronda activa se resalta. Boton/tarjeta enfocable que abre el cajon de la zona (foto analizada).
   - Derecha `#red-agentes`: SVG con los 5 agentes en nodos fijos (Supervisor arriba; SensorResiduos y SensorAire a la izquierda; Coordinador al centro; Alertas a la derecha). Un nodo se ilumina segun `agente_estado`. Cada `mensaje_acl` anima un pulso a lo largo de la flecha emisor->receptor y deja la etiqueta de la performativa 2 s. Maximo 1-2 mensajes animados a la vez.
3. **Banda inferior** `#bitacora`: lista de las **ultimas 8** lineas `mensaje_acl` (hora, PERFORMATIVA, emisor->receptor, contenido corto), la mas nueva arriba. `role="log"`.

**Cajones (detalle bajo demanda, cerrados por defecto):**
- `#cajon-agente`: al activar un nodo del SVG (clic o Enter) muestra estado y los ultimos 5 mensajes de ese agente.
- `#cajon-zona`: al activar una zona muestra la ultima `vision` de esa zona: `<img>` con `imagen_anotada_url` (con `alt` descriptivo y rotulo visible 'Imagen de muestra analizada'), porcentaje, bolsas, motor (`IA Gemini` o `Analisis local HSV`) y `explicacion`.
- Cerrar con boton y con `Esc`. Foco devuelto al elemento que lo abrio.

Etiqueta visible y fija en el mapa: "Sensores del entorno: simulados". Los agentes y mensajes son reales.

## 6. Diseno y accesibilidad (obligatorio)
- Un solo color de acento (azul petroleo) + semaforo solo para riesgo. Sin morado, degradados, glassmorphism ni emojis como iconos.
- Contraste WCAG 2.1 AA (>= 4.5:1), foco visible, navegacion completa con teclado, `lang="es"`, `alt` en imagenes.
- `@media (prefers-reduced-motion: reduce)`: sin pulsos animados, solo cambio de color/borde.
- Responsivo: a < 900 px las columnas se apilan.
- Sin dependencias externas (sin CDN ni fuentes remotas).
- Texto en espanol, frases simples.
