"""
PANEL ADMIN — Generador y gestor de licencias SECOP Automatizador.
Uso: python licencias/admin_licencias.py

Solo lo usa el vendedor (tú). Nunca se distribuye al cliente.
"""
import os, sys, json, sqlite3, hashlib, uuid
from datetime import datetime, timedelta
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes, serialization

BASE = os.path.dirname(os.path.abspath(__file__))
CLAVE_PRIVADA_PATH = os.path.join(BASE, "claves", "privada.pem")
# En producción (servidor Linux): la DB vive fuera de la carpeta distribuida al cliente
DB_ADMIN_PATH = os.getenv("SECOP_ADMIN_DB", os.path.join(os.path.expanduser("~"), "secop_clientes.db"))

PLANES = {
    "basico":    {"precio_mensual": 350_000,  "descripcion": "Dashboard + Simulador (sin bot)"},
    "pro":       {"precio_mensual": 650_000,  "descripcion": "Todo incluido + Bot SECOP 2"},
    "empresarial":{"precio_mensual": 1_200_000,"descripcion": "Multi-usuario + soporte prioritario"},
}

# ── Base de datos de clientes ─────────────────────────────────────────────────
def init_admin_db():
    conn = sqlite3.connect(DB_ADMIN_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS clientes (
            license_id      TEXT PRIMARY KEY,
            nit             TEXT NOT NULL,
            nombre          TEXT NOT NULL,
            email           TEXT,
            plan            TEXT NOT NULL,
            fecha_inicio    TEXT NOT NULL,
            fecha_vencimiento TEXT NOT NULL,
            activo          INTEGER DEFAULT 1,
            notas           TEXT,
            fecha_creacion  TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()

# ── Firmar licencia con clave privada RSA ─────────────────────────────────────
def firmar_payload(payload: dict) -> str:
    """Firma el payload y retorna la licencia completa como JSON string."""
    with open(CLAVE_PRIVADA_PATH, "rb") as f:
        privada = serialization.load_pem_private_key(f.read(), password=None)
    payload_bytes = json.dumps(payload, sort_keys=True).encode()
    firma = privada.sign(payload_bytes, padding.PKCS1v15(), hashes.SHA256())
    return json.dumps({
        "payload": payload,
        "firma": firma.hex()
    }, ensure_ascii=False, indent=2)

def crear_licencia(nit: str, nombre: str, email: str, plan: str, meses: int, notas: str = "") -> str:
    """Crea una licencia para un cliente y la guarda en la DB."""
    init_admin_db()
    license_id = str(uuid.uuid4())
    ahora = datetime.now()
    vencimiento = ahora + timedelta(days=30 * meses)

    payload = {
        "license_id":       license_id,
        "nit":              nit,
        "nombre":           nombre,
        "plan":             plan,
        "fecha_inicio":     ahora.strftime("%Y-%m-%d"),
        "fecha_vencimiento": vencimiento.strftime("%Y-%m-%d"),
        "version_app":      "1.0",
    }

    licencia_json = firmar_payload(payload)

    # Guardar en DB admin
    conn = sqlite3.connect(DB_ADMIN_PATH)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute("""
        INSERT INTO clientes (license_id, nit, nombre, email, plan, fecha_inicio, fecha_vencimiento, notas)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (license_id, nit, nombre, email, plan, payload["fecha_inicio"], payload["fecha_vencimiento"], notas))
    conn.commit()
    conn.close()

    # Guardar archivo de licencia
    out_dir = os.path.join(BASE, "licencias_generadas")
    os.makedirs(out_dir, exist_ok=True)
    nit_safe = "".join(c for c in nit if c.isalnum()) or "cliente"  # nunca separadores de ruta
    out_path = os.path.join(out_dir, f"licencia_{nit_safe}.lic")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(licencia_json)

    print(f"\n✅ Licencia creada para {nombre}")
    print(f"   NIT:         {nit}")
    print(f"   Plan:        {plan}  |  {meses} meses")
    print(f"   Vence:       {payload['fecha_vencimiento']}")
    print(f"   License ID:  {license_id}")
    print(f"   Archivo:     {out_path}")
    print(f"\n📧 Envía el archivo '{os.path.basename(out_path)}' al cliente.")
    print(f"   El cliente lo pone en: secop-automatizador/licencias/mi_licencia.lic\n")
    return out_path

def cancelar_licencia(nit: str):
    """Cancela la licencia de un cliente (bloqueo desde el servidor)."""
    init_admin_db()
    conn = sqlite3.connect(DB_ADMIN_PATH)
    cur = conn.execute("UPDATE clientes SET activo=0 WHERE nit=? AND activo=1", (nit,))
    affected = cur.rowcount
    conn.commit()
    conn.close()
    if affected:
        print(f"✅ Licencia de NIT {nit} cancelada. El cliente será bloqueado en máximo 24 horas.")
    else:
        print(f"⚠️  No se encontró licencia activa para NIT {nit}")

def listar_clientes():
    """Lista todos los clientes con su estado."""
    init_admin_db()
    conn = sqlite3.connect(DB_ADMIN_PATH)
    rows = conn.execute("""
        SELECT nit, nombre, plan, fecha_vencimiento, activo, email
        FROM clientes ORDER BY fecha_vencimiento DESC
    """).fetchall()
    conn.close()
    ahora = datetime.now().strftime("%Y-%m-%d")
    print(f"\n{'NIT':<18} {'Nombre':<30} {'Plan':<12} {'Vence':<12} {'Estado'}")
    print("-" * 90)
    for nit, nombre, plan, vence, activo, email in rows:
        if not activo:
            estado = "❌ CANCELADO"
        elif vence < ahora:
            estado = "⏰ VENCIDO"
        else:
            dias = (datetime.strptime(vence, "%Y-%m-%d") - datetime.now()).days
            estado = f"✅ Activo ({dias}d)"
        print(f"{nit:<18} {nombre:<30} {plan:<12} {vence:<12} {estado}")
    print()

def renovar_licencia(nit: str, meses: int):
    """Extiende la suscripción de un cliente."""
    init_admin_db()
    conn = sqlite3.connect(DB_ADMIN_PATH)
    row = conn.execute("SELECT fecha_vencimiento FROM clientes WHERE nit=? ORDER BY fecha_creacion DESC LIMIT 1", (nit,)).fetchone()
    if not row:
        print(f"⚠️  No se encontró cliente con NIT {nit}")
        conn.close()
        return
    vence_actual = datetime.strptime(row[0], "%Y-%m-%d")
    nueva_fecha = max(vence_actual, datetime.now()) + timedelta(days=30 * meses)
    conn.execute("UPDATE clientes SET activo=1, fecha_vencimiento=? WHERE nit=?",
                 (nueva_fecha.strftime("%Y-%m-%d"), nit))
    conn.commit()
    conn.close()
    print(f"✅ Licencia de {nit} renovada por {meses} meses. Nueva fecha: {nueva_fecha.strftime('%Y-%m-%d')}")

# ── Menú interactivo ──────────────────────────────────────────────────────────
def menu():
    print("\n" + "═"*50)
    print("  🏗️  SECOP Automatizador — Panel Admin")
    print("═"*50)
    print("  1. Crear nueva licencia")
    print("  2. Listar clientes")
    print("  3. Cancelar licencia")
    print("  4. Renovar licencia")
    print("  5. Salir")
    return input("\nOpción: ").strip()

if __name__ == "__main__":
    while True:
        op = menu()
        if op == "1":
            print("\n── Crear licencia ──")
            nit    = input("NIT del cliente: ").strip()
            nombre = input("Nombre empresa: ").strip()
            email  = input("Email contacto: ").strip()
            print("Planes disponibles:", ", ".join(PLANES.keys()))
            plan   = input("Plan (basico/pro/empresarial): ").strip().lower()
            meses  = int(input("Meses de suscripción: ").strip())
            notas  = input("Notas internas (opcional): ").strip()
            crear_licencia(nit, nombre, email, plan, meses, notas)
        elif op == "2":
            listar_clientes()
        elif op == "3":
            nit = input("NIT a cancelar: ").strip()
            cancelar_licencia(nit)
        elif op == "4":
            nit   = input("NIT a renovar: ").strip()
            meses = int(input("Meses adicionales: ").strip())
            renovar_licencia(nit, meses)
        elif op == "5":
            break
