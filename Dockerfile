# =====================================================================
# TATKAL PROXY - PRODUCTION DOCKERFILE
# =====================================================================

FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies (including libpq for PostgreSQL)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create application user
RUN groupadd -r tatkal && useradd -r -g tatkal -d /app -s /sbin/nologin tatkal

WORKDIR /app

# Copy dependency definition
COPY requirements.txt .

# Install dependencies (including PostgreSQL driver)
RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && pip install psycopg2-binary>=2.9.9

# Copy application source code
COPY . .

# Ensure directory permissions for runtime uploads and logs
RUN mkdir -p uploads logs assets \
    && chown -R tatkal:tatkal /app

USER tatkal

# Expose FastAPI webhook port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default command: Runs the production bot
CMD ["python", "bot.py"]
