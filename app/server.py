import logging
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.core.settings import settings
from app.db.database import Base, engine, SessionLocal
from app.models.agent import AgentModel
from app.models.user import UserModel
from app.models.call_record import CallRecordModel
from app.api.routers import admin, websocket, health
from app.core.security import pwd_context
import uuid

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize DB models
Base.metadata.create_all(bind=engine)

def seed_super_admin():
    db = SessionLocal()
    try:
        super_admin = db.query(UserModel).filter(UserModel.username == settings.admin_username).first()
        if not super_admin:
            hashed = pwd_context.hash(settings.admin_password)
            new_admin = UserModel(
                id=str(uuid.uuid4()),
                username=settings.admin_username,
                hashed_password=hashed,
                role="super_admin"
            )
            db.add(new_admin)
            db.commit()
    finally:
        db.close()

seed_super_admin()

app = FastAPI(title="Gemini Live Voice Bot")

# Mount static files
import os
os.makedirs("recordings", exist_ok=True)

app.mount("/web", StaticFiles(directory="web"), name="web")
app.mount("/recordings", StaticFiles(directory="recordings"), name="recordings")

# Include routers
app.include_router(health.router)
app.include_router(admin.router)
app.include_router(websocket.router)

@app.get("/")
async def index() -> FileResponse:
    return FileResponse("web/index.html")

@app.get("/monitor.html")
async def monitor() -> FileResponse:
    return FileResponse("web/monitor.html")

# Provide an easy way to run this directly for legacy reasons if needed
def run():
    import uvicorn
    uvicorn.run("app.server:app", host=settings.host, port=settings.port, reload=True)
