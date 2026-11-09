"""Piezas del ejecutable de Windows que se pueden comprobar sin Windows."""
import importlib.util
import socket
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def test_expedientes_van_a_documentos_cuando_esta_congelado(monkeypatch, tmp_path):
    import m6_propuesta.expediente as exp

    monkeypatch.delenv("LICITAPP_EXPEDIENTES", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(exp, "_documentos", lambda: tmp_path / "Documentos")
    assert exp._raiz_expedientes() == tmp_path / "Documentos" / "LicitApp" / "expedientes"
    monkeypatch.setenv("LICITAPP_EXPEDIENTES", str(tmp_path / "otra"))
    assert exp._raiz_expedientes() == tmp_path / "otra"
    monkeypatch.undo()
    assert exp._raiz_expedientes() == RAIZ / "expedientes"  # en desarrollo, junto al proyecto


def test_carpeta_de_datos_se_puede_fijar_por_entorno(monkeypatch, tmp_path):
    from licencias import trial, validador

    monkeypatch.setenv("LICITAPP_DATA_DIR", str(tmp_path))
    assert trial._data_dir() == str(tmp_path)
    assert validador._data_dir() == str(tmp_path)


def _cargar_launcher(monkeypatch, tmp_path):
    monkeypatch.setenv("LICITAPP_SIN_VENTANA", "1")
    monkeypatch.setenv("LICITAPP_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("LICITAPP_PUERTO", raising=False)
    spec = importlib.util.spec_from_file_location("launcher_prueba", RAIZ / "launcher.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_launcher_elige_puerto_libre_en_127_0_0_1(monkeypatch, tmp_path):
    launcher = _cargar_launcher(monkeypatch, tmp_path)
    assert launcher.HOST == "127.0.0.1" and launcher.SIN_VENTANA
    with socket.socket() as ocupado:
        ocupado.bind(("127.0.0.1", 0))
        ocupado.listen(1)
        puerto = ocupado.getsockname()[1]
        elegido = launcher._elegir_puerto(puerto)
        assert elegido != puerto and elegido > 0
        assert launcher._puerto_libre(elegido)
        assert not launcher._puerto_libre(puerto)


def test_spec_no_empaqueta_la_clave_privada_ni_los_generadores_de_licencias():
    spec = (RAIZ / "build" / "secop.spec").read_text(encoding="utf-8")
    assert 'licencias/claves/publica.pem' in spec
    assert '(f"{ROOT}/licencias",' not in spec          # no se copia la carpeta entera
    assert "generar_licencia" not in spec and "admin_licencias" not in spec
    assert not (RAIZ / "licencias" / "claves" / "privada.pem").exists()


def test_script_de_windows_es_ascii_con_crlf():
    datos = (RAIZ / "CONSTRUIR_E_INSTALAR.bat").read_bytes()
    datos.decode("ascii")  # sin tildes: cmd.exe las rompe según la página de códigos
    assert b"\r\n" in datos and b"\n" not in datos.replace(b"\r\n", b"")
