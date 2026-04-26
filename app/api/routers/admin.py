import secrets
from fastapi import APIRouter, Depends, HTTPException, status, Header
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.core.settings import settings
from app.schemas.agent import AgentConfigCreate
from app.services.agent_service import AgentService
from app.services.auth_service import AuthService
from app.core.security import pwd_context
from app.models.user import UserModel
from app.services.session_manager import session_manager
from app.models.call_record import CallRecordModel
from app.models.agent import AgentModel
from typing import Optional, List
import json
import asyncio
import os
import logging
from sse_starlette.sse import EventSourceResponse

logger = logging.getLogger(__name__)

router = APIRouter()

def get_current_user(
    authorization: Optional[str] = Header(None), 
    token: Optional[str] = None,
    db: Session = Depends(get_db)
):
    if not authorization and not token:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
    
    if not token:
        raise HTTPException(status_code=401, detail="Invalid token")
        
    auth_service = AuthService(db)
    payload = auth_service.decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return payload

from pydantic import BaseModel
from app.schemas.user import UserCreate, UserLogin

class RefreshRequest(BaseModel):
    refresh_token: str

@router.post("/api/register")
async def register(req: UserCreate, db: Session = Depends(get_db)):
    auth_service = AuthService(db)
    if auth_service.get_user_by_username(req.username):
        return JSONResponse({"ok": False, "message": "Username already exists"}, status_code=400)
    
    # Optional: check if email exists
    if req.email:
        existing_email = db.query(UserModel).filter(UserModel.email == req.email).first()
        if existing_email:
            return JSONResponse({"ok": False, "message": "Email already registered"}, status_code=400)

    user = auth_service.create_user(req)
    access_token = auth_service.create_access_token(user.username, user.role, user.id)
    refresh_token = auth_service.create_refresh_token(user.username, user.role, user.id)
    return JSONResponse({
        "ok": True, 
        "token": access_token, 
        "refresh_token": refresh_token,
        "role": user.role
    })

@router.post("/api/login")
async def login(req: UserLogin, db: Session = Depends(get_db)):
    auth_service = AuthService(db)
    user = auth_service.get_user_by_username(req.username)
    if user and pwd_context.verify(req.password, user.hashed_password):
        access_token = auth_service.create_access_token(user.username, user.role, user.id)
        refresh_token = auth_service.create_refresh_token(user.username, user.role, user.id)
        return JSONResponse({
            "ok": True, 
            "token": access_token, 
            "refresh_token": refresh_token,
            "role": user.role, 
            "full_name": user.full_name, 
            "username": user.username
        })
    return JSONResponse({"ok": False, "message": "Invalid credentials"}, status_code=401)

@router.post("/api/refresh")
async def refresh_token(req: RefreshRequest, db: Session = Depends(get_db)):
    auth_service = AuthService(db)
    payload = auth_service.decode_refresh_token(req.refresh_token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    
    # Optionally verify user still exists and hasn't been disabled
    user = auth_service.get_user_by_username(payload["sub"])
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
        
    access_token = auth_service.create_access_token(user.username, user.role, user.id)
    new_refresh_token = auth_service.create_refresh_token(user.username, user.role, user.id)
    
    return JSONResponse({
        "ok": True, 
        "token": access_token,
        "refresh_token": new_refresh_token
    })

@router.get("/api/me")
async def get_me(user_data: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    auth_service = AuthService(db)
    user = auth_service.get_user_by_username(user_data["sub"])
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"id": user.id, "username": user.username, "full_name": user.full_name, "role": user.role}

@router.get("/dashboard")
async def dashboard_page():
    return FileResponse("web/admin.html")

@router.get("/dashboard/api/agents")
async def get_admin_agents(user_data: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    service = AgentService(db)
    return JSONResponse(service.get_all_agents(user_data["user_id"], user_data["role"]))

@router.get("/api/agents")
async def get_public_agents(db: Session = Depends(get_db)):
    service = AgentService(db)
    agents = service.get_all_agents()
    # Strip prompts for public access if needed, or just return basic info
    # For now, return basic info for UI
    public_agents = {k: {"name": v["name"], "voice": v["voice"]} for k, v in agents.items()}
    return JSONResponse(public_agents)

@router.post("/dashboard/api/agents/{agent_id}")
async def update_agent(
    agent_id: str, 
    config: AgentConfigCreate, 
    user_data: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    service = AgentService(db)
    try:
        service.update_agent(agent_id, config, user_data["user_id"], user_data["role"])
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "message": str(e)}, status_code=403)

@router.delete("/dashboard/api/agents/{agent_id}")
async def delete_agent(
    agent_id: str, 
    user_data: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    service = AgentService(db)
    success = service.delete_agent(agent_id, user_data["user_id"], user_data["role"])
    if not success:
        return JSONResponse({"ok": False, "message": "Cannot delete default agent or agent not found"}, status_code=400)
    return JSONResponse({"ok": True})
@router.get("/dashboard/api/sessions")
async def get_active_sessions(user_data: dict = Depends(get_current_user)):
    return JSONResponse(session_manager.get_active_sessions_for_user(user_data["user_id"], user_data["role"]))

@router.get("/dashboard/api/sessions/sse")
async def active_sessions_sse(authorization: Optional[str] = Header(None), token: Optional[str] = None):
    # Manually decode token to avoid holding DB session
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
        
    if not token:
        raise HTTPException(status_code=401, detail="Invalid token")

    from app.services.auth_service import AuthService
    from app.db.database import SessionLocal
    
    db = SessionLocal()
    try:
        auth_service = AuthService(db)
        user_data = auth_service.decode_access_token(token)
        if not user_data:
            raise HTTPException(status_code=401, detail="Invalid token")
    finally:
        db.close() # Close DB session immediately after auth check

    async def event_generator():
        queue = asyncio.Queue()
        session_manager.subscribers.append(queue)
        try:
            # Send initial state
            sessions = session_manager.get_active_sessions_for_user(user_data["user_id"], user_data["role"])
            yield {"data": json.dumps(sessions)}
            
            while True:
                try:
                    # Wait for notification OR 1 minute timeout pulse
                    await asyncio.wait_for(queue.get(), timeout=60.0)
                except asyncio.TimeoutError:
                    # Periodic 1-minute update even if no changes
                    pass
                
                sessions = session_manager.get_active_sessions_for_user(user_data["user_id"], user_data["role"])
                yield {"data": json.dumps(sessions)}
        finally:
            session_manager.subscribers.remove(queue)

    return EventSourceResponse(event_generator())

@router.get("/dashboard/api/history")
async def get_call_history(limit: int = 10, offset: int = 0, user_data: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(CallRecordModel).join(AgentModel)
    
    if user_data["role"] != "super_admin":
        query = query.filter(AgentModel.owner_id == user_data["user_id"])
    
    total = query.count()
    records = query.order_by(CallRecordModel.start_time.desc()).offset(offset).limit(limit).all()
    
    # Setup GCS client for signed URLs
    storage_client = None
    try:
        from google.cloud import storage
        if os.path.exists(settings.gcs_service_account_path):
            storage_client = storage.Client.from_service_account_json(settings.gcs_service_account_path)
        else:
            storage_client = storage.Client()
    except Exception as e:
        logger.error(f"Failed to setup GCS client for signed URLs: {e}")

    result = []
    import datetime
    for r in records:
            audio_data = {}
            if r.audio_path:
                try:
                    if r.audio_path.startswith("{"):
                        audio_data = json.loads(r.audio_path)
                    elif r.audio_path.startswith("["):
                        audio_data = {"turns": json.loads(r.audio_path)}
                    else:
                        audio_data = {"merged": r.audio_path}
                except:
                    audio_data = {"merged": r.audio_path}
            
            # Generate Signed URLs
            proxy_data = {}
            prefix = f"https://storage.googleapis.com/{settings.gcs_bucket_name}/"
            
            if storage_client:
                bucket = storage_client.bucket(settings.gcs_bucket_name)
                
                # Sign merged URL
                merged_url = audio_data.get("merged")
                if merged_url and merged_url.startswith(prefix):
                    blob_path = merged_url[len(prefix):]
                    try:
                        proxy_data["merged"] = bucket.blob(blob_path).generate_signed_url(
                            version="v4",
                            expiration=datetime.timedelta(hours=2),
                            method="GET"
                        )
                    except Exception as sign_err:
                        logger.error(f"Failed to sign merged URL: {sign_err}")
                
                # Sign turns
                if audio_data.get("turns"):
                    proxy_turns = []
                    for t in audio_data["turns"]:
                        pt = {"turn": t.get("turn")}
                        # Sign user
                        u_url = t.get("user_url")
                        if u_url and u_url.startswith(prefix):
                            try:
                                pt["user_url"] = bucket.blob(u_url[len(prefix):]).generate_signed_url(
                                    version="v4", expiration=datetime.timedelta(hours=2), method="GET"
                                )
                            except: pass
                        # Sign bot
                        b_url = t.get("bot_url")
                        if b_url and b_url.startswith(prefix):
                            try:
                                pt["bot_url"] = bucket.blob(b_url[len(prefix):]).generate_signed_url(
                                    version="v4", expiration=datetime.timedelta(hours=2), method="GET"
                                )
                            except: pass
                        proxy_turns.append(pt)
                    proxy_data["turns"] = proxy_turns

            result.append({
                "id": r.id,
                "agent_id": r.agent_id,
                "agent_name": r.agent.name,
                "owner_name": r.agent.owner.full_name or r.agent.owner.username if r.agent.owner else "Unknown",
                "session_id": r.session_id,
                "start_time": r.start_time.isoformat() + "Z",
                "end_time": r.end_time.isoformat() + "Z" if r.end_time else None,
                "transcript": r.transcript,
                "audio_url": proxy_data if proxy_data else None,
                "duration": r.duration or "0:00"
            })
    
    return JSONResponse({
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": result
    })


