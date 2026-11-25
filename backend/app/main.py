from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import errors
from .config import FRONTEND_DIR
from .routes import router

app = FastAPI(title="Stock Analyst (India)")
errors.install(app)
app.include_router(router)


@app.get("/api/health")
def health():
    return {"ok": True}


# Mounted last so /api routes win. In production the frontend is served by Vercel; this is for local use.
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
