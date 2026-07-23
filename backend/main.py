"""
CodeMind — FastAPI Application Entry Point
==========================================
This is the top-level app factory. It wires together:
  - All API routers
  - CORS middleware
  - App lifespan (startup / shutdown events)
  - Global exception handlers
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.api.routes import health, repo, bundle, chat, mcp


# ── Lifespan ─────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Runs on startup (before yield) and shutdown (after yield).
    Use this to initialise resources: DB pools, warm-up caches, etc.
    """
    # Startup
    print(f"[*] CodeMind backend starting — env={settings.APP_ENV}")
    _ensure_directories()
    yield
    # Shutdown
    print("CodeMind backend shutting down.")


def _ensure_directories() -> None:
    """Create required directories if they don't already exist."""
    import os
    os.makedirs(settings.OKF_BUNDLES_DIR, exist_ok=True)
    os.makedirs(settings.REPOS_CLONE_DIR, exist_ok=True)
    print(f"OKF bundles dir  : {settings.OKF_BUNDLES_DIR}")
    print(f"Repos clone dir  : {settings.REPOS_CLONE_DIR}")


# ── App Factory ───────────────────────────────────────────────────────────────
def create_app() -> FastAPI:
    app = FastAPI(
        title="CodeMind — OKF Codebase Assistant",
        description=(
            "An AI-powered developer assistant that crawls any GitHub repository, "
            "builds an OKF (Open Knowledge Format) knowledge bundle, and answers "
            "questions about the codebase with source-backed precision."
        ),
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # ── CORS ─────────────────────────────────────────────────────────────────
    # In development: allow any origin so the frontend (Streamlit / React) can
    # connect freely. Tighten this in production.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.APP_ENV == "development" else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Routers ──────────────────────────────────────────────────────────────
    app.include_router(health.router, tags=["Health"])
    app.include_router(repo.router,   prefix="/repo",   tags=["Repository"])
    app.include_router(bundle.router, prefix="/bundle", tags=["OKF Bundle"])
    app.include_router(chat.router,   prefix="/chat",   tags=["Agent / Chat"])
    app.include_router(mcp.router,    prefix="/mcp",    tags=["Model Context Protocol (MCP)"])

    # ── Global Exception Handler ──────────────────────────────────────────────
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_server_error",
                "message": str(exc),
                "path": str(request.url),
            },
        )

    return app


# ── Entrypoint ────────────────────────────────────────────────────────────────
app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.APP_ENV == "development",
        log_level=settings.LOG_LEVEL.lower(),
    )
