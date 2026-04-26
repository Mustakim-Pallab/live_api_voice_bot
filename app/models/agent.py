from sqlalchemy import Column, String, ForeignKey
from sqlalchemy.orm import relationship
from app.db.database import Base

class AgentModel(Base):
    __tablename__ = "agents"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    prompt = Column(String, nullable=False)
    voice = Column(String, nullable=False)
    owner_id = Column(String, ForeignKey("users.id"), nullable=True)

    owner = relationship("UserModel")
