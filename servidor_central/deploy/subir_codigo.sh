#!/usr/bin/env bash
# LicitApp — Subir código al VPS
# Uso: bash subir_codigo.sh IP_DEL_VPS
# Ejecutar desde la carpeta secop-automatizador/

set -euo pipefail

VPS_IP="${1:?Uso: bash subir_codigo.sh IP_DEL_VPS}"
VPS_USER="${2:-root}"

echo "📤 Subiendo servidor_central/ a $VPS_USER@$VPS_IP..."

# Copiar solo el servidor_central (no el cliente completo)
rsync -avz --progress \
    --exclude "__pycache__" \
    --exclude "*.pyc" \
    --exclude ".env" \
    servidor_central/ \
    "$VPS_USER@$VPS_IP:/tmp/servidor_central/"

echo ""
echo "✅ Código subido. Ahora en el VPS ejecuta:"
echo "   cp -r /tmp/servidor_central /opt/licitapp/"
echo "   systemctl restart licitapp-api licitapp-sync"
echo ""
echo "O si es la primera vez:"
echo "   bash /opt/licitapp/setup_vps.sh"
