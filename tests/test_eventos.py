import asyncio
import threading

import pytest
from pydantic import ValidationError

from app.eventos import EventBus


def test_emitir_valida_tipo_y_payload():
    bus = EventBus()
    with pytest.raises(ValueError):
        bus.emitir("inexistente", x=1)
    with pytest.raises(ValidationError):
        bus.emitir("agente_estado", agente="AgenteCoordinador", estado="dormido")
    ev = bus.emitir("narracion", texto="Hola")
    assert ev.id == 1 and ev.datos["nivel"] == "info"


def test_ids_crecientes_y_recientes_desde():
    bus = EventBus()
    for i in range(5):
        bus.emitir("narracion", texto=str(i))
    assert [e.id for e in bus.recientes(desde_id=3)] == [4, 5]


def test_historial_acotado():
    bus = EventBus(historial=3)
    for i in range(10):
        bus.emitir("narracion", texto=str(i))
    assert [e.id for e in bus.recientes()] == [8, 9, 10]


def test_sse_formato():
    bus = EventBus()
    ev = bus.emitir("narracion", texto="ñandú")
    s = ev.a_sse()
    assert s.startswith("id: 1\nevent: narracion\ndata: ") and s.endswith("\n\n")
    assert "ñandú" in s


def test_stream_entrega_backlog_y_eventos_desde_otro_hilo():
    bus = EventBus()
    bus.emitir("narracion", texto="previo")

    async def main():
        recibidos = []
        gen = bus.stream(desde_id=0)

        async def consumir():
            async for ev in gen:
                recibidos.append(ev.datos["texto"])
                if len(recibidos) == 3:
                    return

        tarea = asyncio.create_task(consumir())
        await asyncio.sleep(0.05)
        hilo = threading.Thread(
            target=lambda: [bus.emitir("narracion", texto=t) for t in ("a", "b")]
        )
        hilo.start()
        await asyncio.wait_for(tarea, timeout=2)
        hilo.join()
        return recibidos

    assert asyncio.run(main()) == ["previo", "a", "b"]
