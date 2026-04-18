"""
Purpose: Global error handlers — map exceptions to consistent JSON responses.
Registered on the FastAPI app in main.py via register_error_handlers().
"""
import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from models.exceptions import AppError

logger = logging.getLogger(__name__)


def _error_response(status_code: int, message: str, details=None) -> JSONResponse:
    body = {"error": message}
    if details:
        body["details"] = details
    return JSONResponse(status_code=status_code, content=body)


def register_error_handlers(app: FastAPI) -> None:

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        # 5xx errors được log ở mức ERROR, 4xx ở mức WARNING
        if exc.status_code >= 500:
            logger.error("AppError: %s", exc.message, exc_info=exc)
        else:
            logger.warning("AppError %s: %s", exc.status_code, exc.message)
        return _error_response(exc.status_code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        logger.warning("Validation error: %s", exc.errors())
        return _error_response(
            status_code=422,
            message="Invalid request body",
            details=exc.errors(),
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception: %s", exc)
        return _error_response(500, "Internal server error")
