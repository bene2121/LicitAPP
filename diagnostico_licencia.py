"""
Diagnóstico de licencia — ejecutar desde la raíz del proyecto:
  python diagnostico_licencia.py
"""
import json, sys, os

exe_dir  = os.path.join("dist", "SECOP_Automatizador")
internal = os.path.join(exe_dir, "_internal")
lic_path = os.path.join(exe_dir, "licencias", "mi_licencia.lic")
pub_path = os.path.join(internal, "licencias", "claves", "publica.pem")

print(f"Licencia : {lic_path}")
print(f"  existe : {os.path.exists(lic_path)}")
print(f"Publica  : {pub_path}")
print(f"  existe : {os.path.exists(pub_path)}")

if not os.path.exists(lic_path):
    print("ERROR: falta mi_licencia.lic")
    sys.exit(1)
if not os.path.exists(pub_path):
    print("ERROR: falta publica.pem en _internal")
    sys.exit(1)

with open(lic_path) as f:
    data = json.load(f)

print(f"\nFormato .lic — claves: {list(data.keys())}")
if "payload" not in data or "firma" not in data:
    print("ERROR: formato incorrecto, faltan 'payload' o 'firma'")
    sys.exit(1)

payload = data["payload"]
firma   = bytes.fromhex(data["firma"])
print(f"Payload : {payload}")
print(f"Firma   : {len(firma)} bytes")

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    with open(pub_path, "rb") as f:
        pub = serialization.load_pem_public_key(f.read())
    payload_bytes = json.dumps(payload, sort_keys=True).encode()
    pub.verify(firma, payload_bytes, padding.PKCS1v15(), hashes.SHA256())
    print("\nFIRMA OK — la licencia es válida")
except Exception as e:
    print(f"\nFIRMA FALLA: {e}")
