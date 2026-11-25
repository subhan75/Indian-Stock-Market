from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import FRONTEND_DIR
from .db import init_db
from . import errors
from .routes import router


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Stock Analyst (India) v0", lifespan=lifespan)
errors.install(app)
app.include_router(router)


@app.get("/api/health")
def health():
    return {"ok": True}


# Mounted last so /api routes win.
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
