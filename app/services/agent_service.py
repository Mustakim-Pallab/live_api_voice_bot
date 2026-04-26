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

    def get_all_agents(self, user_id: str = None, role: str = None) -> Dict[str, Any]:
        if role == "super_admin":
            agents = self.repo.get_all()
        elif user_id:
            agents = self.repo.get_all(owner_id=user_id)
        else:
            # Public access - return all agents but stripping sensitive data (handled in router)
            agents = self.repo.get_all()
            
        result = {}
        for agent in agents:
            agent_data = {
                "name": agent.name,
                "prompt": agent.prompt,
                "voice": agent.voice,
                "owner_id": agent.owner_id,
                "is_mine": agent.owner_id == user_id if user_id else False
            }
            # Include owner info for super_admin
            if role == "super_admin" and agent.owner:
                agent_data["owner_name"] = agent.owner.full_name or agent.owner.username
                agent_data["owner_email"] = agent.owner.email
                
            result[agent.id] = agent_data
            
        # Only ensure the default agent is visible to super_admin
        if role == "super_admin":
            if "default" not in result:
                default_agent = self.repo.get_by_id("default")
                if default_agent:
                    result["default"] = {
                        "name": default_agent.name,
                        "prompt": default_agent.prompt,
                        "voice": default_agent.voice
                    }
                else:
                    result["default"] = DEFAULT_AGENT
                
        return result

    def get_agent(self, agent_id: str) -> Dict[str, str]:
        agent = self.repo.get_by_id(agent_id)
        if agent:
            return {
                "name": agent.name,
                "prompt": agent.prompt,
                "voice": agent.voice,
                "owner_id": agent.owner_id
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

    def update_agent(self, agent_id: str, config: AgentConfigCreate, user_id: str, role: str) -> None:
        if role != "super_admin":
            existing = self.repo.get_by_id(agent_id)
            if existing and existing.owner_id != user_id:
                raise Exception("Not authorized to edit this agent")
        
        self.repo.create_or_update(agent_id, config, owner_id=user_id)

    def delete_agent(self, agent_id: str, user_id: str, role: str) -> bool:
        if agent_id == "default":
            return False
            
        if role != "super_admin":
            existing = self.repo.get_by_id(agent_id)
            if not existing or existing.owner_id != user_id:
                return False
                
        return self.repo.delete(agent_id)
