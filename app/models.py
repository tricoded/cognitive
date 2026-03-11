from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Enum
from sqlalchemy.sql import func
from app.database import Base
import enum

class TaskStatus(str, enum.Enum):
    pending = "pending"
    in_progress = "in_progress"
    done = "done"

class QuadrantEnum(str, enum.Enum):
    do_now = "do_now"           # urgent + important
    schedule = "schedule"       # not urgent + important
    delegate = "delegate"       # urgent + not important
    eliminate = "eliminate"     # not urgent + not important

class Memory(Base):
    __tablename__ = "memories"

    id = Column(Integer, primary_key=True, index=True)
    content = Column(Text, nullable=False)
    category = Column(String(50))          # task | idea | preference | goal
    importance_score = Column(Float, default=0.5)
    access_count = Column(Integer, default=0)
    embedding_index = Column(Integer)      # index in FAISS
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text)
    urgency = Column(Float, default=0.5)       # 0.0 to 1.0
    importance = Column(Float, default=0.5)    # 0.0 to 1.0
    quadrant = Column(String(50))              # eisenhower quadrant
    status = Column(String(50), default="pending")
    deadline = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
