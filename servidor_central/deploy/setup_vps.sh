#!/usr/bin/env bash
# ============================================================
# LicitApp — Setup automático VPS Ubuntu 22.04
# Uso: bash setup_vps.sh
# Autor: Poly Modules — polymodulospvc@gmail.com
# ============================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; NC='\033[0m'; BOLD='\033[1m'

log()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1"; exit 1; }
step() { echo -e "\n${BLUE}${BOLD}━━━ $1 ━━━${NC}"; }

# ── Variables — editar antes de ejecutar ─────────────────────
DOMAIN="api.licitapp.co"
DB_PASS="$(openssl rand -base64 16 | tr -dc 'a-zA-Z0-9' | head -c 20)"
API_SECRET="$(openssl rand -base64 32 | tr -dc 'a-zA-Z0-9' | head -c 40)"
APP_DIR="/opt/licitapp"
APP_USER="licitapp"
PYTHON="python3.11"

echo -e "${BOLD}"
echo "  ██╗     ██╗ ██████╗██╗████████╗ █████╗ ██████╗ ██████╗ "
echo "  ██║     ██║██╔════╝██║╚══██╔══╝██╔══██╗██╔══██╗██╔══██╗"
echo "  ██║     ██║██║     ██║   ██║   ███████║██████╔╝██████╔╝"
echo "  ██║     ██║██║     ██║   ██║   ██╔══██║██╔═══╝ ██╔═══╝ "
echo "  ███████╗██║╚██████╗██║   ██║   ██║  ██║██║     ██║     "
echo "  ╚══════╝╚═╝ ╚═════╝╚═╝   ╚═╝   ╚═╝  ╚═╝╚═╝     ╚═╝     "
echo -e "${NC}"
echo "  Setup automático VPS — $(date '+%Y-%m-%d %H:%M')"
echo "  Dominio: $DOMAIN"
echo ""
warn "Este script requiere Ubuntu 22.04 y acceso root."
read -p "  ¿Continuar? [s/N]: " confirm
[[ "$confirm" =~ ^[sSyY]$ ]] || { echo "Abortado."; exit 0; }

# ── 1. Sistema ────────────────────────────────────────────────
step "1/8 Sistema y dependencias"
apt-get update -qq
apt-get install -y -qq \
    python3.11 python3.11-venv python3.11-dev \
    postgresql postgresql-contrib \
    nginx certbot python3-certbot-nginx \
    git curl wget unzip build-essential \
    libpq-dev supervisor ufw fail2ban
log "Sistema actualizado"

# ── 2. Firewall ───────────────────────────────────────────────
step "2/8 Firewall (UFW)"
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 'Nginx Full'
ufw --force enable
log "Firewall configurado"

# ── 3. PostgreSQL ─────────────────────────────────────────────
step "3/8 PostgreSQL"
systemctl enable postgresql
systemctl start postgresql
sudo -u postgres psql -c "CREATE USER licitapp WITH PASSWORD '$DB_PASS';" 2>/dev/null || \
    sudo -u postgres psql -c "ALTER USER licitapp WITH PASSWORD '$DB_PASS';"
sudo -u postgres psql -c "CREATE DATABASE licitapp_db OWNER licitapp;" 2>/dev/null || \
    warn "Base de datos ya existe"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE licitapp_db TO licitapp;"
log "PostgreSQL configurado — DB: licitapp_db"

# ── 4. Usuario de app ─────────────────────────────────────────
step "4/8 Usuario de aplicación"
id "$APP_USER" &>/dev/null || useradd -r -m -s /bin/bash "$APP_USER"
log "Usuario $APP_USER listo"

# ── 5. App ────────────────────────────────────────────────────
step "5/8 Instalar LicitApp API"
mkdir -p "$APP_DIR"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

# Crear entorno virtual
sudo -u "$APP_USER" $PYTHON -m venv "$APP_DIR/venv"
VENV="$APP_DIR/venv/bin"

# Copiar código (el usuario debe subir el código antes o usar git)
if [ -d "/tmp/servidor_central" ]; then
    cp -r /tmp/servidor_central "$APP_DIR/"
    log "Código copiado desde /tmp/servidor_central"
else
    warn "Código no encontrado en /tmp/servidor_central"
    warn "Sube el código con: scp -r servidor_central/ root@IP:/tmp/"
fi

# Instalar dependencias
sudo -u "$APP_USER" "$VENV/pip" install --upgrade pip -q
sudo -u "$APP_USER" "$VENV/pip" install \
    fastapi==0.110.0 \
    "uvicorn[standard]==0.29.0" \
    psycopg2-binary==2.9.9 \
    sqlalchemy==2.0.29 \
    alembic==1.13.1 \
    python-dotenv==1.0.1 \
    apscheduler==3.10.4 \
    httpx==0.27.0 \
    pydantic==2.7.0 \
    -q
log "Dependencias instaladas"

# ── 6. Variables de entorno ───────────────────────────────────
step "6/8 Configuración (.env)"
cat > "$APP_DIR/.env" << EOF
DATABASE_URL=postgresql://licitapp:${DB_PASS}@localhost/licitapp_db
API_SECRET_KEY=${API_SECRET}
SOCRATA_APP_TOKEN=
ENVIRONMENT=production
EOF
chown "$APP_USER:$APP_USER" "$APP_DIR/.env"
chmod 600 "$APP_DIR/.env"
log ".env creado (credenciales guardadas en $APP_DIR/.env)"

# ── 7. Systemd services ───────────────────────────────────────
step "7/8 Servicios systemd"

# API service
cat > /etc/systemd/system/licitapp-api.service << EOF
[Unit]
Description=LicitApp API Central
After=network.target postgresql.service
Requires=postgresql.service

[Service]
User=$APP_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$VENV/uvicorn servidor_central.main:app --host 127.0.0.1 --port 8000 --workers 2
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Scheduler service
cat > /etc/systemd/system/licitapp-sync.service << EOF
[Unit]
Description=LicitApp Sync SECOP (ingestor cada 6h)
After=licitapp-api.service
Requires=postgresql.service

[Service]
User=$APP_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$VENV/python -m servidor_central.scheduler_central
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable licitapp-api licitapp-sync
systemctl start licitapp-api || warn "API no inició (¿código copiado?)"
log "Servicios systemd creados"

# ── 8. Nginx + SSL ────────────────────────────────────────────
step "8/8 Nginx y SSL"

cat > /etc/nginx/sites-available/licitapp << EOF
server {
    listen 80;
    server_name $DOMAIN;
    return 301 https://\$host\$request_uri;
}
server {
    listen 443 ssl;
    server_name $DOMAIN;

    ssl_certificate     /etc/letsencrypt/live/$DOMAIN/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$DOMAIN/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;
    add_header X-XSS-Protection "1; mode=block";

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 60;
    }
}
EOF

ln -sf /etc/nginx/sites-available/licitapp /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
log "Nginx configurado"

# SSL (requiere que el dominio apunte a este servidor)
if host "$DOMAIN" &>/dev/null; then
    certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos \
        --email polymodulospvc@gmail.com --redirect || \
        warn "SSL falló — asegúrate que $DOMAIN apunte a $(curl -s ifconfig.me)"
else
    warn "SSL pendiente — apunta $DOMAIN a $(curl -s ifconfig.me) y ejecuta:"
    warn "  certbot --nginx -d $DOMAIN --email polymodulospvc@gmail.com"
fi

# ── Resumen ───────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}════════════════════════════════════════${NC}"
echo -e "${GREEN}${BOLD}  ✅ LicitApp VPS Setup Completado${NC}"
echo -e "${GREEN}${BOLD}════════════════════════════════════════${NC}"
echo ""
echo "  API URL:       https://$DOMAIN"
echo "  Health check:  https://$DOMAIN/v1/health"
echo "  Docs:          https://$DOMAIN/docs"
echo ""
echo "  DB Password:   $DB_PASS"
echo "  API Secret:    $API_SECRET"
echo ""
warn "Guarda las credenciales de arriba en un lugar seguro."
echo ""
echo "  Próximos pasos:"
echo "  1. scp -r servidor_central/ root@IP:/tmp/"
echo "  2. systemctl restart licitapp-api licitapp-sync"
echo "  3. Primera sync: sudo -u licitapp $VENV/python -m servidor_central.ingestor_central"
echo "  4. Verifica: curl https://$DOMAIN/v1/health"
echo ""
