from sqlalchemy import Column, String
from app.db.database import Base

class AgentModel(Base):
    __tablename__ = "agents"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    prompt = Column(String, nullable=False)
    voice = Column(String, nullable=False)
