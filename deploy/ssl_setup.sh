#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────��
#  Let's Encrypt SSL Certificate Setup
#  Run AFTER vps_setup.sh and BEFORE docker compose up
#
#  Usage:
#    cd ~/trading_bot
#    chmod +x deploy/ssl_setup.sh
#    ./deploy/ssl_setup.sh
# ─────────────────────────────────────────────────────────────

set -euo pipefail

# Load domain from .env
if [ -f .env ]; then
    source .env
fi

[ -z "${DOMAIN:-}" ]          && { echo "Set DOMAIN in .env"; exit 1; }
[ -z "${CERTBOT_EMAIL:-}" ]   && { echo "Set CERTBOT_EMAIL in .env"; exit 1; }

echo "[+] Getting certificate for $DOMAIN via Certbot standalone..."

# Update nginx.conf with the actual domain
sed -i "s/DOMAIN_PLACEHOLDER/$DOMAIN/g" nginx/nginx.conf

# Temporarily start Nginx on port 80 only (no SSL yet) using a minimal config
docker run --rm -d --name tmp_nginx \
    -p 80:80 \
    -v "$(pwd)/nginx/nginx.conf:/etc/nginx/nginx.conf:ro" \
    nginx:1.25-alpine || true

sleep 2

# Obtain certificate
docker run --rm \
    -v "$(pwd)/.certbot/conf:/etc/letsencrypt" \
    -v "$(pwd)/.certbot/www:/var/www/certbot" \
    certbot/certbot certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    --email "$CERTBOT_EMAIL" \
    --agree-tos \
    --no-eff-email \
    -d "$DOMAIN"

docker stop tmp_nginx 2>/dev/null || true

# Create Docker named volumes and copy certs into them
echo "[+] Certificates obtained for $DOMAIN"
echo "[+] You can now run: docker compose up -d"
