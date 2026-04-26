# Trading Bot — VPS Deployment Guide

This guide walks through deploying the Trading Bot on a **DigitalOcean Droplet** using Docker Compose, with PostgreSQL, a FastAPI backend, Streamlit dashboard, Nginx reverse proxy, and Let's Encrypt TLS certificates.

---

## Recommended VPS: DigitalOcean

### Why DigitalOcean

DigitalOcean strikes the best balance of simplicity, cost, and reliability for a solo trading bot deployment. Their Droplets come with predictable pricing, a clean control panel, automated backups, and excellent documentation. The $12/month tier provides more than enough headroom for this stack.

### Recommended Droplet Spec

| Resource | Minimum | Recommended |
|---|---|---|
| Plan | Basic Shared CPU | Basic Shared CPU |
| vCPUs | 1 | 2 |
| RAM | 2 GB | 4 GB |
| SSD | 50 GB | 80 GB |
| Region | Choose closest to your broker | — |
| OS | Ubuntu 22.04 LTS x64 | Ubuntu 22.04 LTS x64 |
| **Cost** | ~$12/mo | ~$24/mo |

The 4 GB / 2 vCPU tier is strongly recommended — PostgreSQL, Redis, the API, the bot worker, and Streamlit all run concurrently.

Enable **Automated Backups** ($2.40/mo extra) and **Monitoring** (free) at creation time.

---

## Architecture Overview

```
Internet
    │
    ▼
[ Nginx :443 ]  ←── TLS termination (Let's Encrypt)
    │
    ├──/api/*  ────► [ FastAPI :8000 ]  ←── JWT auth, rate limiting
    ├──/ws     ────► [ FastAPI :8000 ]  ←── WebSocket (live updates)
    └──/       ────► [ Streamlit :8501 ] ←── Dashboard UI
                           │
                    [ Bot Worker ]  ←── Background signal loop
                           │
              ┌────────────┴────────────┐
         [ PostgreSQL :5432 ]   [ Redis :6379 ]
```

All services run in Docker containers on an isolated internal network. Only Nginx ports 80 and 443 are exposed to the internet. The database and Redis are never accessible externally.

---

## Step-by-Step Deployment

### Step 1 — Create the Droplet

1. Log in to [cloud.digitalocean.com](https://cloud.digitalocean.com)
2. Click **Create → Droplets**
3. Select: **Ubuntu 22.04 LTS**, Basic Shared CPU, 4 GB RAM / 2 vCPU
4. Choose a datacenter region close to your broker
5. Under **Authentication**, paste your SSH public key
6. Enable **Backups**
7. Click **Create Droplet**
8. Note the Droplet's IP address

### Step 2 — Point Your Domain to the VPS

In your DNS provider, create an **A record**:

```
Type: A
Name: @ (or "bot" for bot.yourdomain.com)
Value: YOUR_DROPLET_IP
TTL: 300
```

Wait a few minutes for DNS to propagate before proceeding.

### Step 3 — Run the Bootstrap Script

```bash
# SSH into the VPS as root
ssh root@YOUR_DROPLET_IP

# Download and run the bootstrap script
curl -O https://raw.githubusercontent.com/YOUR_REPO/main/deploy/vps_setup.sh

# Edit the script to set your DOMAIN, DEPLOY_USER, and SSH_PUB_KEY
nano vps_setup.sh

chmod +x vps_setup.sh
./vps_setup.sh
```

The script will:
- Update and harden the OS
- Create a non-root `trading` user
- Disable root SSH login and password authentication
- Configure UFW firewall (only ports 22, 80, 443 open)
- Install Fail2ban (SSH brute-force protection)
- Enable automatic security updates
- Install Docker and Docker Compose
- Clone your repository

### Step 4 — Configure Environment Variables

```bash
# Switch to the deploy user
su - trading
cd ~/trading_bot

# Copy the example and fill in all values
cp .env.example .env
nano .env
```

Critical values to set in `.env`:

```bash
# Generate a strong secret key:
python3 -c "import secrets; print(secrets.token_hex(64))"

SECRET_KEY=<paste output here>
POSTGRES_PASSWORD=<strong random password>
DOMAIN=yourdomain.com
CERTBOT_EMAIL=your@email.com
CORS_ORIGINS=https://yourdomain.com
```

### Step 5 — Get TLS Certificate

```bash
chmod +x deploy/ssl_setup.sh
./deploy/ssl_setup.sh
```

This obtains a free Let's Encrypt certificate for your domain. The `certbot` container in Docker Compose will automatically renew it every 60 days.

### Step 6 — Start All Services

```bash
docker compose up -d
```

Check that all services started:

```bash
docker compose ps
```

You should see all services as `healthy`. Check logs if any service failed:

```bash
docker compose logs api
docker compose logs db
```

### Step 7 — Create the Admin User

The first user to register gets `trader` role by default. To promote them to admin, connect directly to the database:

```bash
docker compose exec db psql -U trading -d trading_bot

# Inside psql:
UPDATE users SET role = 'admin' WHERE username = 'your_username';
\q
```

### Step 8 — Verify the Deployment

```bash
# Health check
curl https://yourdomain.com/health

# API docs (only available in development mode)
# Visit: https://yourdomain.com/docs

# Dashboard
# Visit: https://yourdomain.com
```

---

## Security Hardening Summary

The deployment applies defence-in-depth across multiple layers:

**Network Layer**
- UFW firewall allows only ports 22 (SSH), 80 (HTTP→HTTPS redirect), 443 (HTTPS)
- All inter-service communication is on an isolated Docker bridge network
- PostgreSQL and Redis are never exposed to the internet

**TLS / Transport**
- TLS 1.2 and 1.3 only (TLS 1.0 and 1.1 disabled)
- Modern cipher suites only (ECDHE + AES-GCM / ChaCha20)
- HSTS with 2-year max-age, includeSubDomains, preload
- OCSP stapling enabled
- SSL session tickets disabled (forward secrecy)

**Application Layer**
- JWT tokens: 15-minute access tokens + 7-day refresh tokens
- Passwords: bcrypt with cost factor 12
- Account lockout after 5 failed login attempts (15-minute lockout)
- Rate limiting: 60 req/min general, 1 req/s on auth endpoints (Nginx + FastAPI)
- CORS restricted to configured origins only
- Security headers: CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy
- Input validation via Pydantic on every endpoint
- SQL injection prevention via SQLAlchemy ORM (parameterised queries)
- No raw SQL strings anywhere in the codebase

**Audit Trail**
- Every login, logout, failed login, trade, and admin action is written to `audit_logs`
- Logs include IP address, user agent, timestamp, and action detail

**Infrastructure**
- Fail2ban: bans IPs with 3+ failed SSH attempts for 24 hours
- Automatic unattended security upgrades
- Root login disabled; deploy user has passwordless sudo
- Containers run as non-root user (`trading`)
- Multi-stage Docker builds to minimise attack surface

---

## Ongoing Operations

### Updating the Application

```bash
cd ~/trading_bot
git pull
docker compose build --no-cache api frontend worker
docker compose up -d
```

### Viewing Logs

```bash
docker compose logs -f api        # FastAPI logs
docker compose logs -f worker     # Bot worker
docker compose logs -f nginx      # Nginx access/error logs
```

### Database Backups

```bash
# Manual backup
docker compose exec db pg_dump -U trading trading_bot > backup_$(date +%Y%m%d).sql

# Restore from backup
docker compose exec -T db psql -U trading trading_bot < backup_20260425.sql
```

Set up a daily automated backup with cron:

```bash
crontab -e
# Add this line:
0 2 * * * cd ~/trading_bot && docker compose exec -T db pg_dump -U trading trading_bot | gzip > ~/backups/trading_$(date +\%Y\%m\%d).sql.gz
```

### Monitoring

DigitalOcean's built-in monitoring (enabled at Droplet creation) tracks CPU, memory, disk, and bandwidth with alerting. For more detailed application metrics, consider adding:

- **Grafana + Prometheus** — `docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up -d`
- **Uptime Robot** (free) — external HTTP check on `https://yourdomain.com/health` with SMS/email alerts

### Scaling

When you outgrow the single Droplet:

1. **Scale vertically first** — DigitalOcean lets you resize Droplets with minimal downtime
2. **Separate the database** — Move PostgreSQL to a DigitalOcean Managed Database (~$15/mo for basic). Eliminates manual backup management and provides automatic failover
3. **Scale the API horizontally** — Increase `--workers` in `Dockerfile.api` or add a second Droplet behind a DigitalOcean Load Balancer

---

## Troubleshooting

| Symptom | Check |
|---|---|
| `502 Bad Gateway` | `docker compose ps` — is the `api` service healthy? |
| Can't connect to DB | `docker compose logs db` — check credentials in `.env` |
| SSL certificate error | Check `docker compose logs certbot`, verify DNS A record is correct |
| Login fails | Check `audit_logs` table for failed login entries, verify rate limits |
| Bot not generating signals | `docker compose logs worker`, check `BOT_WORKER_USER_ID` in `.env` |

---

## Cost Summary

| Item | Monthly Cost |
|---|---|
| DigitalOcean Droplet (4 GB / 2 vCPU) | $24.00 |
| Automated Backups (20%) | $4.80 |
| Domain name (annual) | ~$1.00 |
| Let's Encrypt TLS certificate | Free |
| **Total** | **~$30/month** |
