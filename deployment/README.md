# Tatkal Proxy — Production Deployment Guide (Ubuntu VPS)

This guide provides end-to-end instructions for deploying **Tatkal Proxy** on an online Ubuntu 22.04 / 24.04 LTS VPS with PostgreSQL, Nginx, HTTPS, and Docker or Systemd.

---

## 1. Architecture Overview

- **Host OS:** Ubuntu 22.04 / 24.04 LTS (x86_64)
- **Database:** PostgreSQL 15+ (Production connection pooling)
- **Application Engine:** Python 3.11+ / AsyncIO Telegram Bot (v21+)
- **Expiry Scheduler:** APScheduler (Guaranteed single instance in `bot.py`)
- **Webhooks:** FastAPI + Uvicorn (Port 8000)
- **Reverse Proxy:** Nginx (Rate limiting + Let's Encrypt TLS 1.3)
- **Security:** Fernet credential encryption at rest, numeric Telegram Admin ID authorization, HMAC-SHA256 signature verification.

---

## 2. Server Preparation

Connect to your Ubuntu VPS via SSH:

```bash
ssh root@YOUR_SERVER_IP
```

Update system packages:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl ufw uvicorn nginx certbot python3-certbot-nginx
```

Configure Firewall (UFW):

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
```

Create a dedicated non-root application user:

```bash
sudo useradd -m -s /bin/bash tatkal
sudo usermod -aG sudo tatkal
```

---

## 3. Option A: Deployment with Docker & Docker Compose (Recommended)

### Step 1: Install Docker & Docker Compose

```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker tatkal
```

### Step 2: Clone Repository

```bash
su - tatkal
git clone <YOUR_GIT_REPO_URL> /opt/tatkalproxy
cd /opt/tatkalproxy
```

### Step 3: Configure Environment Variables

```bash
cp .env.example .env
nano .env
```

Ensure you configure:
- `BOT_TOKEN`: Token from Telegram `@BotFather`.
- `ADMIN_IDS`: Your numeric Telegram ID (e.g. from `@userinfobot`).
- `UPI_ID`: Your UPI payment address.
- `ENCRYPTION_KEY`: Generate via `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
- `ENVIRONMENT=production`
- `WEBHOOK_HOST=https://yourdomain.com`
- `PAYMENT_GATEWAY_WEBHOOK_SECRET`: Secure HMAC random key.

### Step 4: Launch Containers

```bash
docker compose up -d --build
```

Check running services:

```bash
docker compose ps
docker compose logs -f bot
```

---

## 4. Option B: Native Systemd Deployment (Without Docker)

### Step 1: Install PostgreSQL

```bash
sudo apt install -y postgresql postgresql-contrib python3-pip python3-venv libpq-dev
sudo -u postgres psql -c "CREATE DATABASE tatkal_proxy;"
sudo -u postgres psql -c "CREATE USER tatkal_user WITH ENCRYPTED PASSWORD 'YOUR_STRONG_PASSWORD';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE tatkal_proxy TO tatkal_user;"
```

### Step 2: Setup Python Virtual Environment

```bash
cd /opt/tatkalproxy
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt
./venv/bin/pip install psycopg2-binary
```

Configure `.env` with:
```env
DATABASE_URL=postgresql+psycopg2://tatkal_user:YOUR_STRONG_PASSWORD@localhost:5432/tatkal_proxy
```

Initialize database schema:
```bash
./venv/bin/python -c "from database.connection import init_db; init_db()"
```

### Step 3: Install & Start Systemd Service

```bash
sudo cp deployment/tatkalproxy.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable tatkalproxy
sudo systemctl start tatkalproxy
sudo systemctl status tatkalproxy
```

---

## 5. Nginx & SSL Certificate Setup

### Step 1: Configure Nginx

```bash
sudo cp deployment/nginx.conf /etc/nginx/sites-available/tatkalproxy
sudo ln -s /etc/nginx/sites-available/tatkalproxy /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
```

Edit `/etc/nginx/sites-available/tatkalproxy` and replace `yourdomain.com` with your actual domain name pointing to the VPS IP.

### Step 2: Obtain Let's Encrypt SSL Certificate

```bash
sudo certbot --nginx -d yourdomain.com -d api.yourdomain.com
```

### Step 3: Restart Nginx

```bash
sudo nginx -t
sudo systemctl restart nginx
```

---

## 6. Single Expiry Scheduler Guarantee

In Tatkal Proxy, the background APScheduler is managed by `services/scheduler_service.py` with:
- `replace_existing=True`
- `max_instances=1`
- `coalesce=True`

In production, the scheduler runs strictly within the `bot` service (or `tatkalproxy.service`). When scaling webhooks or API workers, the scheduler remains bound to the single bot master instance, preventing duplicate expiry notices or race conditions.

---

## 7. Database Backup & Disaster Recovery

### Automated Nightly Backup Cron Job

Create backup script `/opt/tatkalproxy/backup.sh`:

```bash
#!/bin/bash
BACKUP_DIR="/opt/tatkalproxy/backups"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
mkdir -p "$BACKUP_DIR"

# Docker PostgreSQL Backup
docker exec tatkalproxy_db pg_dump -U tatkal_user tatkal_proxy | gzip > "$BACKUP_DIR/db_backup_$TIMESTAMP.sql.gz"

# Keep last 14 days of backups
find "$BACKUP_DIR" -type f -name "*.sql.gz" -mtime +14 -delete
```

Make executable and add to crontab:

```bash
chmod +x /opt/tatkalproxy/backup.sh
crontab -e
# Add: Run daily at 03:00 AM UTC
0 3 * * * /opt/tatkalproxy/backup.sh
```

### Database Restoration

To restore from a backup:

```bash
gunzip -c /opt/tatkalproxy/backups/db_backup_YYYYMMDD_HHMMSS.sql.gz | docker exec -i tatkalproxy_db psql -U tatkal_user -d tatkal_proxy
```
