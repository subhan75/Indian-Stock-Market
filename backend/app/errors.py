"""API errors always look like {"error": {"code": ..., "message": ...}} (v0 contract)."""
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

STATUS = {"not_found": 404, "source_unavailable": 503, "bad_request": 400}


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
