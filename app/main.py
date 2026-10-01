"""FileSh server: builds the web app. Run with `python -m app.main`."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import STATIC_DIR, Settings
from app.context import AppContext
from app.routes import core, files, settings, share
from app.security import SecurityMiddleware
from app.utils import UnsafePathError

logger = logging.getLogger("filesh")


def create_app(config: Settings | None = None) -> FastAPI:
    ctx = AppContext(config or Settings())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await ctx.start_background()
        try:
            yield
        finally:
            await ctx.stop_background()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.ctx = ctx
    app.add_middleware(SecurityMiddleware, ports=ctx.ports, hostnames=ctx.hostnames)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    for module in (core, files, share, settings):
        app.include_router(module.router)

    # ---------- Errors: short messages only, never paths or stack traces ----------

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse({"error": exc.detail}, exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse({"error": "Invalid request"}, 400)

    @app.exception_handler(UnsafePathError)
    async def unsafe_path_error(request: Request, exc: UnsafePathError) -> JSONResponse:
        client = request.client.host if request.client else "-"
        logger.warning("Blocked unsafe path from %s", client)
        return JSONResponse({"error": "Access denied"}, 403)

    @app.exception_handler(Exception)
    async def server_error(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Unexpected error: %s", type(exc).__name__)
        return JSONResponse({"error": "Something went wrong"}, 500)

    return app


if __name__ == "__main__":
    from app.runner import main

    main()
