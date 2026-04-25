import logging
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.core.settings import settings
from app.db.database import Base, engine
from app.api.routers import admin, websocket, health

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize DB models
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Gemini Live Voice Bot")

# Mount static files
app.mount("/web", StaticFiles(directory="web"), name="web")

# Include routers
app.include_router(health.router)
app.include_router(admin.router)
app.include_router(websocket.router)

@app.get("/")
async def index() -> FileResponse:
    return FileResponse("web/index.html")

# Provide an easy way to run this directly for legacy reasons if needed
def run():
    import uvicorn
    uvicorn.run("app.server:app", host=settings.host, port=settings.port, reload=True)
