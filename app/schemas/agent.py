from pydantic import BaseModel

class AgentConfigBase(BaseModel):
    name: str
    prompt: str
    voice: str

class AgentConfigCreate(AgentConfigBase):
    pass

class AgentConfigResponse(AgentConfigBase):
    id: str

    class Config:
        from_attributes = True
