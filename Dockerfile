# The backend API (FastAPI). Railway builds this automatically when the file exists.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first, so rebuilds that only change code are fast.
COPY requirements.txt .
RUN pip install -r requirements.txt

# The app, the bundled NSE company snapshot, and the static pages (so the API address can also serve the site).
COPY backend ./backend
COPY frontend ./frontend

# Run as a normal user, not root.
RUN useradd --create-home appuser
USER appuser

# Railway sets $PORT. 0.0.0.0 (IPv4) is what Railway's public edge reaches; an IPv6-only "::" listener gave
# "Application failed to respond" even though the app started.
# --proxy-headers lets the app see the real client address and https when it sits behind Vercel/Railway.
CMD ["sh", "-c", "exec uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
