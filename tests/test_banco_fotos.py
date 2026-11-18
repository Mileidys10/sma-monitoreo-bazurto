import random
import shutil
from pathlib import Path

from PIL import Image

from app.autonomo import LoopAutonomo
from app.banco_fotos import BancoFotos
from app.eventos import EventBus
from app.main import STATIC_DIR
from app.models_masml import SMAMonitoreoBazurto


def _carpeta_con_muestras(tmp_path: Path) -> Path:
    carpeta = tmp_path / "fotos"
    carpeta.mkdir()
    for nombre in ("contenedor_limpio.png", "contenedor_medio.png", "contenedor_critico.png"):
        shutil.copy(STATIC_DIR / "samples" / nombre, carpeta / nombre)
    return carpeta


def test_carpeta_inexistente_deja_banco_vacio(tmp_path: Path) -> None:
    banco = BancoFotos(tmp_path / "no_existe")
    assert len(banco) == 0 and banco.elegir(50.0) is None


def test_banco_elige_la_foto_mas_parecida_al_nivel(tmp_path: Path) -> None:
    banco = BancoFotos(_carpeta_con_muestras(tmp_path), rng=random.Random(1))
    assert len(banco) == 3
    niveles = {f["nombre"]: f["nivel"] for f in banco.fotos}
    assert niveles["contenedor_limpio.png"] < niveles["contenedor_medio.png"] < niveles["contenedor_critico.png"]
    por_nombre = {f["data_url"]: f["nombre"] for f in banco.fotos}
    assert {por_nombre[banco.elegir(5.0)] for _ in range(20)} <= {"contenedor_limpio.png", "contenedor_medio.png"}
    assert por_nombre[banco.elegir(99.0)] in {"contenedor_critico.png", "contenedor_medio.png"}


def test_archivos_corruptos_o_que_no_son_imagen_se_omiten(tmp_path: Path) -> None:
    carpeta = _carpeta_con_muestras(tmp_path)
    (carpeta / "roto.png").write_bytes(b"no soy una imagen")
    (carpeta / "notas.txt").write_text("ignorar")
    banco = BancoFotos(carpeta)
    assert len(banco) == 3 and "roto.png" in banco.descartadas


def test_foto_sin_contenedor_se_descarta(tmp_path: Path) -> None:
    carpeta = tmp_path / "fotos"
    carpeta.mkdir()
    Image.new("RGB", (300, 300), (240, 200, 180)).save(carpeta / "persona.png")  # sin ningun contenedor
    banco = BancoFotos(carpeta)
    assert len(banco) == 0 and banco.descartadas == ["persona.png"]


def test_la_foto_no_pisa_el_nivel_simulado_en_el_bucle(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SMA_FOTOS_DIR", str(_carpeta_con_muestras(tmp_path)))
    sma = SMAMonitoreoBazurto(db_path=str(tmp_path / "bf.db"))
    bus = EventBus()
    loop = LoopAutonomo(sma, bus, ritmo_s=0, semilla=5)
    loop.entorno.paso_llenado = (0.0, 0.0)
    assert len(loop.banco) == 3 and "banco de fotos locales" in loop.info_sistema["mensaje"]
    antes = sma.db.get_zona("zona_2")["nivel_llenado_contenedores"]
    loop.ejecutar_ronda()  # ronda 1 = zona_2
    assert sma.db.get_zona("zona_2")["nivel_llenado_contenedores"] == antes
    vis = [e.datos for e in bus.recientes() if e.tipo == "vision"][0]
    assert vis["imagen_anotada_url"] and vis["imagen_url"] is None
