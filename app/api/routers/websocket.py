from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.services.agent_service import AgentService
from app.services.live_voice import LiveVoiceBridge
from app.core.settings import settings
from app.services.session_manager import session_manager
import logging
import uuid

logger = logging.getLogger(__name__)

router = APIRouter()

@router.websocket("/ws/live/{agent_id}")
async def ws_live(websocket: WebSocket, agent_id: str = "default", db: Session = Depends(get_db)) -> None:
    await websocket.accept()
    
    if not settings.gemini_api_key:
        await websocket.send_json(
            {"type": "error", "message": "GEMINI_API_KEY is not set on server."}
        )
        await websocket.close()
        return

    service = AgentService(db)
    agent_config = service.get_agent(agent_id)
    
    session_id = str(uuid.uuid4())
    session_manager.register_session(
        session_id, 
        agent_id, 
        agent_config.get("name", "Unknown Agent"), 
        agent_config.get("owner_id")
    )

    bridge = LiveVoiceBridge(
        websocket=websocket, 
        api_key=settings.gemini_api_key, 
        model=settings.gemini_model,
        prompt=agent_config["prompt"],
        voice=agent_config["voice"],
        session_id=session_id,
        agent_id=agent_id
    )
    
    try:
        await bridge.run()
    except WebSocketDisconnect:
        logger.info(f"Browser disconnected from session {session_id}")
    except Exception as e:
        logger.error(f"Live session failed for {session_id}: {e}", exc_info=True)
    finally:
        session_manager.unregister_session(session_id)

@router.websocket("/ws/monitor/{session_id}")
async def ws_monitor(websocket: WebSocket, session_id: str, db: Session = Depends(get_db)) -> None:
    # Authorization will be handled by checking the token in the frontend and passing it as a query param or header
    # For now, let's accept and then check. 
    # WebSocket doesn't support headers well in all browsers, so query param is common.
    await websocket.accept()
    
    # We should verify if the user is authorized to monitor this session
    # (admin or owner of the agent)
    # This requires token verification.
    
    success = await session_manager.add_monitor(session_id, websocket)
    if not success:
        await websocket.send_json({"type": "error", "message": "Session not found"})
        await websocket.close()
        return

    try:
        # Keep the connection open and wait for messages from the monitor if any (though usually it's read-only)
        while True:
            data = await websocket.receive_text()
            # Handle potential monitor commands here
    except WebSocketDisconnect:
        logger.info(f"Monitor disconnected from session {session_id}")
    finally:
        await session_manager.remove_monitor(session_id, websocket)
