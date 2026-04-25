from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.services.agent_service import AgentService
from app.services.live_voice import LiveVoiceBridge
from app.core.settings import settings
import logging

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

    bridge = LiveVoiceBridge(
        websocket=websocket, 
        api_key=settings.gemini_api_key, 
        model=settings.gemini_model,
        prompt=agent_config["prompt"],
        voice=agent_config["voice"]
    )
    
    try:
        await bridge.run()
    except WebSocketDisconnect:
        logger.info("Browser disconnected")
    except Exception as e:
        logger.error(f"Live session failed: {e}", exc_info=True)
