(function () {
  "use strict";

  const SVG_NS = "http://www.w3.org/2000/svg";
  const TIPOS_EVENTO = [
    "sistema",
    "ronda_inicio",
    "agente_estado",
    "mensaje_acl",
    "medicion",
    "vision",
    "alerta",
    "narracion",
    "ronda_fin",
  ];

  const NODOS_CENTROS = {
    AgenteSupervisor: { x: 300, y: 52 },
    AgenteSensorResiduos: { x: 102, y: 165 },
    AgenteSensorAire: { x: 102, y: 285 },
    AgenteCoordinador: { x: 300, y: 225 },
    AgenteAlertas: { x: 498, y: 225 },
  };

  const MAX_BITACORA = 8;
  const MAX_HISTORIAL_MENSAJES = 100;
  const MAX_PULSOS_ACTIVOS = 2;
  const DURACION_ETIQUETA_MS = 2000;
  const DURACION_PULSO_MS = 650;

  const estado = {
    ultimoEventoId: 0,
    snapshotCargado: false,
    zonas: new Map(),
    agentes: new Map(),
    bitacora: [],
    historialMensajes: [],
    visionPorZona: new Map(),
    zonaActivaRonda: null,
    rondaActual: 0,
    agenteCajonAbierto: null,
    zonaCajonAbierta: null,
    ultimoFoco: null,
    pulsosEnCurso: [],
    eventSource: null,
  };

  const dom = {
    estadoConexion: document.getElementById("estado-conexion"),
    chipMotor: document.getElementById("chip-motor"),
    narrador: document.getElementById("narrador"),
    listaZonas: document.getElementById("lista-zonas"),
    listaBitacora: document.getElementById("lista-bitacora"),
    capaPulsos: document.getElementById("capa-pulsos"),
    cajonAgente: document.getElementById("cajon-agente"),
    cajonAgenteTitulo: document.getElementById("cajon-agente-titulo"),
    cajonAgenteEstado: document.getElementById("cajon-agente-estado"),
    cajonAgenteMensajes: document.getElementById("cajon-agente-mensajes"),
    cerrarCajonAgente: document.getElementById("cerrar-cajon-agente"),
    cajonZona: document.getElementById("cajon-zona"),
    cajonZonaTitulo: document.getElementById("cajon-zona-titulo"),
    cajonZonaImagen: document.getElementById("cajon-zona-imagen"),
    cajonZonaDatos: document.getElementById("cajon-zona-datos"),
    cajonZonaExplicacion: document.getElementById("cajon-zona-explicacion"),
    cerrarCajonZona: document.getElementById("cerrar-cajon-zona"),
  };

  function prefiereMovimientoReducido() {
    return typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function crearEl(tag, clase, texto) {
    const el = document.createElement(tag);
    if (clase) {
      el.className = clase;
    }
    if (texto !== undefined && texto !== null) {
      el.textContent = String(texto);
    }
    return el;
  }

  function crearSvg(tag, attrs) {
    const el = document.createElementNS(SVG_NS, tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        el.setAttribute(k, String(attrs[k]));
      });
    }
    return el;
  }

  function nombreCortoAgente(nombre) {
    return String(nombre || "").replace(/^Agente/, "");
  }

  function formatearHora(ts) {
    const fecha = typeof ts === "number" && ts > 0 ? new Date(ts * 1000) : new Date();
    const hh = String(fecha.getHours()).padStart(2, "0");
    const mm = String(fecha.getMinutes()).padStart(2, "0");
    const ss = String(fecha.getSeconds()).padStart(2, "0");
    return hh + ":" + mm + ":" + ss;
  }

  function limitarNumero(valor, min, max) {
    const num = Number(valor);
    if (Number.isNaN(num)) {
      return min;
    }
    return Math.min(max, Math.max(min, num));
  }

  function clasificarRiesgo(riesgo) {
    if (riesgo === null || riesgo === undefined || Number.isNaN(Number(riesgo))) {
      return {
        clase: "riesgo-pendiente",
        etiqueta: "Sin evaluar",
        texto: "Sin evaluar",
      };
    }
    const valor = Number(riesgo);
    const pct = valor.toFixed(1) + "%";
    if (valor < 40) {
      return {
        clase: "riesgo-bajo",
        etiqueta: "Bajo",
        texto: pct + " — Riesgo bajo",
      };
    }
    if (valor <= 70) {
      return {
        clase: "riesgo-medio",
        etiqueta: "Medio",
        texto: pct + " — Riesgo medio",
      };
    }
    return {
      clase: "riesgo-alto",
      etiqueta: "Alto",
      texto: pct + " — Riesgo alto",
    };
  }

  function actualizarEstadoConexion(conectado) {
    if (!dom.estadoConexion) {
      return;
    }
    if (conectado) {
      dom.estadoConexion.dataset.estado = "conectado";
      dom.estadoConexion.textContent = "EN VIVO";
    } else {
      dom.estadoConexion.dataset.estado = "reconectando";
      dom.estadoConexion.textContent = "reconectando...";
    }
  }

  function renderizarZonas() {
    if (!dom.listaZonas) {
      return;
    }
    const zonas = Array.from(estado.zonas.values());
    if (zonas.length === 0) {
      const vacio = crearEl(
        "p",
        "estado-vacio",
        "Sin datos de zonas aún. Esperando respuesta de /api/sala/snapshot o eventos SSE."
      );
      dom.listaZonas.replaceChildren(vacio);
      return;
    }

    const fragmento = document.createDocumentFragment();
    zonas.forEach(function (zona) {
      const item = crearEl("div", "zona-item");
      item.setAttribute("role", "listitem");

      const riesgoInfo = clasificarRiesgo(zona.riesgo);
      const esActiva = estado.zonaActivaRonda === zona.zona_id;
      const clasesBtn = "tarjeta-zona " + riesgoInfo.clase + (esActiva ? " zona-activa" : "");

      const btn = crearEl("button", clasesBtn);
      btn.type = "button";
      btn.dataset.zonaId = zona.zona_id;

      const llenado = limitarNumero(zona.nivel_llenado, 0, 100);
      btn.setAttribute(
        "aria-label",
        zona.nombre +
          ", llenado " +
          llenado.toFixed(0) +
          " por ciento, " +
          riesgoInfo.texto +
          ". Activar para ver análisis visual."
      );

      const filaSup = crearEl("span", "zona-fila-superior");
      const nombreSpan = crearEl("span", "zona-nombre", zona.nombre || zona.zona_id);
      const insignias = crearEl("span", "zona-insignias");
      if (esActiva) {
        const badgeRonda = crearEl(
          "span",
          "badge-ronda",
          estado.rondaActual > 0 ? "Ronda " + estado.rondaActual : "En ronda"
        );
        insignias.appendChild(badgeRonda);
      }
      const badgeRiesgo = crearEl("span", "badge-riesgo " + riesgoInfo.clase, riesgoInfo.texto);
      insignias.appendChild(badgeRiesgo);
      filaSup.appendChild(nombreSpan);
      filaSup.appendChild(insignias);

      const barraCont = crearEl("span", "zona-barra-contenedor");
      const pista = crearEl("span", "zona-barra-pista");
      const relleno = crearEl("span", "zona-barra-relleno " + riesgoInfo.clase);
      relleno.style.width = llenado.toFixed(1) + "%";
      pista.appendChild(relleno);
      const textoLlenado = crearEl("span", "zona-llenado-texto", "Llenado: " + llenado.toFixed(1) + "%");
      barraCont.appendChild(pista);
      barraCont.appendChild(textoLlenado);

      const metricas = crearEl("span", "zona-metricas");
      metricas.appendChild(
        crearEl("span", null, "Gases: " + Number(zona.concentracion_gases || 0).toFixed(0) + " ppm")
      );
      metricas.appendChild(
        crearEl("span", null, "Temp: " + Number(zona.temperatura || 0).toFixed(1) + " °C")
      );
      metricas.appendChild(
        crearEl("span", null, "Humedad: " + Number(zona.humedad || 0).toFixed(0) + "%")
      );

      btn.appendChild(filaSup);
      btn.appendChild(barraCont);
      btn.appendChild(metricas);

      if (zona.ultimaAlerta && zona.ultimaAlerta.mensaje) {
        const notaAlerta = crearEl("span", "zona-alerta-nota", zona.ultimaAlerta.mensaje);
        btn.appendChild(notaAlerta);
      }

      btn.addEventListener("click", function () {
        abrirCajonZona(zona.zona_id, btn);
      });

      item.appendChild(btn);
      fragmento.appendChild(item);
    });

    dom.listaZonas.replaceChildren(fragmento);
  }

  function actualizarNodoAgente(agente, estadoAgente, detalle) {
    const estadoNormalizado = estadoAgente || "reposo";
    estado.agentes.set(agente, {
      agente: agente,
      estado: estadoNormalizado,
      detalle: detalle || "",
    });

    const nodo = document.getElementById("nodo-" + agente);
    if (nodo) {
      nodo.setAttribute("data-estado", estadoNormalizado);
      nodo.setAttribute("aria-label", agente + ", estado: " + estadoNormalizado);
      const textoEstado = nodo.querySelector(".nodo-estado");
      if (textoEstado) {
        textoEstado.textContent = "Estado: " + estadoNormalizado;
      }
    }

    if (estado.agenteCajonAbierto === agente) {
      renderizarContenidoCajonAgente(agente);
    }
  }

  function renderizarBitacora() {
    if (!dom.listaBitacora) {
      return;
    }
    if (estado.bitacora.length === 0) {
      const li = crearEl(
        "li",
        "estado-vacio",
        "Aún no se han recibido mensajes FIPA-ACL."
      );
      dom.listaBitacora.replaceChildren(li);
      return;
    }

    const fragmento = document.createDocumentFragment();
    estado.bitacora.forEach(function (entrada) {
      const li = crearEl("li", "bitacora-item");
      const cu = String(entrada.caso_uso || "").trim();
      if (cu) {
        li.dataset.casoUso = cu;
      }
      const hora = crearEl("span", "bitacora-hora", formatearHora(entrada.ts));
      li.appendChild(hora);
      if (cu) {
        const claseCu = cu === "CU-02" ? "cu-02" : "cu-01";
        const badgeCu = crearEl("span", "bitacora-cu " + claseCu, cu);
        li.appendChild(badgeCu);
      }
      const perf = crearEl("span", "bitacora-perf", entrada.performativa || "ACL");
      const ruta = crearEl(
        "span",
        "bitacora-ruta",
        nombreCortoAgente(entrada.emisor) + " -> " + nombreCortoAgente(entrada.receptor)
      );
      const textoContenido = String(entrada.contenido || "");
      const contenido = crearEl(
        "span",
        "bitacora-contenido",
        textoContenido.length > 120 ? textoContenido.slice(0, 117) + "..." : textoContenido
      );
      li.appendChild(perf);
      li.appendChild(ruta);
      li.appendChild(contenido);
      fragmento.appendChild(li);
    });
    dom.listaBitacora.replaceChildren(fragmento);
  }

  function resolverRutaFlecha(emisor, receptor) {
    const candidatos = [
      { id: "flecha-" + emisor + "-" + receptor, invertir: false },
      { id: "flecha-" + nombreCortoAgente(emisor) + "-" + nombreCortoAgente(receptor), invertir: false },
      { id: "flecha-" + receptor + "-" + emisor, invertir: true },
      { id: "flecha-" + nombreCortoAgente(receptor) + "-" + nombreCortoAgente(emisor), invertir: true },
    ];

    for (let i = 0; i < candidatos.length; i += 1) {
      const linea = document.getElementById(candidatos[i].id);
      if (linea) {
        const x1 = Number(linea.getAttribute("x1"));
        const y1 = Number(linea.getAttribute("y1"));
        const x2 = Number(linea.getAttribute("x2"));
        const y2 = Number(linea.getAttribute("y2"));
        const lineaVisible = document.getElementById(
          candidatos[i].invertir
            ? "flecha-" + nombreCortoAgente(receptor) + "-" + nombreCortoAgente(emisor)
            : "flecha-" + nombreCortoAgente(emisor) + "-" + nombreCortoAgente(receptor)
        );
        return {
          linea: lineaVisible || linea,
          x1: candidatos[i].invertir ? x2 : x1,
          y1: candidatos[i].invertir ? y2 : y1,
          x2: candidatos[i].invertir ? x1 : x2,
          y2: candidatos[i].invertir ? y1 : y2,
        };
      }
    }

    const origen = NODOS_CENTROS[emisor] || { x: 300, y: 180 };
    const destino = NODOS_CENTROS[receptor] || { x: 300, y: 180 };
    return {
      linea: null,
      x1: origen.x,
      y1: origen.y,
      x2: destino.x,
      y2: destino.y,
    };
  }

  function limpiarPulso(pulsoObj) {
    if (!pulsoObj || pulsoObj.limpiado) {
      return;
    }
    pulsoObj.limpiado = true;
    if (pulsoObj.rafId) {
      cancelAnimationFrame(pulsoObj.rafId);
    }
    if (pulsoObj.timeoutId) {
      clearTimeout(pulsoObj.timeoutId);
    }
    if (pulsoObj.circulo && pulsoObj.circulo.parentNode) {
      pulsoObj.circulo.parentNode.removeChild(pulsoObj.circulo);
    }
    if (pulsoObj.etiqueta && pulsoObj.etiqueta.parentNode) {
      pulsoObj.etiqueta.parentNode.removeChild(pulsoObj.etiqueta);
    }
    if (pulsoObj.linea) {
      pulsoObj.linea.removeAttribute("data-activa");
    }
    const idx = estado.pulsosEnCurso.indexOf(pulsoObj);
    if (idx !== -1) {
      estado.pulsosEnCurso.splice(idx, 1);
    }
  }

  function animarPulsoACL(datos) {
    if (!dom.capaPulsos || !datos) {
      return;
    }

    while (estado.pulsosEnCurso.length >= MAX_PULSOS_ACTIVOS) {
      limpiarPulso(estado.pulsosEnCurso[0]);
    }

    const ruta = resolverRutaFlecha(datos.emisor, datos.receptor);
    if (ruta.linea) {
      ruta.linea.setAttribute("data-activa", "true");
    }

    const mx = (ruta.x1 + ruta.x2) / 2;
    const my = (ruta.y1 + ruta.y2) / 2;
    const textoPerf = String(datos.performativa || "ACL").slice(0, 14);
    const anchoEtiqueta = Math.max(54, textoPerf.length * 7.5 + 14);

    const etiqueta = crearSvg("g", { class: "etiqueta-performativa" });
    const rect = crearSvg("rect", {
      class: "etiqueta-perf-caja",
      x: mx - anchoEtiqueta / 2,
      y: my - 12,
      width: anchoEtiqueta,
      height: 24,
      rx: 4,
    });
    const texto = crearSvg("text", {
      class: "etiqueta-perf-texto",
      x: mx,
      y: my,
    });
    texto.textContent = textoPerf;
    etiqueta.appendChild(rect);
    etiqueta.appendChild(texto);
    dom.capaPulsos.appendChild(etiqueta);

    const pulsoObj = {
      circulo: null,
      etiqueta: etiqueta,
      linea: ruta.linea,
      rafId: null,
      timeoutId: null,
      limpiado: false,
    };

    if (!prefiereMovimientoReducido()) {
      const circulo = crearSvg("circle", {
        class: "pulso-acl",
        cx: ruta.x1,
        cy: ruta.y1,
        r: 6,
      });
      dom.capaPulsos.appendChild(circulo);
      pulsoObj.circulo = circulo;

      const inicio = performance.now();
      function paso(ahora) {
        if (pulsoObj.limpiado) {
          return;
        }
        const t = Math.min(1, (ahora - inicio) / DURACION_PULSO_MS);
        circulo.setAttribute("cx", String(ruta.x1 + (ruta.x2 - ruta.x1) * t));
        circulo.setAttribute("cy", String(ruta.y1 + (ruta.y2 - ruta.y1) * t));
        if (t < 1) {
          pulsoObj.rafId = requestAnimationFrame(paso);
        } else if (circulo.parentNode) {
          circulo.parentNode.removeChild(circulo);
        }
      }
      pulsoObj.rafId = requestAnimationFrame(paso);
    }

    pulsoObj.timeoutId = setTimeout(function () {
      limpiarPulso(pulsoObj);
    }, DURACION_ETIQUETA_MS);

    estado.pulsosEnCurso.push(pulsoObj);
  }

  function procesarEvento(evento, opciones) {
    if (!evento || !evento.tipo) {
      return;
    }
    const animar = !opciones || opciones.animar !== false;
    const datos = evento.datos || {};
    if (typeof evento.id === "number" && evento.id > estado.ultimoEventoId) {
      estado.ultimoEventoId = evento.id;
    }

    switch (evento.tipo) {
      case "sistema": {
        if (dom.chipMotor) {
          const motor = datos.motor || "LangGraph";
          const version = datos.version_langgraph ? " " + datos.version_langgraph : "";
          dom.chipMotor.textContent = "Motor: " + motor + version;
        }
        break;
      }

      case "ronda_inicio": {
        estado.rondaActual = Number(datos.ronda) || 0;
        estado.zonaActivaRonda = datos.zona_id || null;
        renderizarZonas();
        break;
      }

      case "agente_estado": {
        if (datos.agente) {
          actualizarNodoAgente(datos.agente, datos.estado, datos.detalle);
        }
        break;
      }

      case "mensaje_acl": {
        const entrada = {
          msg_id: datos.msg_id || "",
          performativa: datos.performativa || "",
          emisor: datos.emisor || "",
          receptor: datos.receptor || "",
          contenido: datos.contenido || "",
          conversation_id: datos.conversation_id || "",
          protocolo: datos.protocolo || "",
          ronda: datos.ronda || 0,
          caso_uso: datos.caso_uso || "",
          ts: evento.ts,
        };
        estado.bitacora.unshift(entrada);
        if (estado.bitacora.length > MAX_BITACORA) {
          estado.bitacora.length = MAX_BITACORA;
        }
        estado.historialMensajes.unshift(entrada);
        if (estado.historialMensajes.length > MAX_HISTORIAL_MENSAJES) {
          estado.historialMensajes.length = MAX_HISTORIAL_MENSAJES;
        }
        renderizarBitacora();
        if (animar) {
          animarPulsoACL(entrada);
        }
        if (
          estado.agenteCajonAbierto &&
          (estado.agenteCajonAbierto === entrada.emisor ||
            estado.agenteCajonAbierto === entrada.receptor)
        ) {
          renderizarContenidoCajonAgente(estado.agenteCajonAbierto);
        }
        break;
      }

      case "medicion": {
        if (datos.zona_id) {
          const actual = estado.zonas.get(datos.zona_id) || {
            zona_id: datos.zona_id,
            nombre: datos.zona_id,
          };
          actual.nivel_llenado = datos.nivel_llenado;
          actual.concentracion_gases = datos.concentracion_gases;
          actual.temperatura = datos.temperatura;
          actual.humedad = datos.humedad;
          if (datos.riesgo !== undefined) {
            actual.riesgo = datos.riesgo;
          }
          estado.zonas.set(datos.zona_id, actual);
          renderizarZonas();
          if (estado.zonaCajonAbierta === datos.zona_id) {
            renderizarContenidoCajonZona(datos.zona_id);
          }
        }
        break;
      }

      case "vision": {
        if (datos.zona_id) {
          estado.visionPorZona.set(datos.zona_id, datos);
          if (estado.zonaCajonAbierta === datos.zona_id) {
            renderizarContenidoCajonZona(datos.zona_id);
          }
        }
        break;
      }

      case "alerta": {
        if (datos.zona_id) {
          const z = estado.zonas.get(datos.zona_id);
          if (z) {
            z.ultimaAlerta = {
              alerta_id: datos.alerta_id,
              estado: datos.estado,
              mensaje: datos.mensaje,
            };
            renderizarZonas();
          }
        }
        break;
      }

      case "narracion": {
        if (dom.narrador && datos.texto) {
          dom.narrador.textContent = datos.texto;
          dom.narrador.dataset.nivel = datos.nivel || "info";
        }
        break;
      }

      case "ronda_fin": {
        if (datos.zona_id && datos.riesgo !== undefined && datos.riesgo !== null) {
          const z = estado.zonas.get(datos.zona_id);
          if (z) {
            z.riesgo = datos.riesgo;
          }
        }
        if (Array.isArray(datos.ranking)) {
          datos.ranking.forEach(function (item) {
            if (item && item.zona_id && estado.zonas.has(item.zona_id) && item.riesgo !== undefined) {
              estado.zonas.get(item.zona_id).riesgo = item.riesgo;
            }
          });
        }
        if (estado.zonaActivaRonda === datos.zona_id) {
          estado.zonaActivaRonda = null;
        }
        renderizarZonas();
        break;
      }

      default:
        break;
    }
  }

  function renderizarContenidoCajonAgente(agente) {
    const info = estado.agentes.get(agente) || {
      agente: agente,
      estado: "reposo",
      detalle: "",
    };
    dom.cajonAgenteTitulo.textContent = agente;

    const pEstado = crearEl("p", "cajon-dato-linea", "Estado actual: " + info.estado);
    const pDetalle = crearEl(
      "p",
      "cajon-dato-linea",
      "Detalle: " + (info.detalle ? info.detalle : "Sin actividad en curso.")
    );
    dom.cajonAgenteEstado.replaceChildren(pEstado, pDetalle);

    const propios = estado.historialMensajes
      .filter(function (m) {
        return m.emisor === agente || m.receptor === agente;
      })
      .slice(0, 5);

    if (propios.length === 0) {
      const vacio = crearEl(
        "li",
        "estado-vacio",
        "No hay mensajes recientes para este agente."
      );
      dom.cajonAgenteMensajes.replaceChildren(vacio);
      return;
    }

    const fragmento = document.createDocumentFragment();
    propios.forEach(function (m) {
      const li = crearEl("li", "cajon-mensaje-item");
      const meta = crearEl(
        "span",
        "cajon-mensaje-meta",
        formatearHora(m.ts) +
          " · " +
          m.performativa +
          " · " +
          nombreCortoAgente(m.emisor) +
          " -> " +
          nombreCortoAgente(m.receptor)
      );
      const texto = crearEl("span", "cajon-mensaje-texto", m.contenido || "");
      li.appendChild(meta);
      li.appendChild(texto);
      fragmento.appendChild(li);
    });
    dom.cajonAgenteMensajes.replaceChildren(fragmento);
  }

  function abrirCajonAgente(agente, origen) {
    cerrarCajones(false);
    estado.ultimoFoco = origen || document.activeElement;
    estado.agenteCajonAbierto = agente;
    renderizarContenidoCajonAgente(agente);
    dom.cajonAgente.hidden = false;
    dom.cerrarCajonAgente.focus();
  }

  function renderizarContenidoCajonZona(zonaId) {
    const zona = estado.zonas.get(zonaId) || { zona_id: zonaId, nombre: zonaId };
    const vision = estado.visionPorZona.get(zonaId);
    dom.cajonZonaTitulo.textContent = zona.nombre || zonaId;

    if (!vision) {
      const sinImg = crearEl(
        "p",
        "estado-vacio",
        "Aún no ha llegado análisis visual para esta zona."
      );
      dom.cajonZonaImagen.replaceChildren(sinImg);
    } else {
      const srcImagen = vision.imagen_anotada_url || vision.imagen_url;

      if (!srcImagen) {
        const sinUrl = crearEl(
          "p",
          "estado-vacio",
          "El evento de visión no incluyó URL de imagen."
        );
        dom.cajonZonaImagen.replaceChildren(sinUrl);
      } else {
        const img = document.createElement("img");
        img.className = "cajon-visor-img";
        img.src = srcImagen;
        img.alt =
          "Imagen de muestra analizada del contenedor en " +
          (zona.nombre || zonaId) +
          ", llenado visual " +
          Number(vision.porcentaje_llenado || 0).toFixed(0) +
          "%";
        dom.cajonZonaImagen.replaceChildren(img);
      }
    }

    const riesgoInfo = clasificarRiesgo(zona.riesgo);
    const fragmentosDatos = [];
    if (vision) {
      const motorLabel = vision.motor === "gemini" ? "IA Gemini" : "Análisis local HSV";
      fragmentosDatos.push(
        crearEl(
          "p",
          "cajon-dato-linea",
          "Llenado visual: " +
            Number(vision.porcentaje_llenado || 0).toFixed(1) +
            "% · Bolsas detectadas: " +
            Number(vision.bolsas || 0)
        )
      );
      fragmentosDatos.push(crearEl("p", "cajon-dato-linea", "Motor de visión: " + motorLabel));
    }
    fragmentosDatos.push(crearEl("p", "cajon-dato-linea", "Riesgo actual: " + riesgoInfo.texto));
    fragmentosDatos.push(
      crearEl(
        "p",
        "cajon-dato-linea",
        "Sensores: llenado " +
          Number(zona.nivel_llenado || 0).toFixed(1) +
          "%, gases " +
          Number(zona.concentracion_gases || 0).toFixed(0) +
          " ppm, temp " +
          Number(zona.temperatura || 0).toFixed(1) +
          " °C, humedad " +
          Number(zona.humedad || 0).toFixed(0) +
          "%"
      )
    );
    dom.cajonZonaDatos.replaceChildren.apply(dom.cajonZonaDatos, fragmentosDatos);

    dom.cajonZonaExplicacion.textContent =
      vision && vision.explicacion
        ? vision.explicacion
        : "Esperando explicación del análisis visual desde el servidor.";
  }

  function abrirCajonZona(zonaId, origen) {
    cerrarCajones(false);
    estado.ultimoFoco = origen || document.activeElement;
    estado.zonaCajonAbierta = zonaId;
    renderizarContenidoCajonZona(zonaId);
    dom.cajonZona.hidden = false;
    dom.cerrarCajonZona.focus();
  }

  function cerrarCajones(restaurarFoco) {
    const habiaAbierto = !dom.cajonAgente.hidden || !dom.cajonZona.hidden;
    dom.cajonAgente.hidden = true;
    dom.cajonZona.hidden = true;
    estado.agenteCajonAbierto = null;
    estado.zonaCajonAbierta = null;

    if (restaurarFoco && habiaAbierto && estado.ultimoFoco && typeof estado.ultimoFoco.focus === "function") {
      estado.ultimoFoco.focus();
      estado.ultimoFoco = null;
    }
  }

  function aplicarSnapshot(snap) {
    if (!snap || typeof snap !== "object") {
      return;
    }
    estado.snapshotCargado = true;
    if (typeof snap.ultimo_evento_id === "number") {
      estado.ultimoEventoId = snap.ultimo_evento_id;
    }

    if (snap.sistema && dom.chipMotor) {
      const version = snap.sistema.version_langgraph ? " " + snap.sistema.version_langgraph : "";
      dom.chipMotor.textContent = "Motor: " + (snap.sistema.motor || "LangGraph") + version;
    }

    if (Array.isArray(snap.zonas)) {
      snap.zonas.forEach(function (z) {
        if (z && z.zona_id) {
          estado.zonas.set(z.zona_id, z);
        }
      });
      renderizarZonas();
    }

    if (Array.isArray(snap.agentes)) {
      snap.agentes.forEach(function (ag) {
        if (ag && ag.agente) {
          actualizarNodoAgente(ag.agente, ag.estado, ag.detalle);
        }
      });
    }

    if (Array.isArray(snap.recientes)) {
      snap.recientes.forEach(function (ev) {
        procesarEvento(ev, { animar: false });
      });
    }
  }

  function cargarSnapshot() {
    return fetch("/api/sala/snapshot", {
      headers: { Accept: "application/json" },
    })
      .then(function (resp) {
        if (!resp.ok) {
          throw new Error("HTTP " + resp.status);
        }
        return resp.json();
      })
      .then(function (snap) {
        aplicarSnapshot(snap);
        return snap;
      });
  }

  function parsearEventoSSE(tipoPorDefecto, event) {
    const bruto = JSON.parse(event.data);
    if (bruto && typeof bruto === "object" && "tipo" in bruto && "datos" in bruto) {
      return bruto;
    }
    return {
      id: Number(event.lastEventId) || 0,
      tipo: tipoPorDefecto,
      ts: Date.now() / 1000,
      datos: bruto,
    };
  }

  function conectarSSE(desdeId) {
    if (estado.eventSource) {
      estado.eventSource.close();
    }
    const url = "/api/stream?desde=" + encodeURIComponent(String(desdeId || 0));
    const es = new EventSource(url);
    estado.eventSource = es;

    es.onopen = function () {
      actualizarEstadoConexion(true);
      if (!estado.snapshotCargado) {
        cargarSnapshot().catch(function () {
          // El servidor aun puede estar inicializando; el stream seguira vivo.
        });
      }
    };

    es.onerror = function () {
      actualizarEstadoConexion(false);
    };

    TIPOS_EVENTO.forEach(function (tipo) {
      es.addEventListener(tipo, function (ev) {
        actualizarEstadoConexion(true);
        try {
          const evento = parsearEventoSSE(tipo, ev);
          procesarEvento(evento, { animar: true });
        } catch (_err) {
          // Ignorar payload malformado sin romper el observador.
        }
      });
    });

    es.onmessage = function (ev) {
      actualizarEstadoConexion(true);
      try {
        const evento = parsearEventoSSE("narracion", ev);
        procesarEvento(evento, { animar: true });
      } catch (_err) {
        // Ignorar mensaje sin estructura JSON valida.
      }
    };
  }

  function enlazarEventosUI() {
    const nodos = document.querySelectorAll(".nodo-agente");
    nodos.forEach(function (nodo) {
      const agente = nodo.dataset.agente;
      nodo.addEventListener("click", function () {
        abrirCajonAgente(agente, nodo);
      });
      nodo.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          abrirCajonAgente(agente, nodo);
        }
      });
    });

    dom.cerrarCajonAgente.addEventListener("click", function () {
      cerrarCajones(true);
    });
    dom.cerrarCajonZona.addEventListener("click", function () {
      cerrarCajones(true);
    });

    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") {
        cerrarCajones(true);
      }
    });
  }

  function iniciarSala() {
    actualizarEstadoConexion(false);
    renderizarZonas();
    renderizarBitacora();
    enlazarEventosUI();

    cargarSnapshot()
      .catch(function () {
        actualizarEstadoConexion(false);
      })
      .finally(function () {
        conectarSSE(estado.ultimoEventoId);
      });
  }

  iniciarSala();
})();
