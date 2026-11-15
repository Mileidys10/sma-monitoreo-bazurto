# SMAMonitoreoBazurto

Sistema Multiagente de Monitoreo Ambiental para el Mercado de Bazurto (`SMAMonitoreoBazurto`), modelado 1:1 con **MAS-ML** y **FIPA-ACL**.

## ¿Por qué 100% Python + FastAPI + SQLite en lugar de depender de n8n?

El profesor advirtió que en **n8n** el manejo de persistencia entre ejecuciones es complejo. En este Sistema Multiagente hay dos agentes **Basados en Modelos**:
- `AgenteSensorResiduos` (`estadoInterno`: `nivel`, `tiempoSobreLimite`, `ritmoLlenado`, `estado_visual`, `bolsas_suelo`).
- `AgenteSensorAire` (`historialMediciones`: serie histórica de CO₂, temperatura y humedad para `detectarAumentoProgresivo()`).

Esta aplicación web en **Python + FastAPI + SQLite (`bazurto_sma.db`)** ejecuta todos los agentes de forma autónoma con persistencia real en disco y sin necesidad de instalar n8n. (Adicionalmente se conserva `n8n_workflow_sma_bazurto.json` por si se desea orquestar vía HTTP).

## Funcionalidades Clave para la Sustentación

1. **Cámara y Visión por Computador Real (`AgenteSensorResiduos.analizarImagenes()`)**:
   - No es necesario desplazarse al Mercado de Bazurto.
   - El módulo `app/vision_analyzer.py` (con `Pillow`) analiza píxel a píxel las Regiones de Interés (ROI) del contenedor y del suelo perimetral sobre:
     - 3 escenas precargadas (`contenedor_limpio.png`, `contenedor_medio.png`, `contenedor_critico.png`),
     - cualquier fotografía subida desde el computador, o
     - una captura en vivo desde la webcam de la laptop.
   - Devuelve una imagen anotada con *Bounding Boxes* y sincroniza `nivelLlenadoContenedores` en `MercadoBazurto`.
2. **Panel Interactivo de Comunidad / Líder de Zona (`EmisorAlertas`)**:
   - Al ejecutar `CU-01` en modo interactivo, la alerta llega en vivo al Panel de Comunidad en estado `PENDIENTE_COMUNIDAD`.
   - Desde pantalla puedes elegir **Confirmar Recepción (`ACK` → `INFORM-DONE`)** o **Simular No Respuesta (`FAILURE`)** y encadenar directamente la auditoría de `AgenteSupervisor` en `CU-02`.

## Cómo Ejecutar el Proyecto

En PowerShell, dentro de la carpeta raíz del proyecto (`sma-monitoreo-bazurto`):

```powershell
.\.venv\Scripts\python -m pytest -v
.\.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

Luego abrir en el navegador: `http://localhost:8000`
