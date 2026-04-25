from sqlalchemy.orm import Session
from typing import List, Optional
from app.models.agent import AgentModel
from app.schemas.agent import AgentConfigCreate

class AgentRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_all(self) -> List[AgentModel]:
        return self.db.query(AgentModel).all()

    def get_by_id(self, agent_id: str) -> Optional[AgentModel]:
        return self.db.query(AgentModel).filter(AgentModel.id == agent_id).first()

    def create_or_update(self, agent_id: str, agent_in: AgentConfigCreate) -> AgentModel:
        agent = self.get_by_id(agent_id)
        if agent:
            agent.name = agent_in.name
            agent.prompt = agent_in.prompt
            agent.voice = agent_in.voice
        else:
            agent = AgentModel(
                id=agent_id,
                name=agent_in.name,
                prompt=agent_in.prompt,
                voice=agent_in.voice
            )
            self.db.add(agent)
        self.db.commit()
        self.db.refresh(agent)
        return agent

    def delete(self, agent_id: str) -> bool:
        agent = self.get_by_id(agent_id)
        if agent:
            self.db.delete(agent)
            self.db.commit()
            return True
        return False
