(function () {
  "use strict";

  const estadoEl = document.getElementById("estado-grafo-motor");
  const grafoEl = document.getElementById("mermaid-grafo-motor");
  const RUTA_GRAFO = "../assets/grafo_motor.mmd";

  async function cargarGrafoMotor() {
    if (!grafoEl) {
      return;
    }
    try {
      const resp = await fetch(RUTA_GRAFO, {
        headers: { Accept: "text/plain" },
      });
      if (!resp.ok) {
        throw new Error("HTTP " + resp.status);
      }
      const mmdText = (await resp.text()).trim();
      if (!mmdText) {
        throw new Error("Archivo de grafo vacío");
      }
      grafoEl.textContent = mmdText;
      if (estadoEl) {
        estadoEl.dataset.estado = "ok";
        estadoEl.textContent = "Motor: LangGraph 1.2.22";
      }
    } catch (err) {
      grafoEl.classList.remove("mermaid");
      grafoEl.textContent = "No se pudo cargar el grafo estático del motor (" + RUTA_GRAFO + ").";
      if (estadoEl) {
        estadoEl.dataset.estado = "error";
        estadoEl.textContent =
          "Error al cargar " + RUTA_GRAFO + ": " + (err && err.message ? err.message : "recurso no disponible");
      }
    }
  }

  async function iniciarDiagramas() {
    if (typeof window.mermaid === "undefined") {
      if (estadoEl) {
        estadoEl.dataset.estado = "error";
        estadoEl.textContent = "Error al cargar la librería local de Mermaid.";
      }
      return;
    }

    window.mermaid.initialize({
      theme: "neutral",
      startOnLoad: false,
      securityLevel: "strict",
    });

    await cargarGrafoMotor();
    await window.mermaid.run();
  }

  iniciarDiagramas();
})();
