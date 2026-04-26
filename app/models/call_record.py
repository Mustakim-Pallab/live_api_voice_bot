from sqlalchemy import Column, String, ForeignKey, DateTime, Text
from sqlalchemy.orm import relationship
from app.db.database import Base
import datetime

class CallRecordModel(Base):
    __tablename__ = "call_records"

    id = Column(String, primary_key=True, index=True)
    agent_id = Column(String, ForeignKey("agents.id"), nullable=False)
    session_id = Column(String, nullable=False, unique=True)
    user_id = Column(String, nullable=True) # The participant (if known)
    start_time = Column(DateTime, default=datetime.datetime.utcnow)
    end_time = Column(DateTime, nullable=True)
    transcript = Column(Text, nullable=True) # JSON string of parts
    audio_path = Column(String, nullable=True)
    duration = Column(String, nullable=True) # Duration in seconds

    agent = relationship("AgentModel")
