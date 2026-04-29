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

# Safely extract only the variables we need from .env.
# Using grep+sed avoids the "source .env" pitfall where unquoted values
# with spaces (e.g. APP_NAME=TradingBot API) cause bash to treat the
# second word as a command and fail with "API: command not found".
if [ -f .env ]; then
    DOMAIN=$(grep -E '^DOMAIN=' .env | head -1 | sed 's/^DOMAIN=//' | tr -d '"'"'"' ')
    CERTBOT_EMAIL=$(grep -E '^CERTBOT_EMAIL=' .env | head -1 | sed 's/^CERTBOT_EMAIL=//' | tr -d '"'"'"' ')
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

# Obtain certificate for apex domain AND www subdomain.
# The www cert is required so that mobile browsers, which often
# request www.theapextraders.com, don't get a TLS mismatch error.
docker run --rm \
    -v "$(pwd)/.certbot/conf:/etc/letsencrypt" \
    -v "$(pwd)/.certbot/www:/var/w