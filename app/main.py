from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import engine, get_db, Base
from typing import Union, List
from pydantic import BaseModel
from datetime import datetime
from app.models import Memory, Task
from app.schemas import (
    MemoryCreate, MemoryResponse,
    QueryRequest,
)
from app.memory.store import (
    create_memory,
    retrieve_relevant_memories,
    get_all_memories,
    delete_memory_by_id
)
from app.llm.agent import generate_daily_plan, query_with_memory

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Cognitive Memory and Workflow Assistant",
    description="AI-powered second brain with task management",
    version="1.0.0"
)

# ─── HEALTH ───────────────────────────────────────────────

@app.get("/")
def health_check():
    return {
        "status": "ok",
        "message": "Cognitive Memory and Workflow Assistant API",
        "version": "1.0.0"
    }

# ─── SESSION COMPATIBILITY ROUTES ─────────────────────────

@app.get("/memory/{session_id}")
def get_session_memory(session_id: str, db: Session = Depends(get_db)):
    memories = get_all_memories(db)
    return [
        {
            "role": "user" if i % 2 == 0 else "assistant",
            "content": mem.content
        }
        for i, mem in enumerate(memories)
    ]

@app.delete("/memory/{session_id}")
def clear_session_memory(session_id: str, db: Session = Depends(get_db)):
    db.query(Memory).delete()
    db.commit()
    return {"status": "cleared", "session_id": session_id}

# ─── MEMORY ROUTES ────────────────────────────────────────

@app.post("/memory", response_model=MemoryResponse)
def add_memory(data: MemoryCreate, db: Session = Depends(get_db)):
    return create_memory(db, data)

@app.get("/memory", response_model=list[MemoryResponse])
def list_memories(db: Session = Depends(get_db)):
    return get_all_memories(db)

@app.post("/memory/search", response_model=list[MemoryResponse])
def search_memories(request: QueryRequest, db: Session = Depends(get_db)):
    return retrieve_relevant_memories(db, request.query, top_k=request.top_k)

@app.delete("/memory/{memory_id}")
def delete_memory(memory_id: int, db: Session = Depends(get_db)):
    return delete_memory_by_id(db, memory_id)

# ─── LLM AGENT ROUTES ─────────────────────────────────────

@app.get("/plan")
def get_daily_plan(db: Session = Depends(get_db)):
    plan = generate_daily_plan(db)
    return {"plan": plan}

@app.post("/query")
def query_assistant(request: QueryRequest, db: Session = Depends(get_db)):
    response = query_with_memory(db, request.query)
    return {"response": response}

# ─── CHAT ROUTE ───────────────────────────────────────────

class ChatRequest(BaseModel):
    message: Union[str, None] = None
    query: Union[str, None] = None
    session_id: str = "default"
    model_config = {"extra": "allow"}

@app.post("/chat")
def chat_endpoint(request: ChatRequest, db: Session = Depends(get_db)):
    try:
        user_input = request.query or request.message
        if not user_input:
            raise HTTPException(
                status_code=400,
                detail="Either 'message' or 'query' field must be provided"
            )
        response = query_with_memory(db, user_input)
        return {"response": response}
    except Exception as e:
        print(f"Chat endpoint error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ─── PROFILE ROUTE ────────────────────────────────────────

class UserProfile(BaseModel):
    name: str
    timezone: str
    work_start: str
    work_end: str
    peak_hours: List[int]
    low_hours: List[int]
    focus_duration: int
    break_duration: int
    priorities: List[str]

@app.post("/profile")
def save_profile(profile: UserProfile, db: Session = Depends(get_db)):
    try:
        from app.memory.store import store_memory
        profile_text = f"""
User Profile:
- Name: {profile.name}
- Timezone: {profile.timezone}
- Work Hours: {profile.work_start} - {profile.work_end}
- Peak Energy: {', '.join([f'{h:02d}:00' for h in profile.peak_hours])}
- Low Energy: {', '.join([f'{h:02d}:00' for h in profile.low_hours])}
- Focus Duration: {profile.focus_duration} minutes
- Break Duration: {profile.break_duration} minutes
- Priorities: {', '.join(profile.priorities)}
"""
        store_memory(
            db=db,
            content=profile_text,
            category="profile",
            metadata={"type": "user_preferences"}
        )
        return {"status": "success", "message": "Profile saved"}
    except Exception as e:
        print(f"Profile save error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ─── TASK SCHEMA ──────────────────────────────────────────

class TaskCreateRequest(BaseModel):
    title: str
    priority: str = "Medium"
    category: str = "Other"
    due_date: str
    estimated_minutes: int = 60
    notes: str = ""
    status: str = "pending"

# ─── TASK ROUTES ──────────────────────────────────────────

@app.post("/tasks")
def create_new_task(task: TaskCreateRequest, db: Session = Depends(get_db)):
    try:
        db_task = Task(
            title=task.title,
            priority=task.priority,
            category=task.category,
            due_date=datetime.fromisoformat(task.due_date),
            estimated_minutes=task.estimated_minutes,
            notes=task.notes,
            status=task.status
        )
        db.add(db_task)
        db.commit()
        db.refresh(db_task)
        return {"status": "success", "id": db_task.id}
    except Exception as e:
        print(f"Task creation error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tasks")
def get_all_tasks(db: Session = Depends(get_db)):
    try:
        tasks = db.query(Task).order_by(Task.due_date).all()
        return [
            {
                "id": t.id,
                "title": t.title,
                "priority": t.priority,
                "category": t.category,
                "due_date": t.due_date.isoformat() if t.due_date else None,
                "estimated_minutes": t.estimated_minutes,
                "notes": t.notes,
                "status": t.status
            }
            for t in tasks
        ]
    except Exception as e:
        print(f"Task retrieval error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.patch("/tasks/{task_id}/complete")
def complete_task(task_id: int, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task.status = "completed"
    db.commit()
    return {"status": "success"}

@app.delete("/tasks/{task_id}")
def remove_task_by_id(task_id: int, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    db.delete(task)
    db.commit()
    return {"status": "success"}
