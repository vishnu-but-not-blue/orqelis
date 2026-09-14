import json
import logging
import secrets
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from starlette.exceptions import HTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api import router
from app.config import settings
from app.db import SessionLocal, initialize_database
from app.ingest import register_sources
from app.observability import metrics
from app.observability import router as diagnostics_router
from app.reviews import router as reviews_router
from app.security import BodyLimitMiddleware

log = logging.getLogger("orqelis.http")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@asynccontextmanager
async def lifespan(app):
    config = settings()
    config.validate_deployment()
    if config.environment in {"local", "test"}:
        initialize_database()
    with SessionLocal() as db:
        register_sources(db)
    app.state.signing_key = config.secret_key or secrets.token_urlsafe(48)
    yield


app = FastAPI(
    title="Orqelis API",
    version="1.0",
    lifespan=lifespan,
    docs_url="/api/docs" if settings().environment != "production" else None,
    redoc_url=None,
)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=list(
        {urlparse(settings().base_url).hostname, "localhost", "127.0.0.1", "testserver"}
    ),
)
app.include_router(router)
app.include_router(diagnostics_router)
app.include_router(reviews_router)
app.add_middleware(BodyLimitMiddleware, limit=settings().max_upload_bytes + 65536)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
rate_windows = defaultdict(deque)


@app.middleware("http")
async def guard(request: Request, call_next):
    started = time.monotonic()
    request_id = secrets.token_hex(12)
    request.state.request_id = request_id
    path = request.url.path
    response = None
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != settings().base_url.rstrip("/"):
            response = JSONResponse(
                {"error": {"code": "origin_denied", "message": "Untrusted request origin."}}, 403
            )
        try:
            if (
                int(request.headers.get("content-length", "0"))
                > settings().max_upload_bytes + 65536
            ):
                response = JSONResponse(
                    {"error": {"code": "body_too_large", "message": "Request body exceeds limit."}},
                    413,
                )
        except ValueError:
            response = JSONResponse(
                {"error": {"code": "invalid_length", "message": "Invalid content length."}}, 400
            )
    if path.startswith("/api/v1/auth/"):
        key = request.client.host if request.client else "unknown"
        window = rate_windows[key]
        while window and window[0] < started - 60:
            window.popleft()
        if len(window) >= 20:
            response = JSONResponse(
                {
                    "error": {
                        "code": "rate_limited",
                        "message": "Too many sign-in attempts. Retry in a minute.",
                    }
                },
                429,
                headers={"Retry-After": "60"},
            )
        window.append(started)
        if len(rate_windows) > 10000:
            for old in list(rate_windows)[:5000]:
                if not rate_windows[old] or rate_windows[old][-1] < started - 60:
                    del rate_windows[old]
    if response is None:
        response = await call_next(request)
    response.headers.update(
        {
            "X-Request-ID": request_id,
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "X-Frame-Options": "DENY",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'; object-src 'none'",
            "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        }
    )
    metrics[f"http_{response.status_code // 100}xx"] += 1
    metrics["requests"] += 1
    if not path.startswith("/static"):
        response.headers["Cache-Control"] = "no-store"
    if settings().environment == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    log.info(
        json.dumps(
            {
                "request_id": request_id,
                "operation": request.method,
                "route": request.scope.get("route").path
                if request.scope.get("route")
                else "unmatched",
                "duration": round(time.monotonic() - started, 3),
                "result": response.status_code,
            }
        )
    )
    return response


@app.exception_handler(HTTPException)
async def http_error(request, exc):
    return JSONResponse(
        {
            "error": {
                "code": str(exc.status_code),
                "message": str(exc.detail),
                "request_id": getattr(request.state, "request_id", ""),
            }
        },
        exc.status_code,
    )


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    return JSONResponse(
        {
            "error": {
                "code": "validation_error",
                "message": "; ".join(
                    f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
                ),
            }
        },
        422,
    )


@app.exception_handler(Exception)
async def unexpected_error(request, exc):
    log.error(
        json.dumps(
            {"request_id": getattr(request.state, "request_id", ""), "error": type(exc).__name__}
        )
    )
    return JSONResponse(
        {
            "error": {
                "code": "unavailable",
                "message": "This operation could not complete. Please retry; contact support with the request ID if it persists.",
                "request_id": getattr(request.state, "request_id", ""),
            }
        },
        503,
    )


@app.get("/liveness")
def liveness():
    return {"status": "alive"}


@app.get("/readiness")
def readiness():
    with SessionLocal() as db:
        db.execute(text("SELECT 1"))
    return {"status": "ready"}


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return RedirectResponse("/dashboard" if request.cookies.get("session") else "/login")


@app.get("/legal/{page}", response_class=HTMLResponse)
def legal(request: Request, page: str):
    if page not in {"privacy", "terms", "sources"}:
        raise HTTPException(404, "Page not found")
    return templates.TemplateResponse(request, "legal.html", {"page": page, "config": settings()})


@app.get("/{page:path}", response_class=HTMLResponse)
def ui(request: Request, page: str):
    if page not in {
        "login",
        "onboarding",
        "dashboard",
        "opportunities",
        "company",
        "evidence",
        "watchlist",
        "notifications",
        "settings",
    } and not (page.startswith("opportunities/") and len(page.split("/")) == 2):
        raise HTTPException(404, "Page not found")
    return templates.TemplateResponse(request, "app.html", {"config": settings(), "page": page})
