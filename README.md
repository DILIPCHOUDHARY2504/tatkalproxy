# 🚀 Tatkal Proxy — Premium Telegram Proxy Marketplace

> **Tagline:** *Premium Proxy Store*  
> **Brand Identity:** Modern, Minimal, Secure, Professional

Tatkal Proxy is an enterprise-grade Telegram bot marketplace for purchasing and managing dedicated proxy subscriptions. Built from scratch with an async architecture, dual database support (SQLite locally, PostgreSQL in production), encrypted credential storage, automated expiry lifecycle management, and a dual-mode payment engine (Manual UPI with admin verification + signed automated gateway architecture).

---

## ⚡ Key Highlights

- 🔒 **Encrypted At Rest:** All proxy usernames and passwords are encrypted using AES-128-CBC/Fernet symmetric encryption.
- ⚡ **Atomic Inventory Allocation:** Database-level transaction locking ensures zero duplicate proxy allocations across concurrent purchases.
- 🌟 **Special IP Subnet Detection:** Automatically classifies `103.x.x.x` subnets as premium Special IP Proxies.
- 💳 **Dual Payment Engine:**
  - **Mode A (Manual UPI):** Dynamic QR codes with order notes, customer UTR submission, admin notification with one-tap inline [Approve] / [Reject] buttons. Customer UTR is never treated as proof of payment until verified by the admin in their bank records.
  - **Mode B (Automated Gateway):** Provider-independent architecture with HMAC-SHA256 signature verification, exact amount validation, order ID verification, and idempotent duplicate transaction prevention.
- ⏰ **Subscription Lifecycle Automation:** Powered by APScheduler with 24-hour reminders, 1-hour urgent warnings, and automatic transition of expired proxies to an `EXPIRED_HOLD` quarantine pool.
- 🛡️ **Quarantine Safeguard:** Expired proxies are **never** automatically resold. The admin must rotate credentials and explicitly release the proxy before it can be purchased again.
- 👑 **Advanced Admin Dashboard:** Live metrics, inventory importing (TXT & CSV), proxy search by IP, credential manager with audit trail, customer search & blocking, dynamic pricing updates, and sales reports.

---

## 📦 Project Structure

```
TatkalProxy/
├── bot.py                     # Main application entrypoint & bot runner
├── config.py                  # Pydantic environment configuration & secrets loader
├── requirements.txt           # Python dependency specifications
├── .env.example               # Template environment configuration
├── .gitignore                 # Git ignore rules
├── pytest.ini                 # Pytest runner configuration
├── setup.ps1                  # Windows automated one-click setup script
├── start.ps1                  # Windows application launch script
├── database/
│   ├── __init__.py
│   ├── connection.py          # SQLAlchemy 2.0 engine, pools & seed logic
│   ├── models.py              # 10 Relational SQLAlchemy models
│   └── crud.py                # Atomic database CRUD operations
├── handlers/
│   ├── __init__.py
│   ├── customer.py            # Storefront, browsing, ordering & renewals
│   └── admin.py               # Admin control panel, inventory & credentials
├── services/
│   ├── __init__.py
│   ├── crypto_service.py      # Fernet proxy encryption & decryption
│   ├── inventory_service.py   # TXT & CSV parsers, deduplication & delivery
│   ├── allocation_service.py  # Atomic proxy allocation & stock verification
│   ├── payment_service.py     # Manual UPI workflow & notification dispatch
│   ├── gateway_service.py     # HMAC signed gateway verification & idempotency
│   └── scheduler_service.py   # APScheduler subscription expiry automation
├── keyboards/
│   ├── __init__.py
│   ├── customer_kb.py         # Customer inline navigation keyboards
│   └── admin_kb.py            # Admin control panel inline keyboards
├── webhooks/
│   ├── __init__.py
│   └── api.py                 # FastAPI webhook server for gateway callbacks
├── utils/
│   ├── __init__.py
│   ├── logger.py              # Redacted logging with sensitive data filters
│   ├── validators.py          # IPv4, port, and proxy line validators
│   ├── qr_generator.py        # Dynamic UPI QR code generator
│   └── formatters.py          # Telegram HTML message formatting
├── assets/                    # Storage for QR codes and static media
├── uploads/                   # Temporary directory for uploaded batch lists
├── logs/                      # Rotating application logs
├── tests/                     # 25 Automated Pytest tests (100% passing)
│   ├── conftest.py
│   ├── test_admin.py
│   ├── test_allocation.py
│   ├── test_crypto.py
│   ├── test_database.py
│   ├── test_gateway.py
│   ├── test_inventory.py
│   ├── test_payments.py
│   ├── test_scheduler.py
│   └── test_validators.py
├── deployment/
│   ├── nginx.conf             # Nginx reverse proxy & rate limiter
│   ├── tatkalproxy.service    # Systemd service unit for Ubuntu
│   └── README.md              # Production VPS deployment documentation
├── Dockerfile                 # Multi-stage production container
└── docker-compose.yml         # Compose stack with PostgreSQL & FastAPI
```

---

## 💻 Local Windows Development (Quick Start)

### 1. Run Automated Setup

In PowerShell inside the project directory:

```powershell
.\setup.ps1
```

This automatically:
1. Validates your Python version (Python 3.11+).
2. Creates the Python virtual environment (`venv`).
3. Installs all project dependencies.
4. Ensures all directories exist.
5. Generates `.env` with a cryptographically secure `ENCRYPTION_KEY`.
6. Initializes the local SQLite database and seeds default subscription plans.

### 2. Configure Your `.env`

Open `.env` in any text editor and fill in your details:

```env
BOT_TOKEN=1234567890:ABCDefghIJKlmNoPQRsTUVwxyZ     # From @BotFather on Telegram
ADMIN_IDS=123456789                                 # Your numeric Telegram ID from @userinfobot
UPI_ID=yourname@okaxis                              # Your UPI ID for receiving payments
UPI_NAME=Tatkal Proxy Store                         # Your business display name
ENCRYPTION_KEY=...                                  # Auto-generated by setup.ps1
DATABASE_URL=sqlite:///tatkalproxy.db
```

### 3. Start the Application

Launch the bot and local services:

```powershell
.\start.ps1
```

Open Telegram, find your bot, and send `/start`!

---

## 📋 Subscription Plans

| Plan | Duration | Default Price | IP Pool |
| :--- | :--- | :--- | :--- |
| **Daily Proxy** | 1 day | ₹30 | Standard Pool |
| **Monthly Proxy** | 30 days | ₹399 | Standard Pool |
| **Special IP Proxy** | 30 days | ₹499 | Premium Dedicated 103.x.x.x Subnet |

*Note: Prices are stored dynamically in the database and can be changed in real time via the `/admin` menu.*

---

## 📦 Proxy Inventory Import Format

Upload `.txt` or `.csv` files directly to the bot inside the `/admin` -> **📦 Inventory** menu.

### TXT Format (One per line)
```text
103.10.20.30:8080:username:password
45.33.22.11:3128:proxyuser:proxypass
```

### Customer Delivery Format
Delivered proxies strictly follow:
```text
ip:host:user:pass
```
Example:
```text
103.10.20.30:8080:username:password
```

---

## 🧪 Automated Testing

Tatkal Proxy includes a comprehensive test suite covering all critical security, allocation, and business logic.

To run tests:

```powershell
.\venv\Scripts\pytest.exe -v
```

### Test Coverage Highlights:
- ✅ **Database Initialization:** Validates schema creation and seed plans.
- ✅ **TXT & CSV Import:** Tests batch ingestion, line parsing, and error reporting.
- ✅ **Duplicate Detection:** Checks duplicate IPs in files and against existing database records.
- ✅ **Special IP Classification:** Verifies `103.x.x.x` subnets vs standard IP ranges.
- ✅ **Dynamic Pricing:** Tests admin price updates and audit log generation.
- ✅ **Credential Encryption:** Asserts AES/Fernet encryption at rest and invalid token handling.
- ✅ **Atomic Allocation:** Ensures dedicated allocation matching plan type with race condition prevention.
- ✅ **Manual UPI Payment:** Tests UTR deduplication, admin approval, and proxy delivery dispatch.
- ✅ **Subscription Expiry:** Verifies 24h & 1h reminder flags and transition to `EXPIRED_HOLD`.
- ✅ **Quarantine Protection:** Asserts expired proxies cannot be resold without credential rotation.
- ✅ **Gateway Webhook Idempotency:** Validates HMAC SHA-256 signatures, amount integrity, and duplicate prevention.

---

## 🌐 Production VPS Deployment (Ubuntu)

For full instructions, see [deployment/README.md](file:///d:/tatkalproxy/deployment/README.md).

Quick Docker deployment on Ubuntu VPS:

```bash
git clone <YOUR_REPO> /opt/tatkalproxy
cd /opt/tatkalproxy
cp .env.example .env && nano .env
docker compose up -d --build
```
