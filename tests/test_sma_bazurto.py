"""Pruebas automatizadas para los 21 métodos MAS-ML, FIPA-ACL y los 2 Casos de Uso."""

from pathlib import Path
from fastapi.testclient import TestClient

from app.main import STATIC_DIR, app
from app.models_masml import SMAMonitoreoBazurto
from app.vision_analyzer import analizar_imagen_contenedor, ensure_sample_images


def test_cu01_exito_confirmada(tmp_path: Path) -> None:
    db_file = tmp_path / "test_cu01.db"
    sma = SMAMonitoreoBazurto(db_path=str(db_file))
    res = sma.ejecutar_caso_uso_1(zona_id="zona_3", forzar_duplicada=False, comunidad_confirma=True)

    assert res["caso_uso"] == "CU-01"
    assert res["resultado_acl"] == "INFORM-DONE"
    assert res["riesgo"] > 0.8

    metodos = {item["metodo"] for item in res["traza"] if item["tipo"] == "METODO"}
    esperados_cu01 = {
        "medirNivelLlenadoContenedores()",
        "analizarImagenes()",
        "evaluarPersistencia()",
        "publicarEventoRiesgo()",
        "medirGases()",
        "registrarMedicion()",
        "detectarAumentoProgresivo()",
        "publicarMedicion()",
        "consultarEventos()",
        "calcularRiesgo()",
        "priorizarZonas()",
        "delegarAlerta()",
        "recibirSolicitudAlerta()",
        "emitirAviso()",
        "gestionarConfirmacion()",
        "generarReporteConfirmacion()",
    }
    assert esperados_cu01.issubset(metodos)

    # Verificar persistencia en SQLite
    estado_res = sma.db.get_estado_residuos("zona_3")
    assert estado_res is not None
    assert estado_res["tiempo_sobre_limite"] >= 45
    assert len(sma.db.list_historial_aire("zona_3")) >= 3


def test_cu01_sin_confirmacion_failure_y_duplicada_refuse(tmp_path: Path) -> None:
    db_file = tmp_path / "test_cu01_alt.db"
    sma = SMAMonitoreoBazurto(db_path=str(db_file))

    res_fail = sma.ejecutar_caso_uso_1(zona_id="zona_3", forzar_duplicada=False, comunidad_confirma=False)
    assert res_fail["resultado_acl"] == "FAILURE"
    metodos_fail = {item["metodo"] for item in res_fail["traza"] if item["tipo"] == "METODO"}
    assert "generarReporteSinConfirmacion()" in metodos_fail

    res_refuse = sma.ejecutar_caso_uso_1(zona_id="zona_3", forzar_duplicada=True, comunidad_confirma=True)
    assert res_refuse["resultado_acl"] == "REFUSE"


def test_cu02_auditoria_escalamiento_y_timeout_sensor(tmp_path: Path) -> None:
    db_file = tmp_path / "test_cu02.db"
    sma = SMAMonitoreoBazurto(db_path=str(db_file))

    sma.ejecutar_caso_uso_1(zona_id="zona_3", comunidad_confirma=False)
    res_cu2 = sma.ejecutar_caso_uso_2(
        zona_id="zona_3", simular_sin_confirmacion=True, simular_sensor_caido=True
    )

    assert res_cu2["caso_uso"] == "CU-02"
    assert res_cu2["alerta_confirmada"] is False
    assert res_cu2["sensor_aire_activo"] is False
    assert res_cu2["riesgo_recalculado"] is not None
    assert len(res_cu2["incidencias_creadas"]) == 2

    metodos_cu2 = {item["metodo"] for item in res_cu2["traza"] if item["tipo"] == "METODO"}
    esperados_cu02 = {
        "supervisarAgentes()",
        "verificarAtencionEventos()",
        "registrarIncidencias()",
        "notificarFallos()",
        "solicitarAccionesCorrectivas()",
    }
    assert esperados_cu02.issubset(metodos_cu2)

    performatives = [item["performative"] for item in res_cu2["traza"] if item["tipo"] == "ACL"]
    assert "QUERY-IF" in performatives
    assert "DISCONFIRM" in performatives
    assert "INFORM" in performatives
    assert "REQUEST" in performatives
    assert "AGREE" in performatives


def test_api_endpoints_y_persistencia() -> None:
    client = TestClient(app)
    assert client.get("/health").status_code == 200
    assert client.post("/api/reset").status_code == 200

    resp_cu1 = client.post(
        "/api/caso-uso-1", json={"zona_id": "zona_3", "forzar_duplicada": False, "comunidad_confirma": True}
    )
    assert resp_cu1.status_code == 200
    assert resp_cu1.json()["resultado_acl"] == "INFORM-DONE"

    resp_cu2 = client.post(
        "/api/caso-uso-2",
        json={"zona_id": "zona_3", "simular_sin_confirmacion": True, "simular_sensor_caido": False},
    )
    assert resp_cu2.status_code == 200
    assert resp_cu2.json()["alerta_confirmada"] is False

    estado = client.get("/api/estado").json()
    assert len(estado["mensajes_acl"]) >= 8
    assert len(estado["incidencias"]) >= 1


def test_vision_analyzer_imagenes_reales() -> None:
    ensure_sample_images(STATIC_DIR)
    res_limpio = analizar_imagen_contenedor(preset_name="contenedor_limpio.png", static_dir=STATIC_DIR)
    res_medio = analizar_imagen_contenedor(preset_name="contenedor_medio.png", static_dir=STATIC_DIR)
    res_critico = analizar_imagen_contenedor(preset_name="contenedor_critico.png", static_dir=STATIC_DIR)

    assert res_limpio["nivel_llenado_visual"] < 40.0
    assert res_limpio["desbordamiento"] is False
    assert 45.0 <= res_medio["nivel_llenado_visual"] < 80.0
    assert res_medio["desbordamiento"] is False
    assert res_critico["nivel_llenado_visual"] >= 80.0
    assert res_critico["desbordamiento"] is True
    assert res_critico["bolsas_en_suelo"] >= 2
    assert res_critico["annotated_image_base64"].startswith("data:image/png;base64,")


def test_panel_comunidad_interactivo_confirmar_y_rechazar() -> None:
    client = TestClient(app)
    assert client.post("/api/reset").status_code == 200

    # 1. Analizar escena crítica vía API de visión y sincronizar con zona_5
    vis_resp = client.post(
        "/api/vision/analizar",
        json={"zona_id": "zona_5", "preset_imagen": "contenedor_critico.png", "aplicar_a_entorno": True},
    )
    assert vis_resp.status_code == 200
    assert vis_resp.json()["nivel_llenado_visual"] >= 80.0

    # 2. Ejecutar CU-01 en modo interactivo y confirmar recepción desde Panel de Comunidad
    cu1_ack = client.post(
        "/api/caso-uso-1",
        json={
            "zona_id": "zona_5",
            "preset_imagen": "contenedor_critico.png",
            "esperar_confirmacion_interactiva": True,
        },
    )
    assert cu1_ack.status_code == 200
    data_ack = cu1_ack.json()
    assert data_ack["resultado_acl"] == "PENDIENTE_COMUNIDAD"
    alerta_id_1 = data_ack["alerta_id"]

    resp_confirm = client.post(f"/api/alertas/{alerta_id_1}/responder", json={"confirmar": True})
    assert resp_confirm.status_code == 200
    assert resp_confirm.json()["resultado_acl"] == "INFORM-DONE"
    assert resp_confirm.json()["confirmada_comunidad"] is True

    # 3. Ejecutar CU-01 interactivo y simular falta de respuesta comunitaria -> FAILURE
    cu1_fail = client.post(
        "/api/caso-uso-1",
        json={
            "zona_id": "zona_3",
            "preset_imagen": "contenedor_critico.png",
            "esperar_confirmacion_interactiva": True,
        },
    )
    assert cu1_fail.status_code == 200
    alerta_id_2 = cu1_fail.json()["alerta_id"]

    resp_fail = client.post(f"/api/alertas/{alerta_id_2}/responder", json={"confirmar": False})
    assert resp_fail.status_code == 200
    assert resp_fail.json()["resultado_acl"] == "FAILURE"
    assert resp_fail.json()["confirmada_comunidad"] is False
