import tempfile
from pathlib import Path

from app.autonomo import LoopAutonomo
from app.eventos import EventBus
from app.models_masml import SMAMonitoreoBazurto


def _loop(tmp_path: Path, **kw):
    sma = SMAMonitoreoBazurto(db_path=str(tmp_path / "auto.db"))
    bus = EventBus()
    return LoopAutonomo(sma, bus, ritmo_s=0, semilla=7, **kw), bus, sma


def _quieto(loop: LoopAutonomo) -> LoopAutonomo:
    loop.entorno.paso_llenado = (0.0, 0.0)  # entorno estable: los niveles sembrados no cambian entre rondas
    loop.prob_confirma = 1.0
    return loop


def test_zona_bajo_umbral_no_genera_alerta(tmp_path: Path) -> None:
    loop, bus, _ = _loop(tmp_path)
    _quieto(loop).ejecutar_ronda()  # ronda 1 = zona_2 con 16.9 %: bajo el umbral del 80 %
    ev = bus.recientes()
    tipos = [e.tipo for e in ev]
    assert tipos[0] == "ronda_inicio" and tipos[-1] == "ronda_fin"
    acl = [e.datos for e in ev if e.tipo == "mensaje_acl"]
    assert {m["performativa"] for m in acl} == {"INFORM"}  # solo el INFORM del sensor de aire
    assert all(m["emisor"] == "AgenteSensorAire" for m in acl)
    assert "alerta" not in tipos
    assert any("no hace falta alertar" in e.datos["texto"] for e in ev if e.tipo == "narracion")
    assert not any(e.datos.get("agente") == "AgenteAlertas" for e in ev if e.tipo == "agente_estado")


def test_zona_persistente_sobre_umbral_dispara_cadena_completa(tmp_path: Path) -> None:
    loop, bus, _ = _loop(tmp_path)
    _quieto(loop)
    loop.ejecutar_ronda()
    loop.ejecutar_ronda()  # ronda 2 = zona_3 (82 % sembrado, 30 min): persiste
    ev = bus.recientes()
    tipos = [e.tipo for e in ev]
    assert {"agente_estado", "mensaje_acl", "vision", "medicion", "alerta", "narracion"} <= set(tipos)
    acl = [e.datos for e in ev if e.tipo == "mensaje_acl" and e.datos["ronda"] == 2]
    assert acl[0]["emisor"] == "AgenteSensorResiduos" and acl[0]["receptor"] == "AgenteCoordinador"
    assert {m["performativa"] for m in acl} >= {"INFORM", "REQUEST", "AGREE", "INFORM-DONE"}


def test_alerta_activa_en_la_zona_rechaza_la_segunda_con_refuse(tmp_path: Path) -> None:
    loop, bus, sma = _loop(tmp_path)
    _quieto(loop)
    primera = loop.runner.run(zona_id="zona_3", comunidad_confirma=True)
    assert primera["estado_final_checkpoint"]["resultado_acl"] == "INFORM-DONE"
    assert sma.db.get_active_alerta_zona("zona_3") is not None
    segunda = loop.runner.run(zona_id="zona_3", comunidad_confirma=True)
    assert segunda["estado_final_checkpoint"]["resultado_acl"] == "REFUSE"


def test_camion_recolector_cierra_la_alerta_activa(tmp_path: Path) -> None:
    loop, bus, sma = _loop(tmp_path)
    _quieto(loop)
    loop.runner.run(zona_id="zona_3", comunidad_confirma=True)
    assert sma.db.get_active_alerta_zona("zona_3") is not None
    loop.entorno.programar_recoleccion("zona_3", en_rondas=2)
    loop.entorno.avanzar()
    assert sma.db.get_active_alerta_zona("zona_3") is not None  # el camion aun no llega
    assert loop.entorno.avanzar() == ["Sector Pescaderia y Acopio Central"]
    assert sma.db.get_active_alerta_zona("zona_3") is None
    assert sma.db.get_zona("zona_3")["nivel_llenado_contenedores"] < 40
    nueva = loop.runner.run(zona_id="zona_3", comunidad_confirma=True)
    assert nueva["estado_final_checkpoint"]["resultado_acl"] is None  # ya bajo el umbral: sin evento ni alerta


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


def test_entorno_evoluciona_sin_vaciarse_solo(tmp_path: Path) -> None:
    loop, bus, sma = _loop(tmp_path)
    antes = {z["zona_id"]: z["nivel_llenado_contenedores"] for z in sma.db.list_zonas()}
    assert loop.entorno.avanzar() == []
    despues = {z["zona_id"]: z["nivel_llenado_contenedores"] for z in sma.db.list_zonas()}
    assert all(despues[k] >= antes[k] for k in antes) and any(despues[k] > antes[k] for k in antes)
    sma.db.update_zona("zona_3", nivel_llenado_contenedores=99.5)
    loop.entorno.avanzar()
    assert sma.db.get_zona("zona_3")["nivel_llenado_contenedores"] == 100.0  # tope: no se vacia solo


def test_alerta_confirmada_programa_camion_y_la_siguiente_visita_es_refuse(tmp_path: Path) -> None:
    loop, bus, sma = _loop(tmp_path)
    _quieto(loop)
    loop.ejecutar_ronda()
    loop.ejecutar_ronda()  # ronda 2 = zona_3: alerta confirmada
    assert "zona_3" in loop.entorno.pendientes
    loop.ejecutar_ronda()
    loop.ejecutar_ronda()
    loop.ejecutar_ronda()  # ronda 5 = zona_3 otra vez: el camion aun no llego
    acl = [e.datos["performativa"] for e in bus.recientes() if e.tipo == "mensaje_acl" and e.datos["ronda"] == 5]
    assert "REFUSE" in acl


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


def test_cada_ronda_publica_la_medicion_de_todas_las_zonas(tmp_path: Path) -> None:
    loop, bus, sma = _loop(tmp_path)
    _quieto(loop).ejecutar_ronda()
    med = [e.datos for e in bus.recientes() if e.tipo == "medicion"]
    assert {m["zona_id"] for m in med} == {z["zona_id"] for z in sma.db.list_zonas()}
    fin = [e.datos for e in bus.recientes() if e.tipo == "ronda_fin"][0]
    riesgo_ranking = {r["zona_id"]: r["riesgo"] for r in fin["ranking"]}
    assert all(m["riesgo"] == riesgo_ranking[m["zona_id"]] for m in med)  # nivel y riesgo del mismo instante
