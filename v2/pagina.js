(function () {
  "use strict";

  function agregarBotonesCopia() {
    if (!navigator.clipboard || typeof navigator.clipboard.writeText !== "function") {
      return;
    }

    const bloques = document.querySelectorAll(".bloque-codigo");
    bloques.forEach(function (bloque) {
      const code = bloque.querySelector("code");
      if (!code) {
        return;
      }

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn-copiar";
      btn.textContent = "Copiar comando";

      btn.addEventListener("click", function () {
        const texto = code.textContent || "";
        navigator.clipboard.writeText(texto).then(
          function () {
            btn.textContent = "Copiado";
            setTimeout(function () {
              btn.textContent = "Copiar comando";
            }, 2000);
          },
          function () {
            btn.textContent = "No se pudo copiar";
          }
        );
      });

      bloque.appendChild(btn);
    });
  }

  agregarBotonesCopia();
})();
