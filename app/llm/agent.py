# app/llm/task_agent.py
# Task-aware AI agent — the brain behind the chat interface

import httpx
import os
import re
import json
import logging
from datetime import datetime, date, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from app.models import Task
from app.ml.task_predictor import TaskDifficultyPredictor

logger = logging.getLogger(__name__)

# ── Ollama Config (inherits from main.py env vars) ────────────────────────────
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "localhost")
OLLAMA_PORT = os.getenv("OLLAMA_PORT", "11434")
OLLAMA_BASE_URL = (
    OLLAMA_HOST if OLLAMA_HOST.startswith("http")
    else f"http://{OLLAMA_HOST}:{OLLAMA_PORT}"
)
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral")

# ── Singleton predictor reference ─────────────────────────────────────────────
predictor = TaskDifficultyPredictor()


# ══════════════════════════════════════════════════════════════════════════════
#  INTENT DETECTION
# ══════════════════════════════════════════════════════════════════════════════

INTENT_PATTERNS = {
    "create_task": [
        r"\b(add|create|make|new|set up|schedule)\b.*\btask\b",
        r"\btask\b.*\b(add|create|make|new)\b",
        r"\bremind me to\b",
        r"\bi need to\b",
        r"\bput\b.*\bon my list\b",
    ],
    "list_tasks": [
        r"\b(show|list|what|display|give me|get)\b.*\btasks?\b",
        r"\btasks?\b.*\b(do i have|pending|remaining|left|today|week)\b",
        r"\bwhat.*(do i have|should i do|am i working on)\b",
        r"\bmy (todo|to-do|task list|workload)\b",
    ],
    "complete_task": [
        r"\b(done|finished|completed|finish|complete|mark.*done)\b.*\btask\b",
        r"\btask\b.*\b(done|finished|completed)\b",
        r"\bi (finished|completed|did|done)\b",
    ],
    "task_analytics": [
        r"\b(how|what).*(productive|productivity|performing|accuracy|doing)\b",
        r"\b(stats|statistics|analytics|report|insights?|trends?)\b",
        r"\bhow (am i|have i been)\b",
        r"\bmy (performance|progress|week|month)\b",
    ],
    "task_predict": [
        r"\bhow long\b",
        r"\b(estimate|predict|guess)\b.*\btask\b",
        r"\bwill.*take\b",
    ],
    "get_plan": [
        r"\b(plan|schedule|organize|prioritize)\b.*\b(my day|today|tasks?)\b",
        r"\bwhat should i (do|work on|tackle|start)\b",
        r"\b(best order|optimal|most important)\b",
    ],
    "general_chat": [],  # fallback
}


def detect_intent(message: str) -> str:
    """Detect what the user wants to do."""
    msg_lower = message.lower()
    for intent, patterns in INTENT_PATTERNS.items():
        if intent == "general_chat":
            continue
        for pattern in patterns:
            if re.search(pattern, msg_lower):
                return intent
    return "general_chat"


# ══════════════════════════════════════════════════════════════════════════════
#  CONTEXT BUILDERS
# ══════════════════════════════════════════════════════════════════════════════

def build_task_context(db: Session) -> str:
    """Build a rich context string from live DB data."""
    try:
        # Pending + in-progress tasks
        pending = db.query(Task).filter(
            Task.status.in_(["pending", "in_progress"])
        ).order_by(Task.due_date).limit(20).all()

        # Completed tasks (recent 5)
        completed = db.query(Task).filter(
            Task.status == "completed"
        ).order_by(Task.completed_at.desc()).limit(5).all()

        # Stats
        total      = db.query(Task).count()
        done_count = db.query(Task).filter(Task.status == "completed").count()

        today = date.today()
        overdue = [
            t for t in pending
            if t.due_date and t.due_date.date() < today
        ]
        due_today = [
            t for t in pending
            if t.due_date and t.due_date.date() == today
        ]
        due_week = [
            t for t in pending
            if t.due_date and today < t.due_date.date() <= today + timedelta(days=7)
        ]

        lines = [
            f"=== LIVE TASK DATABASE (as of {datetime.now().strftime('%Y-%m-%d %H:%M')}) ===",
            f"Total tasks: {total} | Completed: {done_count} | Pending/Active: {len(pending)}",
            f"Overdue: {len(overdue)} | Due today: {len(due_today)} | Due this week: {len(due_week)}",
            "",
        ]

        if overdue:
            lines.append("🔴 OVERDUE TASKS:")
            for t in overdue:
                lines.append(f"  - [ID:{t.id}] {t.title} ({t.priority}, due {t.due_date.date()})")

        if due_today:
            lines.append("🟡 DUE TODAY:")
            for t in due_today:
                lines.append(f"  - [ID:{t.id}] {t.title} ({t.priority}, ~{t.estimated_minutes}min)")

        if due_week:
            lines.append("📅 DUE THIS WEEK:")
            for t in due_week:
                lines.append(f"  - [ID:{t.id}] {t.title} ({t.priority}, due {t.due_date.date()})")

        no_date = [t for t in pending if not t.due_date]
        if no_date:
            lines.append("📋 OTHER PENDING TASKS:")
            for t in no_date[:8]:
                lines.append(f"  - [ID:{t.id}] {t.title} ({t.priority}, {t.category}, ~{t.estimated_minutes}min)")

        if completed:
            lines.append("")
            lines.append("✅ RECENTLY COMPLETED:")
            for t in completed:
                acc = ""
                if t.estimated_minutes and t.actual_minutes:
                    diff = t.actual_minutes - t.estimated_minutes
                    acc = f" | actual: {t.actual_minutes}min ({'+' if diff>=0 else ''}{diff}min vs estimate)"
                lines.append(f"  - {t.title}{acc}")

        # ML status
        if predictor.is_trained:
            lines.append("")
            lines.append("🤖 ML MODEL: Trained and active (random_forest, MAE ~10.8min)")

        return "\n".join(lines)

    except Exception as e:
        logger.warning(f"Context build failed: {e}")
        return "Task context unavailable."


# ══════════════════════════════════════════════════════════════════════════════
#  ACTION EXECUTOR
# ══════════════════════════════════════════════════════════════════════════════

def extract_task_from_message(message: str) -> dict:
    """
    Attempt to parse task details from natural language.
    e.g. "add a high priority task to fix the login bug, estimate 2 hours"
    """
    msg_lower = message.lower()

    # Priority detection
    priority = "Medium"
    if any(w in msg_lower for w in ["critical", "urgent", "asap", "immediately"]):
        priority = "Critical"
    elif any(w in msg_lower for w in ["high", "important"]):
        priority = "High"
    elif any(w in msg_lower for w in ["low", "someday", "eventually", "later"]):
        priority = "Low"

    # Category detection
    category = "Work"
    cat_map = {
        "Development": ["code", "bug", "fix", "develop", "api", "database", "deploy", "test", "refactor"],
        "Learning":    ["learn", "study", "research", "read", "course", "tutorial"],
        "Work":        ["meeting", "email", "report", "review", "client", "presentation", "plan"],
        "Personal":    ["personal", "gym", "health", "family", "grocery", "home"],
    }
    for cat, keywords in cat_map.items():
        if any(k in msg_lower for k in keywords):
            category = cat
            break

    # Time estimate detection
    est_minutes = 60
    time_patterns = [
        (r"(\d+)\s*hour", lambda m: int(m.group(1)) * 60),
        (r"(\d+)\s*hr",   lambda m: int(m.group(1)) * 60),
        (r"(\d+)\s*min",  lambda m: int(m.group(1))),
        (r"half an? hour", lambda m: 30),
        (r"quarter hour",  lambda m: 15),
    ]
    import re as _re
    for pattern, extractor in time_patterns:
        match = _re.search(pattern, msg_lower)
        if match:
            try:
                est_minutes = extractor(match)
            except:
                pass
            break

    # Title extraction — strip filler words
    title = message
    filler = [
        r"^(add|create|make|new|schedule|set up)\s+(a\s+)?(new\s+)?task\s+(to\s+|for\s+)?",
        r"^(remind me to|i need to)\s+",
        r"\s*(,?\s*(high|low|medium|critical|urgent)\s+priority).*$",
        r"\s*(,?\s*estimate[d]?\s*\d+\s*(hour|hr|min).*)$",
        r"\s*(,?\s*due\s+.*)$",
    ]
    for f in filler:
        title = re.sub(f, "", title, flags=re.IGNORECASE).strip()

    # Capitalize first letter
    if title:
        title = title[0].upper() + title[1:]

    return {
        "title":              title or "New Task",
        "priority":           priority,
        "category":           category,
        "estimated_minutes":  est_minutes,
        "status":             "pending",
    }


def execute_task_action(intent: str, message: str, db: Session) -> Optional[dict]:
    """
    Execute DB actions based on intent.
    Returns action result dict, or None if no action needed.
    """
    if intent == "create_task":
        task_data = extract_task_from_message(message)
        db_task = Task(**task_data)
        db.add(db_task)
        db.commit()
        db.refresh(db_task)
        return {
            "action": "task_created",
            "task_id": db_task.id,
            "task_title": db_task.title,
            "priority": db_task.priority,
            "category": db_task.category,
            "estimated_minutes": db_task.estimated_minutes,
        }

    # Other actions (complete, etc.) need task ID — let LLM handle the response
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  SYSTEM PROMPT
# ══════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """You are Cognitive — an intelligent, friendly AI assistant that combines the warmth of a personal coach with the precision of a productivity expert. You help users manage tasks, track productivity, and make smart decisions about their time.

Your personality:
- Warm, conversational, and encouraging (like a supportive friend, not a corporate bot)
- Direct and concise — don't pad responses with fluff
- Smart about context — you always reference the user's actual tasks and data
- You can handle general conversation naturally, not just task stuff
- Use emojis sparingly but meaningfully
- Never say "As an AI..." or "I cannot..." — just be helpful

Your capabilities:
- View, create, update, and analyze tasks from the live database
- Predict how long tasks will actually take using ML
- Identify productivity patterns and give personalized insights
- Plan and schedule the user's day intelligently
- Have normal conversations about any topic

When the user's message is task-related:
- Always reference their ACTUAL tasks from the context provided
- Give specific, actionable recommendations
- If you created or modified a task, confirm it clearly

When the message is general conversation:
- Just chat naturally — be helpful and friendly
- You can still weave in productivity tips if relevant
"""


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN SMART CHAT FUNCTION
# ══════════════════════════════════════════════════════════════════════════════

def smart_chat(
    message: str,
    db: Session,
    conversation_history: list = None
) -> dict:
    """
    Main entry point for the task-aware AI chat.

    Returns:
        {
            "reply": str,
            "intent": str,
            "action_taken": dict | None,
            "task_context_used": bool
        }
    """
    if conversation_history is None:
        conversation_history = []

    # 1. Detect intent
    intent = detect_intent(message)
    logger.info(f"[SMART CHAT] Intent: {intent} | Message: {message[:60]}...")

    # 2. Execute any DB actions first (before LLM call)
    action_taken = None
    action_summary = ""
    if intent in ["create_task", "complete_task"]:
        action_taken = execute_task_action(intent, message, db)
        if action_taken:
            action_summary = f"\n[SYSTEM: Action executed → {json.dumps(action_taken)}]\n"

    # 3. Build context — inject live task data for task-related intents
    task_context = ""
    task_context_used = False
    if intent != "general_chat":
        task_context = build_task_context(db)
        task_context_used = True

    # 4. Build messages for Ollama
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Add task context as a system message if needed
    if task_context:
        messages.append({
            "role": "system",
            "content": f"CURRENT TASK DATA:\n{task_context}"
        })

    # Add conversation history (last 6 turns for memory)
    for turn in conversation_history[-6:]:
        messages.append(turn)

    # Add action summary if something was done
    user_content = message
    if action_summary:
        user_content = f"{message}\n{action_summary}"

    messages.append({"role": "user", "content": user_content})

    # 5. Call Ollama
    try:
        with httpx.Client(timeout=300.0) as client:
            resp = client.post(
                f"{OLLAMA_BASE_URL}/api/chat",
                json={
                    "model": OLLAMA_MODEL,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "temperature": 0.7,
                        "top_p": 0.9,
                        "num_predict": 512,
                    }
                }
            )
            resp.raise_for_status()
            data = resp.json()
            reply = data["message"]["content"].strip()

    except httpx.ConnectError:
        # Graceful fallback if Ollama is down
        reply = _fallback_response(intent, message, db, action_taken)

    except Exception as e:
        logger.error(f"Ollama error: {e}")
        reply = _fallback_response(intent, message, db, action_taken)

    return {
        "reply":              reply,
        "intent":             intent,
        "action_taken":       action_taken,
        "task_context_used":  task_context_used,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  FALLBACK (when Ollama is unavailable)
# ══════════════════════════════════════════════════════════════════════════════

def _fallback_response(intent: str, message: str, db: Session, action_taken: dict) -> str:
    """Rule-based fallback when LLM is unavailable."""

    if action_taken and action_taken.get("action") == "task_created":
        t = action_taken
        return (
            f"✅ Task created!\n\n"
            f"**{t['task_title']}**\n"
            f"• Priority: {t['priority']}\n"
            f"• Category: {t['category']}\n"
            f"• Estimated: {t['estimated_minutes']} minutes\n\n"
            f"*(AI response unavailable — Ollama offline)*"
        )

    if intent == "list_tasks":
        pending = db.query(Task).filter(
            Task.status.in_(["pending", "in_progress"])
        ).order_by(Task.due_date).limit(10).all()

        if not pending:
            return "🎉 You have no pending tasks! Nice work."

        lines = [f"📋 You have **{len(pending)} pending tasks**:\n"]
        for t in pending:
            due = f" — due {t.due_date.date()}" if t.due_date else ""
            lines.append(f"• [{t.priority}] {t.title}{due} (~{t.estimated_minutes}min)")
        return "\n".join(lines)

    if intent == "task_analytics":
        total = db.query(Task).count()
        done  = db.query(Task).filter(Task.status == "completed").count()
        rate  = round(done / total * 100, 1) if total > 0 else 0
        return (
            f"📊 **Your Stats:**\n"
            f"• Total tasks: {total}\n"
            f"• Completed: {done} ({rate}%)\n"
            f"• ML model: {'✅ Active' if predictor.is_trained else '⚠️ Not trained'}\n\n"
            f"*(Full AI insights unavailable — Ollama offline)*"
        )

    return "I'm having trouble connecting to my AI brain right now. Please check if Ollama is running and try again! 🔧"

# ══════════════════════════════════════════════════════════════════════════════
#  BACKWARDS COMPATIBILITY — keeps existing /plan and /query routes working
# ══════════════════════════════════════════════════════════════════════════════

def query_with_memory(db: Session, user_query: str) -> str:
    """
    Legacy wrapper — routes old /chat and /query calls
    through the new smart_chat engine.
    """
    result = smart_chat(message=user_query, db=db)
    return result["reply"]


def generate_daily_plan(db: Session) -> str:
    """
    Legacy wrapper — routes old /plan calls
    through the smart_chat engine with a planning prompt.
    """
    result = smart_chat(
        message="Generate my daily plan and tell me what to work on today",
        db=db
    )
    return result["reply"]
