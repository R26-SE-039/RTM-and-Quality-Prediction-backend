import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import models
from app.database import Base, SessionLocal, engine
from app.ml.predict import get_model_info
from app.routers import coverage, coverage_gaps, dashboard, external, gaps, github, ml, portfolio, project, quality, rtm

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

    info = get_model_info()
    db = SessionLocal()
    try:
        detail = (
            f"RandomForest, MAE {info['mae']:.2f}, R^2 {info['r2']:.3f}"
            if info.get("trained")
            else "No trained model found — using weighted-formula fallback"
        )
        db.add(
            models.ActivityLog(
                activity_type=models.ActivityType.MODEL_LOADED,
                title="ML model loaded",
                detail=detail,
            )
        )
        db.commit()
    finally:
        db.close()


@app.get("/api/health")
def health():
    return {"status": "ok"}


app.include_router(gaps.router)
app.include_router(coverage_gaps.router)
app.include_router(rtm.router)
app.include_router(quality.router)
app.include_router(portfolio.router)
app.include_router(project.router)
app.include_router(dashboard.router)
app.include_router(coverage.router)
app.include_router(github.router)
app.include_router(ml.router)
app.include_router(external.router)
app.include_router(external.component1_router)
