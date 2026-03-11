from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import engine, get_db, Base
from app.models import Memory, Task
from app.schemas import (
    MemoryCreate, MemoryResponse,
    TaskCreate, TaskResponse,
    QueryRequest, PlanRequest
)
from app.memory.store import (
    create_memory, 
    retrieve_relevant_memories, 
    get_all_memories,
    delete_memory_by_id  # NEW: Import delete function
)
from app.workflow.classifier import create_task, get_prioritized_tasks, delete_task
from app.llm.agent import generate_daily_plan, query_with_memory
from typing import Optional

# Create all tables on startup
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Cognitive Memory and Workflow Assistant",
    description="AI-powered second brain with task management",
    version="1.0.0"
)

# ─── MEMORY ROUTES ────────────────────────────────────────

@app.post("/memory", response_model=MemoryResponse)
def add_memory(data: MemoryCreate, db: Session = Depends(get_db)):
    """Store a new memory (idea, task, preference, goal)."""
    return create_memory(db, data)

@app.get("/memory", response_model=list[MemoryResponse])
def list_memories(db: Session = Depends(get_db)):
    """List all memories sorted by importance score."""
    return get_all_memories(db)

@app.post("/memory/search", response_model=list[MemoryResponse])
def search_memories(request: QueryRequest, db: Session = Depends(get_db)):
    """Semantic search over memories using FAISS + embeddings."""
    return retrieve_relevant_memories(db, request.query, top_k=request.top_k)

@app.delete("/memory/{memory_id}")
def delete_memory(memory_id: int, db: Session = Depends(get_db)):
    """Delete a specific memory by ID and rebuild FAISS index."""
    return delete_memory_by_id(db, memory_id)

# ─── TASK ROUTES ──────────────────────────────────────────

@app.post("/task", response_model=TaskResponse)
def add_task(data: TaskCreate, db: Session = Depends(get_db)):
    """Add a task. Auto-classifies into Eisenhower quadrant."""
    return create_task(db, data)

@app.get("/tasks")
def list_tasks(db: Session = Depends(get_db)):
    """Get all tasks grouped by Eisenhower quadrant."""
    grouped = get_prioritized_tasks(db)
    return {
        quadrant: [
            {
                "id": t.id,
                "title": t.title,
                "urgency": t.urgency,
                "importance": t.importance,
                "status": t.status,
                "deadline": str(t.deadline) if t.deadline else None
            }
            for t in tasks
        ]
        for quadrant, tasks in grouped.items()
    }

@app.patch("/task/{task_id}/status")
def update_task_status(task_id: int, status: str, db: Session = Depends(get_db)):
    """Update task status: pending | in_progress | done"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task.status = status
    db.commit()
    return {"message": f"Task {task_id} updated to {status}"}

@app.delete("/task/{task_id}")
def remove_task(task_id: int, db: Session = Depends(get_db)):
    """Delete a task permanently by ID."""
    success = delete_task(db, task_id)
    if not success:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"message": f"Task {task_id} deleted successfully"}
# ─── LLM AGENT ROUTES ─────────────────────────────────────

@app.get("/plan")
def get_daily_plan(db: Session = Depends(get_db)):
    """Generate an AI daily plan based on current tasks and memories."""
    plan = generate_daily_plan(db)
    return {"plan": plan}

@app.post("/query")
def query_assistant(request: QueryRequest, db: Session = Depends(get_db)):
    """Query the assistant. It retrieves relevant memories and responds."""
    response = query_with_memory(db, request.query)
    return {"response": response}
