from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from src.app.routes import generate_report, health
from src.core.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"MedReport AI starting — env={settings.app_env}, model={settings.agent_model}")
    yield
    logger.info("MedReport AI shutting down")


app = FastAPI(
    title="MedReport AI",
    description="Agentic AI pipeline for automated medical report generation",
    version=settings.pipeline_version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/health", tags=["health"])
app.include_router(generate_report.router, prefix="/report", tags=["report"])


@app.get("/")
async def root():
    return {
        "name": "MedReport AI",
        "version": settings.pipeline_version,
        "docs": "/docs",
        "health": "/health",
    }
