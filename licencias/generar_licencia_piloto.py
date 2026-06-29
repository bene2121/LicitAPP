"""
LicitApp — Generador de licencia piloto (30 días gratis)
Uso: python generar_licencia_piloto.py --nit 900123456 --nombre "Empresa Piloto SAS" --plan pro
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def generar_licencia_piloto(nit: str, nombre: str, plan: str = "pro", dias: int = 30):
    """Genera una licencia de prueba usando el sistema RSA existente."""
    try:
        from licencias.admin_licencias import crear_licencia
        # crear_licencia requiere: nit, nombre, email, plan, meses
        # Para piloto usamos email vacío y convertimos días a meses (mínimo 1)
        meses = max(1, round(dias / 30))
        resultado = crear_licencia(
            nit=nit,
            nombre=nombre,
            email="",
            plan=plan,
            meses=meses,
            notas=f"Licencia piloto {dias} días — generada automáticamente",
        )
        return {"archivo": resultado, "datos": {"fecha_vencimiento": (datetime.now() + timedelta(days=dias)).strftime("%Y-%m-%d"), "features": _features_por_plan(plan)}}
    except ImportError:
        pass

    # Fallback: crear licencia simple si admin_licencias no está disponible
    try:
        import base64, hashlib

        datos = {
            "nit": nit,
            "nombre": nombre,
            "plan": plan,
            "fecha_emision": datetime.now().strftime("%Y-%m-%d"),
            "fecha_vencimiento": (datetime.now() + timedelta(days=dias)).strftime("%Y-%m-%d"),
            "features": _features_por_plan(plan),
            "tipo": "piloto",
        }

        # Intentar firmar con RSA si las claves existen
        clave_priv = os.path.join(os.path.dirname(__file__), "claves", "privada.pem")
        if os.path.exists(clave_priv):
            try:
                from cryptography.hazmat.primitives import hashes, serialization
                from cryptography.hazmat.primitives.asymmetric import padding
                with open(clave_priv, "rb") as f:
                    private_key = serialization.load_pem_private_key(f.read(), password=None)
                payload = json.dumps(datos, ensure_ascii=False, sort_keys=True).encode()
                signature = private_key.sign(payload, padding.PKCS1v15(), hashes.SHA256())
                datos["firma"] = base64.b64encode(signature).decode()
            except Exception as e:
                # C-3: Sin fallback inseguro — la firma RSA es obligatoria
                raise RuntimeError(
                    f"No se pudo firmar la licencia con RSA: {e}\n"
                    "Verifica que licencias/claves/privada.pem exista y sea válida."
                ) from e
        else:
            raise FileNotFoundError(
                "No se encontró licencias/claves/privada.pem.\n"
                "Ejecuta primero: python licencias/generar_claves.py"
            )

        # Guardar archivo .lic
        out_dir = os.path.join(os.path.dirname(__file__), "licencias_generadas")
        os.makedirs(out_dir, exist_ok=True)
        lic_file = os.path.join(out_dir, f"licencia_{nit}_piloto.lic")
        with open(lic_file, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=2)

        return {"archivo": lic_file, "datos": datos}
    except Exception as e:
        return {"error": str(e)}

def _features_por_plan(plan: str) -> list:
    base = ["explorador", "calculadora", "documentos", "alertas_email"]
    pro  = base + ["competidores", "seguimiento", "bot_dry_run", "entidades"]
    emp  = pro  + ["bot_real", "multi_usuario", "soporte_prioritario"]
    return {"basico": base, "pro": pro, "empresa": emp}.get(plan.lower(), pro)

def main():
    parser = argparse.ArgumentParser(description="Generar licencia piloto LicitApp")
    parser.add_argument("--nit",    required=True, help="NIT del cliente (sin digito de verificacion)")
    parser.add_argument("--nombre", required=True, help="Nombre de la empresa o persona")
    parser.add_argument("--plan",   default="pro", choices=["basico", "pro", "empresa"])
    parser.add_argument("--dias",   default=30, type=int, help="Dias de prueba")
    args = parser.parse_args()

    print(f"\nLicitApp -- Generando licencia piloto")
    print(f"   NIT:    {args.nit}")
    print(f"   Nombre: {args.nombre}")
    print(f"   Plan:   {args.plan.upper()}")
    print(f"   Dias:   {args.dias}")
    print()

    resultado = generar_licencia_piloto(args.nit, args.nombre, args.plan, args.dias)

    if "error" in resultado:
        print(f"ERROR: {resultado['error']}")
        sys.exit(1)

    lic_file = resultado.get("archivo", "")
    datos    = resultado.get("datos", resultado)

    print(f"OK Licencia generada: {lic_file}")
    print(f"\n   Vence: {datos.get('fecha_vencimiento', 'N/A')}")
    feats = datos.get("features", [])
    print(f"   Features ({len(feats)}): {', '.join(feats)}")
    print(f"\nEnvia este archivo al cliente junto con LEAME_CLIENTE.txt")
    print(f"   Archivo: {lic_file}")

if __name__ == "__main__":
    main()
