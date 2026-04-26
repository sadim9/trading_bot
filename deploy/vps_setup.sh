#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
#  Trading Bot — VPS Bootstrap Script
#  Tested on: Ubuntu 22.04 LTS (DigitalOcean Droplet)
#
#  What this script does:
#   1. Hardens the base OS (updates, non-root user, SSH)
#   2. Installs Docker + Docker Compose
#   3. Configures UFW firewall (only 22, 80, 443 open)
#   4. Installs Fail2ban (brute-force protection)
#   5. Configures automatic security updates
#   6. Clones your repo and prepares the environment
#
#  Usage:
#    ssh root@YOUR_VPS_IP
#    curl -O https://raw.githubusercontent.com/YOUR_REPO/main/deploy/vps_setup.sh
#    chmod +x vps_setup.sh
#    ./vps_setup.sh
# ─────────────────────────────────────────────────────────────

set -euo pipefail

# ── Configuration — edit before running ──────────────────────
DEPLOY_USER="trading"          # non-root user to create
DOMAIN=""                      # your domain (e.g. bot.example.com)
REPO_URL=""                    # git repo URL
SSH_PUB_KEY=""                 # paste your public key here

# ─────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()  { echo -e "${GREEN}[+]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
fail() { echo -e "${RED}[✗]${NC} $1"; exit 1; }

[ "$EUID" -ne 0 ] && fail "Run as root"
[ -z "$DOMAIN" ]  && fail "Set DOMAIN before running"

# ──────────────────────────���─────────────────────────────────
log "1/8  Updating system packages..."
# ───────────────────────────────���────────────────────────────
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq \
    curl wget git vim htop unzip \
    ufw fail2ban \
    ca-certificates gnupg lsb-release \
    unattended-upgrades apt-listchanges

# ────────────────────────────────────────────────��───────────
log "2/8  Creating deploy user: $DEPLOY_USER..."
# ────────────────────────────────────────────────────────────
if ! id "$DEPLOY_USER" &>/dev/null; then
    useradd -m -s /bin/bash -G sudo "$DEPLOY_USER"
    echo "$DEPLOY_USER ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers.d/"$DEPLOY_USER"
    chmod 0440 /etc/sudoers.d/"$DEPLOY_USER"
    log "  User $DEPLOY_USER created"
else
    warn "  User $DEPLOY_USER already exists, skipping"
fi

# Set up SSH key for deploy user
if [ -n "$SSH_PUB_KEY" ]; then
    mkdir -p /home/$DEPLOY_USER/.ssh
    echo "$SSH_PUB_KEY" >> /home/$DEPLOY_USER/.ssh/authorized_keys
    chmod 700 /home/$DEPLOY_USER/.ssh
    chmod 600 /home/$DEPLOY_USER/.ssh/authorized_keys
    chown -R $DEPLOY_USER:$DEPLOY_USER /home/$DEPLOY_USER/.ssh
    log "  SSH key installed for $DEPLOY_USER"
fi

# ──────────────────────────────────────────────────��─────────
log "3/8  Hardening SSH..."
# ────────────────────────────────────────────────────────────
SSH_CONFIG="/etc/ssh/sshd_config"
cp "$SSH_CONFIG" "${SSH_CONFIG}.bak"

# Apply hardening settings
cat >> "$SSH_CONFIG" << 'EOF'

# ── Trading Bot Security Hardening ──
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
AuthorizedKeysFile .ssh/authorized_keys
X11Forwarding no
AllowAgentForwarding no
AllowTcpForwarding no
MaxAuthTries 3
LoginGraceTime 30
ClientAliveInterval 300
ClientAliveCountMax 2
EOF

systemctl restart sshd
log "  SSH hardened (root login disabled, password auth disabled)"

# ────────────────────────────────────────────────────────────
log "4/8  Configuring UFW firewall..."
# ────────────────────────────────────────────────────────────
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp   comment "SSH"
ufw allow 80/tcp   comment "HTTP (redirect to HTTPS)"
ufw allow 443/tcp  comment "HTTPS"
ufw --force enable
log "  UFW enabled: only ports 22, 80, 443 are open"

# ────────────────────────────────────────────────────────────
log "5/8  Configuring Fail2ban..."
# ────────────────────────────────────────────────────────────
cat > /etc/fail2ban/jail.local << 'EOF'
[DEFAULT]
bantime  = 3600
findtime = 600
maxretry = 5
backend  = systemd

[sshd]
enabled  = true
port     = ssh
maxretry = 3
bantime  = 86400

[nginx-http-auth]
enabled  = true

[nginx-botsearch]
enabled  = true
EOF

systemctl enable fail2ban
systemctl restart fail2ban
log "  Fail2ban configured and started"

# ────────────────────────────────────────────────────────────
log "6/8  Enabling automatic security updates..."
# ────────────────────────────────────────────────────────────
cat > /etc/apt/apt.conf.d/50unattended-upgrades << 'EOF'
Unattended-Upgrade::Allowed-Origins {
    "${distro_id}:${distro_codename}-security";
};
Unattended-Upgrade::AutoFixInterruptedDpkg "true";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
Unattended-Upgrade::Automatic-Reboot "false";
EOF

cat > /etc/apt/apt.conf.d/20auto-upgrades << 'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF

log "  Unattended security upgrades enabled"

# ────────────────────────────────────────────────────────────
log "7/8  Installing Docker..."
# ────────────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
      | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg

    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] \
      https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
      > /etc/apt/sources.list.d/docker.list

    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin

    # Add deploy user to docker group (no sudo required)
    usermod -aG docker "$DEPLOY_USER"
    systemctl enable docker
    log "  Docker $(docker --version | awk '{print $3}') installed"
else
    warn "  Docker already installed, skipping"
fi

# ────────────────────────────────────────────────────────────
log "8/8  Cloning repository..."
# ────────────────────────────────────────────────────────────
APP_DIR="/home/$DEPLOY_USER/trading_bot"

if [ -n "$REPO_URL" ]; then
    if [ ! -d "$APP_DIR" ]; then
        sudo -u "$DEPLOY_USER" git clone "$REPO_URL" "$APP_DIR"
        log "  Repository cloned to $APP_DIR"
    else
        warn "  $APP_DIR already exists, skipping clone"
    fi
else
    warn "  REPO_URL not set — skipping clone. Create $APP_DIR manually."
    sudo -u "$DEPLOY_USER" mkdir -p "$APP_DIR"
fi

# ────────────────────────────────────────────────────────────
log ""
log "══════════════════════════════════════════════════════════"
log "  VPS bootstrap complete!"
log ""
log "  Next steps:"
log "  1. Log out and log back in as: $DEPLOY_USER"
log "  2. cd $APP_DIR"
log "  3. cp .env.example .env && nano .env   (fill in all values)"
log "  4. ./deploy/ssl_setup.sh              (get Let's Encrypt cert)"
log "  5. docker compose up -d               (start all services)"
log "══════════════════════════════════════════════════════════"
