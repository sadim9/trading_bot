#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  deploy/git_push.sh — Fix git locks and push to GitHub
#
#  Run this on your LOCAL machine (not the server) from the
#  trading_bot directory:
#
#    bash deploy/git_push.sh
#
# ─────────────────────────────────────────────────────────────
set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"
echo "📁 Working in: $REPO_DIR"

# Remove stale lock files
echo "🔓 Clearing git lock files..."
rm -f .git/index.lock .git/HEAD.lock .git/objects/maintenance.lock 2>/dev/null || true

# Unstage .env if it's tracked
git rm --cached .env 2>/dev/null && echo "  ✓ .env removed from tracking" || true
git rm --cached -r __pycache__ 2>/dev/null || true
git rm --cached -r dashboard/__pycache__ 2>/dev/null || true
git rm --cached -r signals/__pycache__ 2>/dev/null || true
git rm --cached -r strategies/__pycache__ 2>/dev/null || true

# Stage all changes
echo "📦 Staging changes..."
git add .

# Show what will be committed
echo "📋 Files to commit:"
git status --short | head -40

# Commit
echo "💾 Committing..."
git commit -m "fix: comprehensive platform fixes + new features

Bug Fixes:
- settings persistence across restarts (settings_store.py, /api/v1/settings)
- Discord/Telegram/WhatsApp alerts restored from persisted settings on startup
- watchlist scanner: fallback chain + error dicts instead of silent None returns
- mobile layout: comprehensive responsive CSS (column stacking, touch targets)
- 504 Gateway Timeout: nginx timeouts raised, uvicorn workers=2, resource limits
- security: .gitignore, .env untracked, X-Frame-Options=SAMEORIGIN, CSP fixed

New Features:
- TradingView data source (tvdatafeed + tradingview-ta, no API key needed)
- Dedicated Markov Chains tab with 5 Plotly charts (transition matrix, pi dist,
  state path, N-step forecast, return distribution)
- Chart range selector buttons + volume profile overlay
- Timezone offset setting (Qatar=UTC+3 default) in Account Settings
- /api/v1/settings REST endpoint for server-side settings persistence"

# Push
echo "🚀 Pushing to GitHub..."
git push origin main

echo ""
echo "✅ GitHub push complete!"
