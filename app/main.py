import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.database import Base, engine
from app.routers import (
    coverage,
    coverage_gaps,
    dashboard,
    external,
    github,
    inventory,
    ml,
    portfolio,
    rtm,
)

load_dotenv()

app = FastAPI(title="RTM & Test Quality Prediction API")

cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)


@app.get("/health")
@app.get("/api/health")
def health():
    """Readiness probe: 'ok' only when the Neon DB is actually reachable.

    Used by the gateway's /health/services aggregation, the Docker
    HEALTHCHECK, and the frontend Service Status page — so a green status
    means the service can really serve requests, not just that the process
    is up.
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "database": "up"}
    except Exception as exc:  # pragma: no cover - defensive
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "database": "down", "detail": str(exc)},
        )


app.include_router(rtm.router)
app.include_router(dashboard.router)
app.include_router(inventory.router)
app.include_router(portfolio.router)
app.include_router(coverage_gaps.router)
app.include_router(coverage.router)
app.include_router(github.router)
app.include_router(ml.router)
app.include_router(external.router)
app.include_router(external.component1_router)
