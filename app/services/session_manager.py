from typing import Dict, List, Any
import logging
import asyncio
from fastapi import WebSocket

logger = logging.getLogger(__name__)

class SessionManager:
    def __init__(self):
        # session_id -> { "monitors": [monitor_websockets], "agent_id": agent_id, "user_id": user_id_of_participant }
        self.active_sessions: Dict[str, Dict[str, Any]] = {}
        self.subscribers: List[asyncio.Queue] = []

    def notify_subscribers(self):
        for queue in self.subscribers:
            queue.put_nowait(True)

    def register_session(self, session_id: str, agent_id: str, agent_name: str, owner_id: str):
        self.active_sessions[session_id] = {
            "monitors": [],
            "agent_id": agent_id,
            "agent_name": agent_name,
            "owner_id": owner_id
        }
        logger.info(f"Registered session {session_id} for agent {agent_name} (owner: {owner_id})")
        self.notify_subscribers()

    def unregister_session(self, session_id: str):
        if session_id in self.active_sessions:
            del self.active_sessions[session_id]
            logger.info(f"Unregistered session {session_id}")
            self.notify_subscribers()

    async def add_monitor(self, session_id: str, monitor_websocket: WebSocket):
        if session_id in self.active_sessions:
            self.active_sessions[session_id]["monitors"].append(monitor_websocket)
            logger.info(f"Added monitor to session {session_id}")
            return True
        return False

    async def remove_monitor(self, session_id: str, monitor_websocket: WebSocket):
        if session_id in self.active_sessions:
            if monitor_websocket in self.active_sessions[session_id]["monitors"]:
                self.active_sessions[session_id]["monitors"].remove(monitor_websocket)
                logger.info(f"Removed monitor from session {session_id}")

    async def broadcast_to_monitors(self, session_id: str, message: Any):
        if session_id in self.active_sessions:
            monitors = list(self.active_sessions[session_id]["monitors"]) # Copy to avoid concurrent modification issues
            for monitor in monitors:
                try:
                    await monitor.send_json(message)
                except Exception as e:
                    logger.warning(f"Failed to send message to monitor in session {session_id}: {e}")
                    # Monitor might have disconnected, but we handle that in the monitor loop usually

    def get_active_sessions_for_user(self, user_id: str, role: str) -> List[Dict[str, Any]]:
        sessions = []
        for session_id, info in self.active_sessions.items():
            if role == "super_admin" or info["owner_id"] == user_id:
                sessions.append({
                    "session_id": session_id,
                    "agent_id": info["agent_id"],
                    "agent_name": info["agent_name"],
                    "monitor_count": len(info["monitors"])
                })
        return sessions

session_manager = SessionManager()
