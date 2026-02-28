from fastapi import APIRouter
from pydantic import BaseModel

from src.core.config import settings

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    env: str
    model: str
    version: str


@router.get("", response_model=HealthResponse)
async def health_check():
    return HealthResponse(
        status="ok",
        env=settings.app_env,
        model=settings.agent_model,
        version=settings.pipeline_version,
    )
