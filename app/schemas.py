from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

# Memory schemas
class MemoryCreate(BaseModel):
    content: str
    category: str = "general"  
    
class MemoryResponse(BaseModel):
    id: int
    content: str
    category: str
    importance_score: float
    access_count: int
    created_at: datetime

    class Config:
        from_attributes = True

# Task schemas
class TaskCreate(BaseModel):
    description: Optional[str] = None
    urgency: float = Field(default=0.5, ge=0.0, le=1.0)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    deadline: Optional[datetime] = None

class TaskResponse(BaseModel):
    id: int
    title: str
    description: Optional[str]
    urgency: float
    importance: float
    quadrant: Optional[str]
    status: str
    deadline: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True

class QueryRequest(BaseModel):
    query: str
    top_k: int = 5

class PlanRequest(BaseModel):
    context: Optional[str] = None
