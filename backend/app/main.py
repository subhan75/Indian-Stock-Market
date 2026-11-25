from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles

from . import errors, routes_auth, session
from .config import FRONTEND_DIR
from .routes import router

# Every change (POST/PUT/DELETE) must come from our own site; every data route also needs a signed-in user
# (see routes.py). Only /api/health and the sign-in routes are open.
# The interactive docs and schema are switched off: they would publish the API's structure to anyone.
app = FastAPI(title="Stock Analyst (India)", dependencies=[Depends(session.check_origin)],
              docs_url=None, redoc_url=None, openapi_url=None)
errors.install(app)
app.include_router(routes_auth.router)
app.include_router(router)


@app.get("/api/health")
def health():
    return {"ok": True}


# Mounted last so /api routes win. In production the frontend is served by Vercel; this is for local use.
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
