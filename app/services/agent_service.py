from typing import Dict, Any
from sqlalchemy.orm import Session
from app.repositories.agent_repository import AgentRepository
from app.schemas.agent import AgentConfigCreate

DEFAULT_AGENT = {
    "name": "Gemini Voice Assistant",
    "prompt": "You are a helpful real-time Bangla voice assistant. Keep replies concise and friendly. You can ask clarifying questions if the user's request is unclear. Always respond in Bangla. If you don't know something, say you don't know instead of making it up.",
    "voice": "Aoede"
}

class AgentService:
    def __init__(self, db: Session):
        self.repo = AgentRepository(db)

    def ensure_default_agent(self):
        agent = self.repo.get_by_id("default")
        if not agent:
            self.repo.create_or_update(
                "default",
                AgentConfigCreate(**DEFAULT_AGENT)
            )

    def get_all_agents(self) -> Dict[str, Any]:
        agents = self.repo.get_all()
        result = {}
        for agent in agents:
            result[agent.id] = {
                "name": agent.name,
                "prompt": agent.prompt,
                "voice": agent.voice
            }
        # Fallback
        if "default" not in result:
            result["default"] = DEFAULT_AGENT
        return result

    def get_agent(self, agent_id: str) -> Dict[str, str]:
        agent = self.repo.get_by_id(agent_id)
        if agent:
            return {
                "name": agent.name,
                "prompt": agent.prompt,
                "voice": agent.voice
            }
        # Fallback to default
        default = self.repo.get_by_id("default")
        if default:
            return {
                "name": default.name,
                "prompt": default.prompt,
                "voice": default.voice
            }
        return DEFAULT_AGENT

    def update_agent(self, agent_id: str, config: AgentConfigCreate) -> None:
        self.repo.create_or_update(agent_id, config)

    def delete_agent(self, agent_id: str) -> bool:
        if agent_id == "default":
            return False
        return self.repo.delete(agent_id)
