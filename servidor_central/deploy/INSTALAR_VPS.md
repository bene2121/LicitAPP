# Instalación en VPS Ubuntu 22.04

## 1. Preparar servidor
sudo apt update && sudo apt install python3.11 python3.11-venv postgresql nginx certbot python3-certbot-nginx -y

## 2. PostgreSQL
sudo -u postgres psql
CREATE USER secop WITH PASSWORD 'TU_PASSWORD';
CREATE DATABASE secop_db OWNER secop;
\q

## 3. App
mkdir /opt/secop-api && cd /opt/secop-api
python3.11 -m venv venv
source venv/bin/activate
pip install -r servidor_central/requirements.txt
cp servidor_central/.env.example .env
# Editar .env con credenciales reales

## 4. Servicio systemd
sudo cp deploy/secop-api.service /etc/systemd/system/
sudo systemctl enable secop-api && sudo systemctl start secop-api

## 5. Nginx + SSL
sudo cp deploy/nginx.conf /etc/nginx/sites-available/secop-api
sudo ln -s /etc/nginx/sites-available/secop-api /etc/nginx/sites-enabled/
sudo certbot --nginx -d api.secop-automatizador.com
sudo systemctl restart nginx

## 6. Primera sync
python -m servidor_central.ingestor_central
