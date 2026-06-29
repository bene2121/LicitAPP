"""
Genera la licencia de desarrollador para LicitApp.
Uso: python licencias/generar_licencia_dev.py

Crea mi_licencia.lic en el formato exacto que espera validador.py:
  {"payload": {...}, "firma": "<hex>"}

Y la copia automaticamente a:
  - licencias/mi_licencia.lic          (desarrollo)
  - dist/SECOP_Automatizador/licencias/mi_licencia.lic  (exe compilado)
"""
import json
import os
import sys
import uuid
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CLAVE_PRIV = os.path.join(os.path.dirname(__file__), "claves", "privada.pem")

def generar(nit="900000001", nombre="Poly Developer", plan="empresa", dias=3650):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    with open(CLAVE_PRIV, "rb") as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None)

    payload = {
        "license_id": str(uuid.uuid4()),
        "nit": nit,
        "nombre": nombre,
        "plan": plan,
        "fecha_vencimiento": (datetime.now() + timedelta(days=dias)).strftime("%Y-%m-%d"),
    }

    payload_bytes = json.dumps(payload, sort_keys=True).encode()
    signature = private_key.sign(payload_bytes, padding.PKCS1v15(), hashes.SHA256())

    licencia = {
        "payload": payload,
        "firma": signature.hex(),
    }

    contenido = json.dumps(licencia, ensure_ascii=False, indent=2)

    # Directorios destino
    destinos = [
        os.path.join(os.path.dirname(__file__), "mi_licencia.lic"),
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "dist",
                     "SECOP_Automatizador", "licencias", "mi_licencia.lic"),
    ]

    for ruta in destinos:
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(contenido)
        print(f"OK  {ruta}")

    print(f"\nLicencia generada para: {nombre} | Plan: {plan} | Vence: {payload['fecha_vencimiento']}")

if __name__ == "__main__":
    generar()
