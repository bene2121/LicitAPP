"""Pruebas de seguridad: inyección SoQL/SQL, rutas, archivos, secretos, licencia, bot, red y XSS."""
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import docx
import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import seguridad
from m1_ingestor.campos import (
    soql_like,
    soql_literal,
    soql_numero,
    where_departamentos,
    where_oferta,
    where_procesos_s2,
)
from m1_ingestor.entidades import where_entidad
import importlib
from m7_competencia import historial_ofertas
inv = importlib.import_module("m7_competencia.investigar")  # el paquete reexporta la función con el mismo nombre
from m7_competencia.historial_ofertas import estimar_ofertas
from m7_competencia.investigar import investigar

NOMBRES_RAROS = [
    "CONSORCIO CG&A2M",
    "O'BRIEN",
    "O'BRIEN' OR '1'='1",
    "x'; DROP TABLE procesos_s2; --",
    "100% _real_ \\ \"comillas\"",
    "UNIÓN TEMPORAL Ñandú ''doble''",
    "salto\nde\x00linea",
]


# ═════════════════════════════════════════════════════════════════════════════
# 1. Inyección SoQL
# ═════════════════════════════════════════════════════════════════════════════

def _fuera_de_literales(where: str) -> str:
    """Quita los literales 'texto' de un $where. Falla si algún literal queda abierto."""
    salida, i, n = [], 0, len(where)
    while i < n:
        c = where[i]
        if c != "'":
            salida.append(c)
            i += 1
            continue
        i += 1
        while True:
            assert i < n, f"literal sin cerrar en: {where!r}"
            if where[i] == "'":
                if i + 1 < n and where[i + 1] == "'":  # comilla escapada
                    i += 2
                    continue
                i += 1
                break
            i += 1
        salida.append("S")
    return "".join(salida)


def _registrador(respuestas=None):
    llamadas = []

    def cliente(url, params):
        llamadas.append((url, dict(params)))
        for clave, filas in (respuestas or {}).items():
            if clave in url:
                return filas
        return []

    return cliente, llamadas


def _revisar_wheres(llamadas):
    assert llamadas, "el cliente falso no recibió consultas"
    for _url, params in llamadas:
        fuera = _fuera_de_literales(params["$where"])
        # Fuera de los literales solo puede haber SoQL propio, nunca texto del usuario.
        assert not re.search(r"DROP|1'?='?1|--", fuera, re.I), fuera
        assert "\x00" not in params["$where"] and "\n" not in params["$where"]


def test_soql_literal_escapa_comillas_y_controles():
    assert soql_literal("O'BRIEN") == "O''BRIEN"
    assert soql_literal("a'; DROP--") == "a''; DROP--"
    assert soql_literal("uno\x00dos\nTres") == "unodosTres"
    assert soql_literal("CONSORCIO CG&A2M") == "CONSORCIO CG&A2M"


def test_soql_like_quita_comodines_y_acentos():
    assert soql_like("Ñandú 100%_x") == "NANDU 100 X"
    assert soql_like("O'BRIEN") == "O''BRIEN"
    assert soql_like("CONSORCIO CG&A2M") == "CONSORCIO CG&A2M"
    assert len(soql_like("a" * 5000)) <= 120


@pytest.mark.parametrize("consulta", NOMBRES_RAROS)
def test_investigar_por_nombre_no_rompe_el_literal(consulta):
    cliente, llamadas = _registrador()
    investigar(consulta + "xx", cliente=cliente)
    _revisar_wheres(llamadas)


def test_investigar_por_nit_y_listas_in_con_nombres_raros():
    # Socios/consorcios con comillas y & vuelven de la API y se reutilizan en listas IN.
    respuestas = {
        "ceth-n4bn": [{
            "nombre_grupo": "CONSORCIO O'BRIEN & CIA", "codigo_grupo": "C'1",
            "nit_participante": "900111222", "nombre_participante": "O'BRIEN SAS",
            "participacion": "50", "es_lider_del_grupo": "Verdadero",
        }],
    }
    cliente, llamadas = _registrador(respuestas)
    investigar("900.111.222-3", cliente=cliente)
    _revisar_wheres(llamadas)
    assert any("C''1" in p["$where"] for _u, p in llamadas)


@pytest.mark.parametrize("consulta", NOMBRES_RAROS + ["900111222-3"])
def test_historial_ofertas_no_rompe_el_literal(consulta):
    respuestas = {
        "ceth-n4bn": [{"nombre_grupo": "CONSORCIO O'BRIEN & CIA"}],
        "wi7w-2nvm": [{
            "identificador_de_la_oferta": "1", "id_del_proceso_de_compra": "CO1.X'1",
            "valor_de_la_oferta": "90", "nombre_proveedor": "O'BRIEN",
        }],
    }
    cliente, llamadas = _registrador(respuestas)
    estimar_ofertas([consulta], 100.0, cliente=cliente)
    _revisar_wheres(llamadas)


def test_historial_nit_en_where_va_escapado(monkeypatch):
    # Aunque _variantes_nit solo devuelva dígitos, el where usa soql_literal (defensa en profundidad).
    monkeypatch.setattr(historial_ofertas, "_variantes_nit", lambda t: ["1' OR '1'='1"])
    cliente, llamadas = _registrador()
    estimar_ofertas(["123456789"], 100.0, cliente=cliente)
    _revisar_wheres(llamadas)


def test_where_procesos_no_acepta_texto_en_numeros():
    where = where_procesos_s2("0 OR 1=1", "5; DROP", ["72'; DROP"], "2026-01-01'; --")
    fuera = _fuera_de_literales(where)
    assert "1=1" not in fuera and "DROP" not in fuera
    assert soql_numero("abc", 7) == 7 and soql_numero(float("nan")) == 0.0


def test_where_departamentos_sin_comodines_ni_comillas():
    where = where_departamentos(["%", "_", "ANT'; DROP", "BOGOTA"])
    fuera = _fuera_de_literales(where)
    assert "DROP" not in fuera
    assert "like '%%%'" not in where and "like '%_%'" not in where


def test_where_oferta_y_entidad_escapan():
    assert where_oferta("A'B") == "id_del_proceso_de_compra='A''B'"
    _fuera_de_literales(where_entidad("1' OR '1'='1"))


def test_sqlite_upsert_guarda_texto_hostil_como_dato(tmp_path):
    from m1_ingestor.db_schema import init_db, procesos_s2
    from m1_ingestor.ingestor import _get_engine, _upsert_rows
    from sqlalchemy import select

    ruta = str(tmp_path / "t.db")
    init_db(ruta)
    motor = _get_engine(ruta)
    hostil = "x'); DROP TABLE procesos_s2; --"
    _upsert_rows(motor, procesos_s2, [{"id_del_proceso": "P1", "titulo": hostil, "entidad": hostil}], "id_del_proceso")
    with motor.connect() as con:
        fila = con.execute(select(procesos_s2.c.titulo)).fetchone()
    assert fila[0] == hostil


# ═════════════════════════════════════════════════════════════════════════════
# 2. Rutas y archivos
# ═════════════════════════════════════════════════════════════════════════════

from test_expediente import _formato, expediente  # noqa: E402,F401  (fixture reutilizado)
from m6_propuesta.expediente import (  # noqa: E402
    _seguro, generar_paquete, leer_expediente, reemplazar_en_docx, texto_pdf_seguro, texto_xml_docx,
)


@pytest.mark.parametrize("valor", ["..", "../../etc/passwd", "a/b\\c", "...", "C:\\Windows", "", "  ", "CON"])
def test_seguro_nunca_produce_separadores_ni_puntos_iniciales(valor):
    nombre = _seguro(valor)
    assert "/" not in nombre and "\\" not in nombre and ":" not in nombre
    assert not nombre.startswith(".") and nombre not in {"", ".."}


def test_generar_paquete_con_id_de_ruta_queda_dentro_del_destino(expediente, tmp_path):
    destino = tmp_path / "salida"
    destino.mkdir()
    proceso = {"id": "../../../escape", "referencia": "../../../escape", "entidad": "E", "objeto": "O",
               "presupuesto_oficial": 1_000_000}
    res = generar_paquete(expediente, proceso, {"precio": 900_000}, destino=destino)
    carpeta = Path(res["carpeta"]).resolve()
    assert destino.resolve() in carpeta.parents
    assert not (tmp_path / "escape").exists()


def test_symlinks_del_expediente_no_se_copian(expediente, tmp_path):
    if sys.platform == "win32":
        pytest.skip("symlinks requieren privilegios en Windows")
    secreto = tmp_path / "secreto_ajeno.pdf"
    secreto.write_bytes(b"%PDF-SECRETO-AJENO")
    seccion = Path(expediente["raiz"]) / "6. RUT"
    (seccion / "enlace.pdf").symlink_to(secreto)
    nuevo = leer_expediente(expediente["carpeta"])
    nombres = [a["nombre"] for s in nuevo["secciones"] for a in s["archivos"]]
    assert "enlace.pdf" not in nombres
    res = generar_paquete(nuevo, {"id": "P-2", "entidad": "E", "objeto": "O"}, {"precio": 5_000_000},
                          destino=tmp_path / "out")
    for archivo in Path(res["carpeta"]).rglob("*"):
        if archivo.is_file():
            assert b"SECRETO-AJENO" not in archivo.read_bytes()


def _docx_con_miembro(ruta: Path, nombre: str, datos: bytes):
    _formato(ruta, ["hola"])
    with zipfile.ZipFile(ruta, "a") as z:
        z.writestr(nombre, datos, compress_type=zipfile.ZIP_DEFLATED)


def test_zip_bomb_en_docx_se_rechaza(tmp_path):
    ruta = tmp_path / "bomba.docx"
    _docx_con_miembro(ruta, "word/relleno.bin", b"\0" * (6 * 1024 * 1024))  # compresión >> 200:1
    with pytest.raises(seguridad.ArchivoNoSeguro):
        texto_xml_docx(str(ruta))
    with pytest.raises(seguridad.ArchivoNoSeguro):
        reemplazar_en_docx(ruta, [("hola", "chao")])


def test_zip_slip_en_docx_se_rechaza(tmp_path):
    ruta = tmp_path / "slip.docx"
    _docx_con_miembro(ruta, "../../evil.txt", b"x")
    with pytest.raises(seguridad.ArchivoNoSeguro):
        texto_xml_docx(str(ruta))


def test_docx_y_pdf_enormes_se_rechazan_por_tamano(tmp_path, monkeypatch):
    ruta = tmp_path / "grande.docx"
    _formato(ruta, ["hola"])
    monkeypatch.setattr(seguridad, "MAX_DOCX_BYTES", 100)
    with pytest.raises(seguridad.ArchivoNoSeguro):
        texto_xml_docx(str(ruta))
    pdf = tmp_path / "grande.pdf"
    pdf.write_bytes(b"%PDF-1.4" + b"0" * 5000)
    monkeypatch.setattr("m6_propuesta.expediente.MAX_PDF_BYTES", 100)
    assert texto_pdf_seguro(str(pdf)) == ""


def test_expediente_con_docx_enorme_avisa_y_no_revienta(expediente, monkeypatch):
    monkeypatch.setattr(seguridad, "MAX_DOCX_BYTES", 100)
    nuevo = leer_expediente(expediente["carpeta"])
    assert nuevo["datos"]["omitidos"]
    assert any("No se leyeron" in a for a in nuevo["avisos"])


def test_docx_con_entidad_externa_no_lee_archivos_locales(tmp_path):
    secreto = tmp_path / "secreto.txt"
    secreto.write_text("CONTENIDO-SECRETO-XXE")
    ruta = tmp_path / "xxe.docx"
    _formato(ruta, ["Nombre del proponente: ACME"])
    with zipfile.ZipFile(ruta) as z:
        xml = z.read("word/document.xml").decode()
    xml = xml.replace("<w:document", f'<!DOCTYPE d [<!ENTITY x SYSTEM "file://{secreto}">]><w:document', 1)
    xml = xml.replace("ACME", "ACME &x;", 1)
    nueva = tmp_path / "xxe2.docx"
    with zipfile.ZipFile(ruta) as zin, zipfile.ZipFile(nueva, "w") as zout:
        for it in zin.infolist():
            zout.writestr(it, xml.encode() if it.filename == "word/document.xml" else zin.read(it.filename))
    from m6_propuesta.expediente import _texto_docx
    try:
        parrafos, _t = _texto_docx(str(nueva))
        texto = "\n".join(parrafos)
    except Exception:
        texto = ""
    assert "CONTENIDO-SECRETO-XXE" not in texto
    assert "CONTENIDO-SECRETO-XXE" not in texto_xml_docx(str(nueva))


def test_eml_findeter_no_permite_inyeccion_de_cabeceras(expediente, tmp_path):
    proceso = {"id": "P-9", "entidad": "FINANCIERA DE DESARROLLO TERRITORIAL", "nit_entidad": "800116398",
               "objeto": "O", "presupuesto_oficial": 10_000_000}
    res = generar_paquete(expediente, proceso, {"precio": 9_000_000},
                          consorcio={"nombre": "ACME\r\nBcc: victima@x.com"}, destino=tmp_path / "o")
    eml = next(Path(res["carpeta"]).glob("*.eml")).read_text(encoding="utf-8")
    cabecera = eml.split("\n\n", 1)[0]
    assert "Bcc:" not in cabecera.replace("Subject: Oferta proceso", "").split("\n")[2:] .__str__()
    assert not any(l.startswith("Bcc:") for l in cabecera.splitlines())


def test_helpers_de_nombre_y_ruta():
    assert seguridad.nombre_archivo_seguro("../../x/y") == "x_y"
    assert seguridad.nombre_archivo_seguro("") == "archivo"
    assert seguridad.ruta_dentro_de("/a/b", "/a/b/c") is True
    assert seguridad.ruta_dentro_de("/a/b", "/a/b/../c") is False
    assert seguridad.sin_control("a\r\nb\x00c") == "a b c"


# ═════════════════════════════════════════════════════════════════════════════
# 4. Secretos
# ═════════════════════════════════════════════════════════════════════════════

def _archivos_versionados():
    try:
        out = subprocess.run(["git", "ls-files"], cwd=RAIZ, capture_output=True, text=True, check=True).stdout
    except Exception:
        pytest.skip("sin git")
    return [RAIZ / f for f in out.splitlines() if (RAIZ / f).is_file()]


def test_arbol_versionado_sin_claves_ni_credenciales():
    for archivo in _archivos_versionados():
        if archivo.name == "test_seguridad.py":
            continue  # contiene los patrones buscados
        assert archivo.name != "privada.pem" and archivo.suffix not in {".lic", ".key", ".pfx", ".p12"}
        assert "settings.local.json" not in archivo.name
        if archivo.suffix in {".py", ".md", ".txt", ".bat", ".example", ".toml", ".sh", ".service", ".spec", ".pem"}:
            texto = archivo.read_text(encoding="utf-8", errors="ignore")
            assert "PRIVATE KEY-----" not in texto, archivo
            assert not re.search(r"(?i)(api[_-]?key|secret|token)\s*=\s*['\"][A-Za-z0-9]{20,}['\"]", texto), archivo


def test_gitignore_cubre_secretos_y_datos():
    ignorado = (RAIZ / ".gitignore").read_text(encoding="utf-8")
    for patron in ("licencias/claves/privada.pem", ".env", "data/", "*.lic", "expedientes/*/*",
                   ".claude/settings.local.json", "*.key"):
        assert patron in ignorado, patron


def test_env_example_no_pide_contrasena_secop():
    texto = (RAIZ / ".env.example").read_text(encoding="utf-8")
    assert "SECOP2_CONTRASENA" not in texto


def test_perfil_no_guarda_contrasena_smtp_en_el_json(tmp_path, monkeypatch):
    # Sin cifrado disponible (Linux) la clave NO se escribe en ningún archivo.
    monkeypatch.setattr(seguridad, "_dpapi", lambda datos, proteger: None)
    perfil_p, sec_p = tmp_path / "perfil.json", tmp_path / ".smtp_secret"
    ok = seguridad.guardar_perfil_json(perfil_p, sec_p, {"empresa": "ACME", "smtp_user": "a@b.co", "smtp_pass": "CLAVE-SECRETA-123"})
    assert ok is False
    for archivo in tmp_path.iterdir():
        assert b"CLAVE-SECRETA-123" not in archivo.read_bytes()
    assert json.loads(perfil_p.read_text())["empresa"] == "ACME"


def test_perfil_con_cifrado_guarda_la_clave_cifrada_y_la_recupera(tmp_path, monkeypatch):
    def falso(datos, proteger):  # cifrado de juguete: invertir bytes
        return datos[::-1]
    monkeypatch.setattr(seguridad, "_dpapi", falso)
    perfil_p, sec_p = tmp_path / "perfil.json", tmp_path / ".smtp_secret"
    assert seguridad.guardar_perfil_json(perfil_p, sec_p, {"smtp_pass": "CLAVE-SECRETA-123"}) is True
    assert "CLAVE-SECRETA-123" not in perfil_p.read_text() + sec_p.read_text()
    assert seguridad.cargar_perfil_json(perfil_p, sec_p)["smtp_pass"] == "CLAVE-SECRETA-123"


def test_perfil_viejo_con_clave_en_claro_se_migra(tmp_path, monkeypatch):
    monkeypatch.setattr(seguridad, "_dpapi", lambda datos, proteger: datos[::-1])
    perfil_p, sec_p = tmp_path / "perfil.json", tmp_path / ".smtp_secret"
    perfil_p.write_text(json.dumps({"empresa": "X", "smtp_pass": "VIEJA-CLAVE-EN-CLARO"}))
    cargado = seguridad.cargar_perfil_json(perfil_p, sec_p)
    assert cargado["smtp_pass"] == "VIEJA-CLAVE-EN-CLARO"
    assert "VIEJA-CLAVE-EN-CLARO" not in perfil_p.read_text()


def test_build_no_empaqueta_claves_privadas():
    codigo = [l for l in (RAIZ / "build" / "secop.spec").read_text(encoding="utf-8").splitlines()
              if not l.strip().startswith("#")]
    texto = "\n".join(codigo)
    assert not re.search(r'\(f"\{ROOT\}/licencias",\s*"licencias"\)', texto), "copia la carpeta licencias completa"
    assert "privada" not in texto and ".lic" not in texto and "admin_licencias" not in texto


# ═════════════════════════════════════════════════════════════════════════════
# 5. Licencia y trial
# ═════════════════════════════════════════════════════════════════════════════

from licencias import trial, validador  # noqa: E402
from licencias.validador import LicenciaInvalida  # noqa: E402


def _par_claves():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    privada = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = privada.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    return privada, pem


def _firmar(privada, payload: dict) -> str:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    firma = privada.sign(json.dumps(payload, sort_keys=True).encode(), padding.PKCS1v15(), hashes.SHA256())
    return json.dumps({"payload": payload, "firma": firma.hex()})


def _payload(dias=30):
    return {"license_id": "L-1", "nit": "900", "nombre": "ACME", "plan": "pro",
            "fecha_vencimiento": (datetime.now() + timedelta(days=dias)).strftime("%Y-%m-%d")}


def test_clave_publica_embebida_coincide_con_el_archivo():
    assert validador._PUBLICA_PEM.strip() == Path(validador._PUBLICA_PATH).read_bytes().strip()


def test_licencia_firmada_valida_y_manipulada_se_rechaza(tmp_path, monkeypatch):
    privada, pem = _par_claves()
    monkeypatch.setattr(validador, "_PUBLICA_PEM", pem)
    lic = tmp_path / "mi.lic"
    lic.write_text(_firmar(privada, _payload()))
    assert validador.validar_licencia(str(lic))["nombre"] == "ACME"

    datos = json.loads(lic.read_text())
    # 1. cambiar la fecha de vencimiento
    alterada = json.loads(json.dumps(datos))
    alterada["payload"]["fecha_vencimiento"] = "2099-12-31"
    lic.write_text(json.dumps(alterada))
    with pytest.raises(LicenciaInvalida):
        validador.validar_licencia(str(lic))
    # 2. cambiar el plan
    alterada = json.loads(json.dumps(datos))
    alterada["payload"]["plan"] = "empresarial"
    lic.write_text(json.dumps(alterada))
    with pytest.raises(LicenciaInvalida):
        validador.validar_licencia(str(lic))
    # 3. firma corrompida / vacía / basura
    for firma in (datos["firma"][:-4] + "0000", "", "zz"):
        lic.write_text(json.dumps({"payload": datos["payload"], "firma": firma}))
        with pytest.raises(LicenciaInvalida):
            validador.validar_licencia(str(lic))
    lic.write_text("no es json")
    with pytest.raises(LicenciaInvalida):
        validador.validar_licencia(str(lic))


def test_licencia_vencida_o_incompleta_se_rechaza(tmp_path, monkeypatch):
    privada, pem = _par_claves()
    monkeypatch.setattr(validador, "_PUBLICA_PEM", pem)
    lic = tmp_path / "mi.lic"
    lic.write_text(_firmar(privada, _payload(dias=-1)))
    with pytest.raises(LicenciaInvalida):
        validador.validar_licencia(str(lic))
    incompleto = _payload()
    del incompleto["plan"]
    lic.write_text(_firmar(privada, incompleto))
    with pytest.raises(LicenciaInvalida):
        validador.validar_licencia(str(lic))
    malo = _payload()
    malo["fecha_vencimiento"] = "mañana"
    lic.write_text(_firmar(privada, malo))
    with pytest.raises(LicenciaInvalida):
        validador.validar_licencia(str(lic))


def test_reemplazar_publica_pem_no_permite_firmar_licencias_propias(tmp_path, monkeypatch):
    atacante, pem_atacante = _par_claves()
    falso_pem = tmp_path / "publica.pem"
    falso_pem.write_bytes(pem_atacante)
    monkeypatch.setattr(validador, "_PUBLICA_PATH", str(falso_pem))  # el atacante reemplaza el archivo
    lic = tmp_path / "mi.lic"
    lic.write_text(_firmar(atacante, _payload(dias=3650)))
    with pytest.raises(LicenciaInvalida):
        validador.validar_licencia(str(lic))


def test_cache_con_fecha_futura_no_evita_la_consulta_al_servidor(tmp_path, monkeypatch):
    privada, pem = _par_claves()
    monkeypatch.setattr(validador, "_PUBLICA_PEM", pem)
    monkeypatch.setattr(validador, "SERVIDOR_URL", "https://licencias.example/api/validar")
    monkeypatch.setattr(validador, "CACHE_PATH", str(tmp_path / ".lic_cache"))
    lic = tmp_path / "mi.lic"
    lic.write_text(_firmar(privada, _payload()))
    futuro = (datetime.now() + timedelta(days=3650)).isoformat()
    (tmp_path / ".lic_cache").write_text(json.dumps({"ultimo_check": futuro, "activo": True}))
    llamadas = []
    monkeypatch.setattr(validador, "_verificar_con_servidor",
                        lambda i, n: llamadas.append(1) or {"activo": False})
    with pytest.raises(LicenciaInvalida):
        validador.validar_licencia(str(lic))
    assert llamadas, "la caché manipulada evitó la revocación"


def test_servidor_de_licencias_exige_https_y_respuesta_valida(monkeypatch):
    monkeypatch.setattr(validador, "SERVIDOR_URL", "http://evil.example/api/validar")
    with pytest.raises(ValueError):
        validador._verificar_con_servidor("L", "N")


def test_cache_corrupta_no_rompe(tmp_path, monkeypatch):
    monkeypatch.setattr(validador, "CACHE_PATH", str(tmp_path / ".c"))
    (tmp_path / ".c").write_text("[1,2,3]")
    assert validador._leer_cache() == {}


# ── Trial ────────────────────────────────────────────────────────────────────

@pytest.fixture
def ruta_trial(tmp_path, monkeypatch):
    ruta = tmp_path / "data" / ".trial"
    monkeypatch.setattr(trial, "TRIAL_PATH", str(ruta))
    return ruta


def _trial_legado(ruta: Path, hace_dias: int, mid=None):
    """Archivo de trial EXACTAMENTE como lo escribía la versión anterior."""
    mid = mid or trial._machine_id()
    inicio = (datetime.now() - timedelta(days=hace_dias)).strftime("%Y-%m-%d")
    h = hashlib.sha256(f"{inicio}-{mid}-secop-trial".encode()).hexdigest()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps({"inicio": inicio, "machine": mid, "hash": h}))


def test_trial_legado_sigue_valido(ruta_trial):
    _trial_legado(ruta_trial, 3)
    assert trial.activar_o_verificar_trial()["dias_restantes"] == 4
    assert trial.activar_o_verificar_trial()["dias_restantes"] == 4  # y tras reiniciar


def test_trial_corrupto_no_reinicia_el_periodo(ruta_trial):
    _trial_legado(ruta_trial, 6)
    for basura in ("", "{", "[]", '{"inicio": 1}', '{"inicio": "2026-01-01", "hash": "x"}'):
        ruta_trial.write_text(basura)
        # Hay copia redundante íntegra: se restaura el MISMO inicio, no se reinicia.
        # (La copia se crea la primera vez que corre una versión nueva.)
    ruta_trial.unlink()
    ruta_trial.parent.joinpath(".lic_t").unlink(missing_ok=True)
    _trial_legado(ruta_trial, 6)
    trial.activar_o_verificar_trial()  # crea las copias
    ruta_trial.write_text("{")
    assert trial.activar_o_verificar_trial()["dias_restantes"] == 1


def test_trial_corrupto_sin_copias_bloquea(ruta_trial):
    ruta_trial.parent.mkdir(parents=True)
    ruta_trial.write_text("{")
    with pytest.raises(LicenciaInvalida):
        trial.activar_o_verificar_trial()
    assert ruta_trial.read_text() == "{"  # y no se sobrescribió con un trial nuevo


def test_borrar_el_trial_no_lo_reinicia(ruta_trial):
    _trial_legado(ruta_trial, 5)
    assert trial.activar_o_verificar_trial()["dias_restantes"] == 2
    ruta_trial.unlink()
    assert trial.activar_o_verificar_trial()["dias_restantes"] == 2
    assert ruta_trial.exists()


def test_trial_vencido_sigue_vencido_aunque_borren_el_archivo(ruta_trial):
    _trial_legado(ruta_trial, 20)
    with pytest.raises(LicenciaInvalida):
        trial.activar_o_verificar_trial()
    ruta_trial.unlink(missing_ok=True)
    with pytest.raises(LicenciaInvalida):
        trial.activar_o_verificar_trial()


def test_trial_con_hash_alterado_o_fecha_editada_bloquea(ruta_trial):
    _trial_legado(ruta_trial, 6)
    datos = json.loads(ruta_trial.read_text())
    datos["inicio"] = datetime.now().strftime("%Y-%m-%d")  # intenta "rejuvenecer" el trial
    ruta_trial.write_text(json.dumps(datos))
    with pytest.raises(LicenciaInvalida):
        trial.activar_o_verificar_trial()


def test_trial_con_inicio_futuro_o_reloj_atrasado_bloquea(ruta_trial):
    mid = trial._machine_id()
    futuro = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    ruta_trial.parent.mkdir(parents=True)
    ruta_trial.write_text(json.dumps({"inicio": futuro, "machine": mid, "hash": trial._hash_inicio(futuro, mid)}))
    with pytest.raises(LicenciaInvalida):
        trial.activar_o_verificar_trial()
    # reloj atrasado: el último uso quedó registrado en el futuro
    ruta_trial.unlink()
    trial._marcas and [Path(m).unlink(missing_ok=True) for m in trial._marcas()]
    hoy = datetime.now().strftime("%Y-%m-%d")
    ultimo = (datetime.now() + timedelta(days=10)).strftime("%Y-%m-%d")
    trial._escribir(str(ruta_trial), hoy, ultimo, mid)
    with pytest.raises(LicenciaInvalida):
        trial.activar_o_verificar_trial()


def test_trial_nuevo_dura_7_dias_y_sobrevive_a_reinicios(ruta_trial):
    assert trial.activar_o_verificar_trial()["dias_restantes"] == 7
    assert trial.activar_o_verificar_trial()["dias_restantes"] == 7


# ── Puerta de licencia en la app ─────────────────────────────────────────────

def _app(timeout=120):
    from streamlit.testing.v1 import AppTest
    return AppTest.from_file(str(RAIZ / "m5_dashboard" / "app.py"), default_timeout=timeout)


def test_app_se_detiene_con_trial_vencido_aunque_se_edite_session_state(ruta_trial, monkeypatch, tmp_path):
    monkeypatch.setattr(validador, "LICENCIA_PATH", str(tmp_path / "no_existe.lic"))
    _trial_legado(ruta_trial, 30)
    at = _app()
    at.session_state["perfil"] = {"empresa": "X"}
    at.session_state["licencia_ok"] = True
    at.session_state["_LICENCIA_INFO"] = {"dias_restantes": 999, "plan": "empresarial"}
    at.run()
    assert not at.exception
    assert any("Acceso bloqueado" in e.value for e in at.error)
    assert len(at.tabs) == 0


def test_app_se_detiene_con_licencia_manipulada(tmp_path, monkeypatch):
    privada, pem = _par_claves()
    monkeypatch.setattr(validador, "_PUBLICA_PEM", pem)
    lic = tmp_path / "mi.lic"
    datos = json.loads(_firmar(privada, _payload()))
    datos["payload"]["fecha_vencimiento"] = "2099-01-01"
    lic.write_text(json.dumps(datos))
    monkeypatch.setattr(validador, "LICENCIA_PATH", str(lic))
    at = _app()
    at.run()
    assert any("Acceso bloqueado" in e.value for e in at.error)
    assert len(at.tabs) == 0


# ═════════════════════════════════════════════════════════════════════════════
# 6. Credenciales del bot
# ═════════════════════════════════════════════════════════════════════════════

from m4_bot import secop_bot  # noqa: E402
from m4_bot.secop_bot import SecopBot, SecopBotError  # noqa: E402

USUARIO, CLAVE = "usuario-secreto@empresa.co", "Cl4v3-Sup3r-S3cret4!"


class PaginaFalsa:
    """Registra en orden lo que haría Playwright, sin abrir ningún navegador."""

    def __init__(self):
        self.eventos = []
        self.url = "https://community.secop.gov.co/x"

    def goto(self, url, **kw):
        self.eventos.append(("goto", url))

    def wait_for_selector(self, sel, **kw):
        self.eventos.append(("espera", sel))

    def fill(self, sel, valor):
        self.eventos.append(("fill", sel, valor))

    def click(self, sel, **kw):
        self.eventos.append(("click", sel))

    def wait_for_load_state(self, *a, **kw):
        pass

    def screenshot(self, path=None, **kw):
        self.eventos.append(("captura", os.path.basename(path)))

    def inner_text(self, sel):
        return "texto"

    def pdf(self, path=None, **kw):
        pass


@pytest.fixture
def bot(tmp_path):
    b = SecopBot(USUARIO, CLAVE, modo="dry_run", carpeta_capturas=str(tmp_path / "cap"))
    b._page = PaginaFalsa()
    return b


def test_bot_modo_desconocido_no_cae_en_envio_real(tmp_path):
    for modo in ("dryrun", "DRY_RUN", "Real", "produccion", "x"):
        with pytest.raises(ValueError):
            SecopBot(USUARIO, CLAVE, modo=modo, carpeta_capturas=str(tmp_path))
    assert SecopBot(USUARIO, CLAVE, modo="real", carpeta_capturas=str(tmp_path)).modo == "real"


def test_bot_login_no_captura_pantalla_con_credenciales_ni_las_loguea(bot):
    assert bot.login() is True
    eventos = bot._page.eventos
    i_clave = next(i for i, e in enumerate(eventos) if e[0] == "fill" and e[2] == CLAVE)
    i_click = next(i for i, e in enumerate(eventos) if e[0] == "click")
    assert not [e for e in eventos[i_clave:i_click] if e[0] == "captura"], "captura con credenciales escritas"
    assert all("credencial" not in e[1].lower() for e in eventos if e[0] == "captura")
    texto_log = "\n".join(bot._log)
    assert CLAVE not in texto_log and USUARIO not in texto_log


def test_bot_redacta_credenciales_en_errores_y_log_en_disco(tmp_path):
    class Roto(SecopBot):
        def _iniciar_browser(self):
            raise RuntimeError(f"fallo con {CLAVE} y {USUARIO}")

    b = Roto(USUARIO, CLAVE, modo="dry_run", carpeta_capturas=str(tmp_path / "cap"))
    r = b.presentar_oferta("CO1.BDOS.1", 1_000_000)
    assert r["exito"] is False
    volcado = json.dumps(r)
    assert CLAVE not in volcado and USUARIO not in volcado
    for archivo in (tmp_path / "cap").rglob("*"):
        if archivo.is_file():
            contenido = archivo.read_bytes()
            assert CLAVE.encode() not in contenido and USUARIO.encode() not in contenido


def test_bot_registrar_redacta_cualquier_mensaje(bot):
    bot._registrar(f"clave={CLAVE} usuario={USUARIO}")
    assert CLAVE not in bot._log[-1] and USUARIO not in bot._log[-1]


@pytest.mark.parametrize("malo", ["", "CO1&Page=x", "../../admin", "a b", "x#y", "x?y=1", "a" * 200, "x\ny"])
def test_bot_id_proceso_invalido_se_rechaza(bot, malo):
    with pytest.raises(SecopBotError):
        bot.navegar_proceso(malo)
    assert not [e for e in bot._page.eventos if e[0] == "goto"]


def test_bot_id_proceso_valido_navega_a_la_url_esperada(bot, monkeypatch):
    monkeypatch.setattr(secop_bot.time, "sleep", lambda s: None)
    bot.navegar_proceso("CO1.BDOS.1234567")
    url = next(e[1] for e in bot._page.eventos if e[0] == "goto")
    assert url.endswith("contractNoticeId=CO1.BDOS.1234567")


def test_bot_solo_sube_documentos_normales(bot, tmp_path):
    ok = tmp_path / "rut.pdf"
    ok.write_bytes(b"%PDF")
    assert bot._documento_permitido(str(ok))
    for malo in (".env", "clave.py", "x.exe", "datos.db", "llave.pem"):
        p = tmp_path / malo
        p.write_text("x")
        assert not bot._documento_permitido(str(p))
    assert not bot._documento_permitido(str(tmp_path))  # una carpeta


def test_bot_cli_no_recibe_la_contrasena_por_argumento():
    fuente = (RAIZ / "m4_bot" / "secop_bot.py").read_text(encoding="utf-8")
    assert '"--contrasena"' not in fuente and "getpass" in fuente


# ═════════════════════════════════════════════════════════════════════════════
# 7. Red
# ═════════════════════════════════════════════════════════════════════════════

def test_cliente_publico_no_acepta_http_ni_otros_esquemas(monkeypatch):
    import urllib.request

    def prohibido(*a, **kw):
        raise AssertionError("no debía abrir la URL")
    monkeypatch.setattr(urllib.request, "urlopen", prohibido)
    for url in ("http://www.datos.gov.co/x.json", "file:///etc/passwd", "ftp://x/y"):
        assert inv._cliente_publico(url, {}) == []


def test_cliente_publico_limita_el_tamano(monkeypatch):
    import urllib.request

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(seguridad, "MAX_RESPUESTA_BYTES", 50)
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout: Resp(b"[" + b"1," * 100 + b"1]"))
    assert inv._cliente_publico("https://www.datos.gov.co/resource/x.json", {}) == []


def test_leer_limitado_y_exigir_https():
    assert seguridad.leer_limitado(io.BytesIO(b"abc"), 3) == b"abc"
    with pytest.raises(ValueError):
        seguridad.leer_limitado(io.BytesIO(b"abcd"), 3)
    assert seguridad.exigir_https("https://a.co/x")
    assert seguridad.exigir_https("http://localhost:8000/x")
    for malo in ("http://a.co", "ftp://a.co", "file:///x", "//a.co", ""):
        with pytest.raises(ValueError):
            seguridad.exigir_https(malo)
    with pytest.raises(ValueError):
        seguridad.exigir_https("http://localhost/x", permitir_local=False)


def test_secop_client_rechaza_respuestas_enormes_o_no_lista(monkeypatch):
    from m1_ingestor import secop_client
    cliente = secop_client.SecopClient()
    monkeypatch.setattr(secop_client.time, "sleep", lambda s: None)

    class Resp:
        def __init__(self, trozos):
            self.trozos = trozos

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size=0):
            return iter(self.trozos)

    visto = {}

    def get(url, **kw):
        visto.update(kw)
        return Resp(visto["trozos"])
    monkeypatch.setattr(cliente.session, "get", get)
    monkeypatch.setattr(secop_client, "MAX_RESPUESTA_BYTES", 100)
    visto["trozos"] = [b"[" + b"1," * 200 + b"1]"]
    with pytest.raises(secop_client.SecopRequestError):
        cliente._get_page("https://www.datos.gov.co/x.json", {}, 0, 10)
    visto["trozos"] = [b'{"error": true}']
    with pytest.raises(secop_client.SecopRequestError):
        cliente._get_page("https://www.datos.gov.co/x.json", {}, 0, 10)
    visto["trozos"] = [b'[{"a": 1}]']
    assert cliente._get_page("https://www.datos.gov.co/x.json", {}, 0, 10) == [{"a": 1}]
    assert visto["timeout"][1] <= 30 and visto["allow_redirects"] is False
    assert "verify" not in visto  # verificación de certificado por defecto


def test_ningun_modulo_desactiva_la_verificacion_tls_ni_usa_peligros():
    patrones = [r"verify\s*=\s*False", r"\beval\(", r"\bexec\(", r"pickle\.loads?", r"yaml\.load\(",
                r"shell\s*=\s*True", r"os\.system\(", r"_create_unverified_context", r"CERT_NONE"]
    for archivo in _archivos_versionados():
        if archivo.suffix != ".py" or "tests" in archivo.parts or archivo.name == "test_seguridad.py":
            continue
        texto = archivo.read_text(encoding="utf-8", errors="ignore")
        for p in patrones:
            assert not re.search(p, texto), f"{archivo.relative_to(RAIZ)}: {p}"


def test_api_client_exige_https_y_no_permite_rutas_inyectadas(monkeypatch):
    import api_client
    llamadas = []

    class Resp:
        def __init__(self, url):
            llamadas.append(url)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def raise_for_status(self):
            pass

        def iter_bytes(self):
            return iter([b'{"ok": true}'])

    monkeypatch.setattr(api_client.httpx, "stream", lambda m, url, **kw: Resp(url))
    monkeypatch.setattr(api_client, "API_BASE", "http://evil.example")
    assert "error" in api_client.get_detalle_proceso("X")
    assert not llamadas
    monkeypatch.setattr(api_client, "API_BASE", "https://api.example.com")
    api_client.get_detalle_proceso("../../admin?x=1#y")
    url = llamadas[-1]
    assert url.startswith("https://api.example.com/v1/procesos/")
    resto = url[len("https://api.example.com/v1/procesos/"):]
    assert "/" not in resto and "?" not in resto and "#" not in resto


def test_correo_alertas_escapa_html_remoto_y_verifica_certificado(monkeypatch):
    import ssl
    from m4_bot import scheduler
    capturado = {}

    class SMTPFalso:
        def __init__(self, host, port, timeout=None):
            capturado["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def ehlo(self):
            pass

        def starttls(self, context=None):
            capturado["ctx"] = context

        def login(self, u, p):
            pass

        def sendmail(self, de, para, msg):
            capturado["msg"] = msg

    monkeypatch.setattr(scheduler.smtplib, "SMTP", SMTPFalso)
    proc = [{"objeto": "<script>alert(1)</script>", "entidad": "<img src=x onerror=alert(2)>", "score": 90,
             "presupuesto_oficial": 1, "fecha_cierre": "<b>x</b>", "dias_al_cierre": "<i>"}]
    cfg = {"smtp_user": "a@b.co", "smtp_pass": "p", "destinatario": "c@d.co"}
    assert scheduler.enviar_email_alerta(proc, cfg) is True
    assert capturado["ctx"].verify_mode == ssl.CERT_REQUIRED and capturado["ctx"].check_hostname
    import email
    cuerpo = email.message_from_string(capturado["msg"]).get_payload(0).get_payload(decode=True).decode()
    assert "<script>" not in cuerpo and "<img" not in cuerpo and "&lt;script&gt;" in cuerpo
    # destinatario con inyección de cabeceras: no se envía
    assert scheduler.enviar_email_alerta(proc, dict(cfg, destinatario="c@d.co\nBcc: x@y.co")) is False


# ═════════════════════════════════════════════════════════════════════════════
# 8. Streamlit: XSS y exposición
# ═════════════════════════════════════════════════════════════════════════════

def test_esc_html_y_esc_md():
    assert seguridad.esc_html("<script>alert('x')</script>&") == "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;&amp;"
    assert seguridad.esc_html(None) == ""
    md = seguridad.esc_md("![t](http://evil/x.png) [a](javascript:alert(1)) <b>")
    assert "![" not in md.replace("\\![", "") and "<b>" not in md


def test_explorador_escapa_los_datos_remotos(ruta_trial, monkeypatch):
    """Un proceso con HTML en entidad/objeto/modalidad no debe llegar sin escapar a unsafe_allow_html."""
    import api_client
    xss = "<img src=x onerror=alert(1)><script>alert(2)</script>"
    cierre = (datetime.now() + timedelta(days=10)).isoformat()
    proceso = {"id": "CO1.X.1", "entidad": xss, "objeto": xss, "titulo": xss, "modalidad": xss,
               "estado": "Presentación de oferta", "presupuesto_oficial": 100_000_000, "score": 90,
               "fecha_cierre": cierre, "dias_al_cierre": 10, "departamento": "ANTIOQUIA", "unspsc": "72101500"}
    monkeypatch.setattr(api_client, "get_procesos", lambda **kw: {"items": [dict(proceso)], "total": 1})
    # El Explorador consulta SECOP II en vivo: se le da la misma fila hostil en formato SECOP.
    import importlib
    inv = importlib.import_module("m7_competencia.investigar")
    fila = {"id_del_portafolio": "CO1.X.1", "id_del_proceso": "CO1.X.1", "entidad": xss,
            "nombre_del_procedimiento": xss, "modalidad_de_contratacion": xss, "fase": "Presentación de oferta",
            "precio_base": "100000000", "fecha_de_recepcion_de": cierre[:10] + "T00:00:00.000",
            "departamento_entidad": "ANTIOQUIA", "codigo_principal_de_categoria": "V1.72101500"}
    monkeypatch.setattr(inv, "_cliente_publico", lambda url, params: [dict(fila)] if "p6dx" in url else [])
    import streamlit as st
    st.cache_data.clear()
    monkeypatch.setattr(validador, "LICENCIA_PATH", str(ruta_trial.parent / "no.lic"))
    at = _app()
    at.run()
    assert not at.exception
    html = "\n".join(m.value for m in at.markdown)
    assert "&lt;img" in html, "el proceso no se renderizó: la prueba no ejercita el caso"
    assert "<img src=x" not in html and "<script>alert" not in html


def test_entradas_de_arranque_solo_localhost_y_xsrf():
    run = (RAIZ / "m5_dashboard" / "run.py").read_text(encoding="utf-8")
    launcher = (RAIZ / "launcher.py").read_text(encoding="utf-8")
    bat = (RAIZ / "INICIAR.bat").read_text(encoding="utf-8")
    toml = (RAIZ / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    for texto in (run, launcher, bat):
        assert "127.0.0.1" in texto
        assert "enableXsrfProtection" in texto and "false" not in texto.split("enableXsrfProtection")[1][:30].lower()
        assert "gatherUsageStats" in texto
        assert "0.0.0.0" not in texto
    assert 'address = "127.0.0.1"' in toml and "enableXsrfProtection = true" in toml
    assert "gatherUsageStats = false" in toml
    assert "enableCORS\", \"false" not in launcher


# ═════════════════════════════════════════════════════════════════════════════
# 9. Servidores
# ═════════════════════════════════════════════════════════════════════════════

def test_servidor_licencias_admin_con_cabecera_y_limite(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    import importlib
    import sqlite3
    from fastapi.testclient import TestClient

    clave = "k" * 32
    db = tmp_path / "c.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE clientes (license_id TEXT, nit TEXT, nombre TEXT, plan TEXT, "
                "fecha_vencimiento TEXT, activo INTEGER, email TEXT, fecha_creacion TEXT)")
    con.execute("INSERT INTO clientes VALUES ('L1','900','ACME','pro','2099-01-01',1,'a@b.co','2026-01-01')")
    con.commit()
    con.close()
    monkeypatch.setenv("ADMIN_API_KEY", clave)
    monkeypatch.setenv("SECOP_ADMIN_DB", str(db))
    import licencias.servidor.main as srv
    srv = importlib.reload(srv)
    c = TestClient(srv.app)
    assert c.get("/api/admin/clientes").status_code == 403
    assert c.get("/api/admin/clientes", headers={"X-Admin-Key": "otra"}).status_code == 403
    assert c.get("/api/admin/clientes", headers={"X-Admin-Key": clave}).status_code == 200
    # inyección SQL en el NIT: se trata como dato
    r = c.get("/api/admin/cancelar", params={"nit": "900' OR '1'='1"}, headers={"X-Admin-Key": clave})
    assert r.json()["cancelados"] == 0
    r = c.get("/api/validar", params={"license_id": "L1' OR '1'='1", "nit": "900"})
    assert r.json()["activo"] is False
    r = c.get("/api/validar", params={"license_id": "L1", "nit": "900"})
    assert r.json()["activo"] is True
    # fuerza bruta de la clave admin: tras 5 fallos, 429
    srv._LIM_ADMIN_FALLOS._hits.clear()
    codigos = [c.get("/api/admin/clientes", headers={"X-Admin-Key": f"mala{i}"}).status_code for i in range(8)]
    assert codigos[:5] == [403] * 5 and 429 in codigos[5:]
    # límite de consultas de validación
    srv._LIM_VALIDAR._hits.clear()
    codigos = [c.get("/api/validar", params={"license_id": "L1", "nit": "900"}).status_code for _ in range(70)]
    assert 429 in codigos


def test_servidor_licencias_rechaza_clave_admin_debil(monkeypatch):
    pytest.importorskip("fastapi")
    import importlib
    monkeypatch.setenv("ADMIN_API_KEY", "corta")
    import licencias.servidor.main as srv
    with pytest.raises(RuntimeError):
        importlib.reload(srv)
    monkeypatch.setenv("ADMIN_API_KEY", "x" * 32)
    importlib.reload(srv)


def test_servidor_central_like_escape_y_limitador():
    from servidor_central.seguridad import Limitador, like_escape
    assert like_escape("50%_\\") == "50\\%\\_\\\\"
    lim = Limitador(2, 60)
    assert lim.permitir("a") and lim.permitir("a") and not lim.permitir("a") and lim.permitir("b")


def test_servidor_central_rechaza_licencia_falsa_y_limita_intentos(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    import sqlite3
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'central.db'}")
    db = tmp_path / "c.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE clientes (license_id TEXT, activo INTEGER, fecha_vencimiento TEXT)")
    con.execute("INSERT INTO clientes VALUES ('BUENA',1,'2099-01-01'), ('VIEJA',1,'2000-01-01'), ('OFF',0,'2099-01-01')")
    con.commit()
    con.close()
    monkeypatch.setenv("SECOP_ADMIN_DB", str(db))
    for m in [m for m in sys.modules if m.startswith("servidor_central")]:
        del sys.modules[m]
    from fastapi.testclient import TestClient
    from sqlalchemy import JSON
    import sqlalchemy.dialects.postgresql as pg
    pg.JSONB = JSON
    import servidor_central.main as central
    if not central._DB_AVAILABLE:
        pytest.skip("la API central no pudo inicializar su base en este entorno")
    c = TestClient(central.app)
    try:
        assert c.get("/v1/procesos/").status_code == 401
        assert c.get("/v1/procesos/", headers={"X-License-Key": "BUENA' OR '1'='1"}).status_code == 403
        assert c.get("/v1/procesos/", headers={"X-License-Key": "VIEJA"}).status_code == 403
        assert c.get("/v1/procesos/", headers={"X-License-Key": "OFF"}).status_code == 403
        assert c.get("/v1/procesos/", headers={"X-License-Key": "BUENA"}).status_code == 200
        assert c.get("/v1/procesos/", params={"q": "%"}, headers={"X-License-Key": "BUENA"}).status_code == 200
        central._LIM_FALLOS._hits.clear()
        codigos = [c.get("/v1/procesos/", headers={"X-License-Key": f"MALA{i}"}).status_code for i in range(30)]
        assert 429 in codigos
    finally:
        central._LIM_FALLOS._hits.clear()
        for m in [m for m in sys.modules if m.startswith("servidor_central")]:
            del sys.modules[m]  # que otras pruebas importen la API con su propia configuración
