import secrets
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.core.settings import settings
from app.schemas.agent import AgentConfigCreate
from app.services.agent_service import AgentService

router = APIRouter()
security = HTTPBasic()

def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    is_user_ok = secrets.compare_digest(credentials.username, settings.admin_username)
    is_pass_ok = secrets.compare_digest(credentials.password, settings.admin_password)
    if not (is_user_ok and is_pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

from pydantic import BaseModel

class LoginRequest(BaseModel):
    username: str
    password: str

@router.post("/api/login")
async def login(req: LoginRequest):
    is_user_ok = secrets.compare_digest(req.username, settings.admin_username)
    is_pass_ok = secrets.compare_digest(req.password, settings.admin_password)
    if is_user_ok and is_pass_ok:
        return JSONResponse({"ok": True})
    return JSONResponse({"ok": False}, status_code=401)

@router.get("/admin")
async def admin_page():
    return FileResponse("web/admin.html")

@router.get("/admin/api/agents")
async def get_admin_agents(username: str = Depends(verify_admin), db: Session = Depends(get_db)):
    service = AgentService(db)
    return JSONResponse(service.get_all_agents())

@router.get("/api/agents")
async def get_public_agents(db: Session = Depends(get_db)):
    service = AgentService(db)
    agents = service.get_all_agents()
    # Strip prompts for public access if needed, or just return basic info
    # For now, return basic info for UI
    public_agents = {k: {"name": v["name"], "voice": v["voice"]} for k, v in agents.items()}
    return JSONResponse(public_agents)

@router.post("/admin/api/agents/{agent_id}")
async def update_agent(
    agent_id: str, 
    config: AgentConfigCreate, 
    username: str = Depends(verify_admin),
    db: Session = Depends(get_db)
):
    service = AgentService(db)
    service.update_agent(agent_id, config)
    return JSONResponse({"ok": True})

@router.delete("/admin/api/agents/{agent_id}")
async def delete_agent(
    agent_id: str, 
    username: str = Depends(verify_admin),
    db: Session = Depends(get_db)
):
    service = AgentService(db)
    success = service.delete_agent(agent_id)
    if not success:
        return JSONResponse({"ok": False, "message": "Cannot delete default agent or agent not found"}, status_code=400)
    return JSONResponse({"ok": True})
