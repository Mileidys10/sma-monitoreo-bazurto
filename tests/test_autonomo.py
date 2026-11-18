import tempfile
from pathlib import Path

from app.autonomo import LoopAutonomo
from app.eventos import EventBus
from app.models_masml import SMAMonitoreoBazurto


def _loop(tmp_path: Path, **kw):
    sma = SMAMonitoreoBazurto(db_path=str(tmp_path / "auto.db"))
    bus = EventBus()
    return LoopAutonomo(sma, bus, ritmo_s=0, semilla=7, **kw), bus, sma


def test_ronda_publica_eventos_reales_en_orden(tmp_path: Path) -> None:
    loop, bus, _ = _loop(tmp_path)
    loop.ejecutar_ronda()
    tipos = [e.tipo for e in bus.recientes()]
    assert tipos[0] == "ronda_inicio" and tipos[-1] == "ronda_fin"
    assert {"agente_estado", "mensaje_acl", "vision", "medicion", "alerta", "narracion"} <= set(tipos)
    acl = [e.datos for e in bus.recientes() if e.tipo == "mensaje_acl"]
    assert acl[0]["emisor"] == "AgenteSensorResiduos" and acl[0]["receptor"] == "AgenteCoordinador"
    assert {m["performativa"] for m in acl} >= {"INFORM", "REQUEST", "AGREE", "INFORM-DONE"}


def test_riesgo_en_escala_0_100_y_ranking(tmp_path: Path) -> None:
    loop, bus, _ = _loop(tmp_path)
    loop.ejecutar_ronda()
    fin = [e.datos for e in bus.recientes() if e.tipo == "ronda_fin"][0]
    assert 0 <= fin["riesgo"] <= 100
    assert fin["ranking"] and all(0 <= r["riesgo"] <= 100 for r in fin["ranking"])


def test_rondas_rotan_zonas_y_guardan_imagen_anotada(tmp_path: Path) -> None:
    loop, bus, sma = _loop(tmp_path)
    for _ in range(3):
        loop.ejecutar_ronda()
    zonas = [e.datos["zona_id"] for e in bus.recientes() if e.tipo == "ronda_inicio"]
    assert len(set(zonas)) == 3
    assert all(png.startswith(b"\x89PNG") for png in loop.imagenes.values())
    vis = [e.datos for e in bus.recientes() if e.tipo == "vision"][0]
    assert vis["imagen_anotada_url"].startswith("/api/sala/vision/") and vis["cajas"] == []


def test_entorno_evoluciona_y_camion_recolecta(tmp_path: Path) -> None:
    loop, bus, sma = _loop(tmp_path)
    antes = {z["zona_id"]: z["nivel_llenado_contenedores"] for z in sma.db.list_zonas()}
    loop.entorno.avanzar()
    despues = {z["zona_id"]: z["nivel_llenado_contenedores"] for z in sma.db.list_zonas()}
    assert any(despues[k] != antes[k] for k in antes)
    sma.db.update_zona("zona_3", nivel_llenado_contenedores=98.9)
    recolectadas = loop.entorno.avanzar()
    assert "Sector Pescaderia y Acopio Central" in recolectadas
    assert sma.db.get_zona("zona_3")["nivel_llenado_contenedores"] < 40


def test_acl_fuera_del_bucle_no_se_transmite(tmp_path: Path) -> None:
    loop, bus, sma = _loop(tmp_path)
    sma.ejecutar_caso_uso_1(zona_id="zona_3", comunidad_confirma=True)
    assert [e for e in bus.recientes() if e.tipo == "mensaje_acl"] == []


def test_snapshot_forma_contrato(tmp_path: Path) -> None:
    loop, bus, _ = _loop(tmp_path)
    loop.ejecutar_ronda()
    snap = loop.snapshot()
    assert snap["ultimo_evento_id"] == bus.recientes()[-1].id
    assert len(snap["agentes"]) == 5 and snap["zonas"]
    assert any(z["riesgo"] is not None for z in snap["zonas"])
    assert snap["recientes"][-1]["tipo"] == "ronda_fin"
