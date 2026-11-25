"""API errors always look like {"error": {"code": ..., "message": ...}} (v0 contract, extended in V1)."""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import store

log = logging.getLogger("stock_analyst.errors")

STATUS = {
    "not_found": 404, "source_unavailable": 503, "bad_request": 400,
    "unauthorized": 401, "forbidden": 403, "rate_limited": 429,
}
SIGN_IN = "Please sign in."
DB_DOWN = "The database isn't reachable right now. Try again in a minute."


class ApiError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message


def _body(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return JSONResponse(_body(exc.code, exc.message), status_code=STATUS[exc.code])

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, __: RequestValidationError):
        return JSONResponse(_body("bad_request", "That request wasn't valid."), status_code=400)

    @app.exception_handler(store.NotAuthorized)
    async def _not_authorized(_: Request, __: store.NotAuthorized):
        return JSONResponse(_body("unauthorized", SIGN_IN), status_code=401)

    @app.exception_handler(store.StoreError)
    async def _store_error(_: Request, exc: store.StoreError):
        # Details go to the log only, never to the user.
        log.warning("Database error: %s", exc)
        return JSONResponse(_body("source_unavailable", DB_DOWN), status_code=503)

    @app.exception_handler(store.NoStore)
    async def _no_store(_: Request, exc: store.NoStore):
        log.error("Saved data was used outside a signed-in request: %s", exc)
        return JSONResponse(_body("unauthorized", SIGN_IN), status_code=401)
