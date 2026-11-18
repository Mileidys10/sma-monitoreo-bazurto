(function () {
  "use strict";

  const estadoEl = document.getElementById("estado-grafo-motor");
  const grafoEl = document.getElementById("mermaid-grafo-motor");

  async function cargarGrafoMotor() {
    if (!grafoEl) {
      return;
    }
    try {
      const resp = await fetch("/api/motor", {
        headers: { Accept: "application/json" },
      });
      if (!resp.ok) {
        throw new Error("HTTP " + resp.status);
      }
      const data = await resp.json();
      if (!data || !data.mermaid_graph) {
        throw new Error("Respuesta sin campo mermaid_graph");
      }
      grafoEl.textContent = data.mermaid_graph;
      if (estadoEl) {
        const motor = data.motor || "LangGraph";
        const version = data.version_langgraph ? " " + data.version_langgraph : "";
        const checkpointer = data.checkpointer ? " · Checkpointer: " + data.checkpointer : "";
        estadoEl.dataset.estado = "ok";
        estadoEl.textContent = "Motor activo: " + motor + version + checkpointer;
      }
    } catch (err) {
      grafoEl.classList.remove("mermaid");
      grafoEl.textContent = "Grafo del motor no disponible en este momento.";
      if (estadoEl) {
        estadoEl.dataset.estado = "error";
        estadoEl.textContent = "No se pudo consultar /api/motor (" + (err && err.message ? err.message : "sin conexión") + ").";
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
