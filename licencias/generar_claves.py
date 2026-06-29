"""
Genera el par de claves RSA para el sistema de licencias.
Ejecutar UNA SOLA VEZ al configurar el servidor.
Las claves se guardan en licencias/claves/
"""
import os
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

CLAVES_DIR = os.path.join(os.path.dirname(__file__), "claves")
os.makedirs(CLAVES_DIR, exist_ok=True)

priv_path = os.path.join(CLAVES_DIR, "privada.pem")
pub_path  = os.path.join(CLAVES_DIR, "publica.pem")

if os.path.exists(priv_path):
    print("⚠️  Las claves ya existen. Elimínalas manualmente si quieres regenerar.")
else:
    privada = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with open(priv_path, "wb") as f:
        f.write(privada.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ))
    with open(pub_path, "wb") as f:
        f.write(privada.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ))
    print("✅ Claves RSA generadas en licencias/claves/")
    print("   privada.pem  → guárdala SOLO en tu servidor, NUNCA la distribuyas")
    print("   publica.pem  → se embebe en la app del cliente")

if __name__ == "__main__":
    pass
