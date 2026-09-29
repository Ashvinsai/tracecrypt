"""FastAPI application wiring."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import Response

from app.core.envelope import error
from app.core.logging import configure_logging, get_logger
from app.core.settings import REPO_ROOT, AppEnv, get_settings
from app.routes import (
    addresses,
    auth,
    cases,
    console,
    demo_api,
    health,
    mock_complaints,
    traces,
    watches,
    unified,
    operations,
)

configure_logging()
log = get_logger(__name__)

HTTP_STATUS_TO_CODE = {
    400: "validation_error",
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    422: "validation_error",
    429: "budget_exceeded",
}


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="TraceCrypt Unified — Evidence-led Attribution",
        version=settings.engine_version,
        description=(
            "Read-only investigative triage. Does not identify persons, establish guilt, "
            "guarantee recovery, or execute freezes."
        ),
    )

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie=settings.session_cookie,
        max_age=settings.session_max_age_seconds,
        same_site="lax",
        https_only=settings.app_env is AppEnv.prod,
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method not in {"GET", "HEAD", "OPTIONS"} and (request.url.path.startswith(("/api/v1/operations", "/api/v1/integrations")) or "/cross-chain/" in request.url.path):
            chunks = []
            size = 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > 65536:
                    return JSONResponse(status_code=413, content=error("body_too_large", "intake body limit is 64 KiB"))
                chunks.append(chunk)
            request._body = b"".join(chunks)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            from urllib.parse import urlsplit
            origin = request.headers.get("origin")
            source = urlsplit(origin) if origin else None
            target = urlsplit(str(request.base_url))
            cross_site = request.headers.get("sec-fetch-site") == "cross-site"
            if cross_site or (source and (source.scheme, source.netloc) != (target.scheme, target.netloc)):
                return JSONResponse(status_code=403, content=error("forbidden", "cross-origin mutation refused"))
        supplied_id = request.headers.get("x-request-id", "")
        request_id = supplied_id if len(supplied_id) <= 80 and all(c.isascii() and (c.isalnum() or c in "._-") for c in supplied_id) and bool(supplied_id) else uuid.uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        response.headers["x-data-mode"] = settings.data_mode.value
        response.headers["x-content-type-options"] = "nosniff"
        response.headers["referrer-policy"] = "same-origin"
        if request.url.path.startswith("/api/v1/"):
            response.headers["cache-control"] = "no-store"
        return response

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        code = HTTP_STATUS_TO_CODE.get(exc.status_code, "error")
        return JSONResponse(
            status_code=exc.status_code,
            content=error(code, str(exc.detail)),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Only the field, the rule that failed, and the message. Pydantic's raw
        # errors carry the submitted input and the original exception object:
        # the first is complaint data we must not echo, the second is not
        # serializable at all.
        details = [
            {
                "field": ".".join(str(part) for part in err.get("loc", ())),
                "type": err.get("type", "value_error"),
                "message": str(err.get("msg", "invalid value")),
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=error("validation_error", "request validation failed", {"errors": details}),
        )

    app.include_router(health.router)
    #: The local, read-only demo console. It serves only allow-listed saved
    #: public/synthetic artifacts and carries no case data (see the module).
    #: It is a local prototype surface, so it is not registered in prod; a
    #: production console belongs behind the case-authorization dependency.
    if settings.app_env is not AppEnv.prod:
        app.include_router(console.router)
        app.include_router(console.site_router)
        #: Read-only JSON facade over the same allow-listed saved artifacts,
        #: for the React investigator workspace. Local prototype only.
        app.include_router(demo_api.router)
        #: The built investigator workspace. Served only when a production
        #: build is present; a clean checkout without node_modules still runs
        #: the server-rendered console at /console. Deep links fall back to the
        #: SPA shell so client-side routes survive a hard refresh.
        frontend_dist = REPO_ROOT / "frontend" / "dist"
        index_html = frontend_dist / "index.html"
        if index_html.is_file():

            @app.get("/investigator", include_in_schema=False)
            @app.get("/investigator/{path:path}", include_in_schema=False)
            def investigator_spa(path: str = "") -> FileResponse:
                if path:
                    candidate = (frontend_dist / path).resolve()
                    if frontend_dist.resolve() in candidate.parents and candidate.is_file():
                        return FileResponse(candidate)
                return FileResponse(index_html)
    app.include_router(auth.router)
    app.include_router(cases.router)
    app.include_router(addresses.router)
    app.include_router(traces.router)
    app.include_router(mock_complaints.router)
    app.include_router(watches.router)
    app.include_router(unified.router)
    app.include_router(operations.router)
    if settings.app_env is not AppEnv.prod:
        app.include_router(unified.demo_router)
    from fastapi.staticfiles import StaticFiles
    workspace = REPO_ROOT / "workspace"
    if workspace.is_dir():
        app.mount("/workspace", StaticFiles(directory=workspace, html=True), name="workspace")
    return app


app = create_app()
