from fastapi import APIRouter
from fastapi.responses import JSONResponse
from app.core.settings import settings

router = APIRouter()

@router.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"ok": True, "model": settings.gemini_model})
