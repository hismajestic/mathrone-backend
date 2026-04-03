# ============================================================
#  Mathrone Academy — Dockerfile
# ============================================================
# Build:   docker build -t mathrone-backend .
# Run:     docker run --env-file .env -p 8000:8000 mathrone-backend
# ============================================================

FROM python:3.11-slim AS base

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Working directory
WORKDIR /app

# ── Install Python dependencies ──────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ── Copy application code ─────────────────────────────────────
COPY app/ ./app/

# ── Ownership ─────────────────────────────────────────────────
RUN chown -R appuser:appuser /app
USER appuser

# ── Expose port ───────────────────────────────────────────────
EXPOSE 8000

# ── Health check ──────────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# ── Start command ─────────────────────────────────────────────
# Workers = (2 × CPU cores) + 1  →  adjust --workers for your server
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "2", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*"]