#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  deploy/redeploy.sh — Pull latest code & redeploy on DigitalOcean
#
#  Run this ON THE SERVER (SSH in first):
#    ssh root@theapextraders.com
#    cd /opt/trading_bot   (or wherever you deployed)
#    bash deploy/redeploy.sh
#
# ─────────────────────────────────────────────────────────────
set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  APEX TERMINAL — Production Redeploy"
echo "  $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 1. Pull latest code
echo "📥 Pulling latest from GitHub..."
git pull origin main
echo ""

# 2. Stop services gracefully
echo "🛑 Stopping services..."
docker compose down --remove-orphans 2>/dev/null || docker-compose down --remove-orphans
echo ""

# 3. Remove old frontend/api images to force rebuild with new code
echo "🧹 Removing stale images..."
docker rmi $(docker images -q --filter "reference=*_frontend" 2>/dev/null) 2>/dev/null || true
docker rmi $(docker images -q --filter "reference=*_api") 2>/dev/null || true
docker rmi $(docker images -q --filter "reference=*_worker") 2>/dev/null || true

# 4. Prune dangling images/volumes (not named volumes — keeps DB data)
docker image prune -f
echo ""

# 5. Build and start all services
echo "🔨 Building services..."
docker compose build --no-cache api frontend worker
echo ""

echo "🚀 Starting services..."
docker compose up -d
echo ""

# 6. Wait for health checks
echo "⏳ Waiting for services to become healthy (60s)..."
sleep 15

echo "  Checking API health..."
for i in {1..6}; do
    if curl -fsS http://localhost:8000/health > /dev/null 2>&1; then
        echo "  ✅ API healthy"
        break
    fi
    echo "  ... waiting ($i/6)"
    sleep 10
done

echo "  Checking Frontend health..."
for i in {1..6}; do
    if curl -fsS http://localhost:8501/_stcore/health > /dev/null 2>&1; then
        echo "  ✅ Frontend healthy"
        break
    fi
    echo "  ... waiting ($i/6)"
    sleep 10
done

# 7. Show container status
echo ""
echo "📊 Container status:"
docker compose ps
echo ""

# 8. Tail logs briefly
echo "📋 Recent logs (last 20 lines each):"
echo "--- API ---"
docker compose logs --tail=20 api 2>&1 | tail -10
echo ""
echo "--- Frontend ---"
docker compose logs --tail=20 frontend 2>&1 | tail -10

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ Redeploy complete!  https://theapextraders.com"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
