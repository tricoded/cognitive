# app/llm/agent.py
import httpx
import os
import re
import logging
from datetime import datetime, date, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from app.models import Task
from app.ml.task_predictor import TaskDifficultyPredictor
from rapidfuzz import fuzz, process
from app.ml.intent_classifier import intent_clf
from app.ml.user_patterns import analyze_user_patterns
from app.ml.streaks import get_streak

logger = logging.getLogger(__name__)

# ── Ollama Config ──────────────────────────────────────────────────────────
OLLAMA_HOST     = os.getenv("OLLAMA_HOST", "localhost")
OLLAMA_PORT     = os.getenv("OLLAMA_PORT", "11434")
OLLAMA_BASE_URL = (
    OLLAMA_HOST if OLLAMA_HOST.startswith("http")
    else f"http://{OLLAMA_HOST}:{OLLAMA_PORT}"
)
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral")

# ── Singleton predictor ────────────────────────────────────────────────────
predictor = TaskDifficultyPredictor()

PRIORITY_EMOJI = {"Critical": "🔴", "High": "🟠", "Medium": "🟡", "Low": "🟢", "Overdue": "🚨"}
STATUS_EMOJI   = {"pending": "⏳", "in_progress": "🔄", "completed": "✅"}


# ══════════════════════════════════════════════════════════════════════════════
#  INTENT DETECTION
# ══════════════════════════════════════════════════════════════════════════════

INTENT_PATTERNS = {
    "help": [
        r"\bhelp\b",
        r"\bwhat can you do\b",
        r"\bhow do i\b",
        r"\bcommands?\b",
        r"\btemplate\b",
        r"\bhow does this work\b",
    ],
    "create_task": [
        r"\b(add|create|make|new|set up|schedule)\b.*\btask\b",
        r"\btask\b.*\b(add|create|make|new)\b",
        r"\bremind me to\b",
        r"\bi need to\b",
        r"\bput\b.*\bon my list\b",
        r"\bi have to\b",
        r"\bdon'?t forget to\b",
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
        r"\bi (finished|completed|did)\b",
        r"\bcomplete task\b",
        r"\bmark task\b",
    ],
    "set_priority": [
        r"\bset\b.*\btask\b.*\bpriority\b",
        r"\bset\b.*\bpriority\b.*\btask\b",
        r"\bchange\b.*\bpriority\b",
        r"\bupdate\b.*\bpriority\b",
        r"\btask\b.*\bpriority\b.*(to|as)\b",
        r"\bmark\b.*\btask\b.*(high|low|medium|critical)\b",
        r"\bpriority.*to\b",
    ],
    "bulk_set_priority": [
        r"\bset\b.*\btasks?\b.*#\d+.*#\d+",
        r"\bupdate\b.*\btasks?\b.*#\d+.*#\d+",
    ],
    "review_priorities": [
        r"\breview\b.*\bpriorities\b",
        r"\bpriorities\b.*\breview\b",
        r"\bset all priorities\b",
        r"\bfix.*priorities\b",
        r"\bprioritize.*tasks\b",
        r"\bprioritize my\b",
    ],
    "task_analytics": [
        r"\b(how|what).*(productive|productivity|performing|accuracy|doing)\b",
        r"\b(stats|statistics|analytics|report|insights?|trends?)\b",
        r"\bhow (am i|have i been)\b",
        r"\bmy (performance|progress|week|month)\b",
        r"\bshow.*stats\b",
    ],
    "task_predict": [
        r"\bhow long\b",
        r"\b(estimate|predict|guess)\b.*\btask\b",
        r"\bwill.*take\b",
        r"\btime estimate\b",
    ],
    "get_plan": [
        r"\b(plan|schedule|organize)\b.*\b(my day|today|tasks?)\b",
        r"\bwhat should i (do|work on|tackle|start)\b",
        r"\b(best order|optimal|most important)\b",
        r"\bplan my day\b",
        r"\bmy day\b",
    ],
    "general_chat": [],
}

def strip_markdown(text: str) -> str:
    """Remove common markdown symbols from LLM responses."""
    if not text:
        return text
 
    # Remove headings:  ## Title → Title
    text = re.sub(r'#{1,6}\s*', '', text)
 
    # Remove bold/italic: **text** or *text* or __text__ or _text_
    text = re.sub(r'\*{1,3}(.+?)\*{1,3}', r'\1', text)
    text = re.sub(r'_{1,3}(.+?)_{1,3}',   r'\1', text)
 
    # Remove inline code: `code` → code
    text = re.sub(r'`(.+?)`', r'\1', text)
 
    # Remove code blocks: ```...``` → (contents only)
    text = re.sub(r'```[\s\S]*?```', '', text)
 
    # Remove blockquotes: > text → text
    text = re.sub(r'^\s*>\s?', '', text, flags=re.MULTILINE)
 
    # Remove horizontal rules: --- or ***
    text = re.sub(r'^[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)
 
    # Remove bullet points: - item or * item → item
    text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)
 
    # Remove numbered lists: 1. item → item
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)
 
    # Remove links: [text](url) → text
    text = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', text)
 
    # Remove images: ![alt](url) → (removed)
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
 
    # Collapse 3+ newlines into 2
    text = re.sub(r'\n{3,}', '\n\n', text)
 
    return text.strip()


def detect_intent(message: str) -> str:
    msg_lower = message.lower()
    for intent in ["bulk_set_priority", "set_priority", "review_priorities",
                   "complete_task", "create_task", "list_tasks", "get_plan",
                   "task_analytics", "task_predict", "help"]:
        patterns = INTENT_PATTERNS.get(intent, [])
        for pattern in patterns:
            if re.search(pattern, msg_lower):
                return intent
    return "general_chat"


INTENT_KEYWORDS = {
    "complete_task":      ["complete", "done", "finish", "finished", "completed", "mark done", "close"],
    "create_task":        ["add", "create", "new task", "remind", "i need to", "schedule"],
    "list_tasks":         ["show", "list", "display", "what tasks", "my tasks", "see tasks"],
    "get_plan":           ["plan", "schedule today", "what should i do", "daily plan", "my day"],
    "task_analytics":     ["stats", "analytics", "productivity", "how am i doing", "progress"],
    "help":               ["help", "how does", "what can you", "commands"],
    "review_priorities":  ["review priorities", "prioritize", "sort priorities"],
    "set_priority":       ["set priority", "change priority", "update priority", "priority to"],
}

def detect_intent(message: str) -> str:
    # 1. Try ML classifier first
    if intent_clf.is_trained:
        intent, confidence = intent_clf.predict(message)
        logger.info(f"[ML Intent] {intent} ({confidence:.2f})")
        if confidence >= 0.45:
            return intent
 
    # 2. Fallback to regex
    msg_lower = message.lower()

    for intent, patterns in INTENT_PATTERNS.items():
        if intent == "general_chat":
            continue
        for pattern in patterns:
            if re.search(pattern, msg_lower):
                return intent
 
    # 3. Fuzzy keyword scoring fallback
    scores = {
        "create_task":    sum(msg_lower.count(w) for w in ["task", "add", "todo", "need", "create", "remind", "finish"]),
        "complete_task":  sum(msg_lower.count(w) for w in ["done", "complete", "finished", "completed", "mark"]),
        "list_tasks":     sum(msg_lower.count(w) for w in ["list", "show", "pending", "see", "view"]),
        "get_plan":       sum(msg_lower.count(w) for w in ["plan", "day", "schedule", "today", "focus", "should"]),
        "task_analytics": sum(msg_lower.count(w) for w in ["stats", "streak", "progress", "analytics", "how"]),
        "set_priority":   sum(msg_lower.count(w) for w in ["priority", "urgent", "critical", "wizard", "review"]),
        "delete_task":    sum(msg_lower.count(w) for w in ["delete", "remove", "cancel"]),
    }

    best = max(scores, key=scores.get)
    if scores[best] > 0:
        logger.info(f"[Intent] Fuzzy match → {best} (score: {scores[best]})")
        return best

    return "general_chat"

# ══════════════════════════════════════════════════════════════════════════════
#  PRIORITY HELPERS  — defined early so everything below can call them
# ══════════════════════════════════════════════════════════════════════════════

def compute_auto_priority(task) -> str:
    """
    Derive priority from deadline. Returns a priority string.
    Called by daily_priority_refresh and extract_task_from_message.
    """
    if not task.due_date:
        return task.priority or "Medium"

    today     = date.today()
    due       = task.due_date.date() if hasattr(task.due_date, "date") else task.due_date
    days_left = (due - today).days

    if days_left < 0:
        return "Overdue"
    elif days_left <= 1:
        return "Critical"
    elif days_left <= 3:
        return "High"
    elif days_left <= 7:
        return "Medium"
    else:
        return "Low"


def resolve_priority(task) -> str:
    """
    Always use deadline-derived priority if it's more urgent than stored.
    """
    auto    = compute_auto_priority(task)
    order   = {"Overdue": 0, "Critical": 1, "High": 2, "Medium": 3, "Low": 4}
    stored  = task.priority or "Medium"
    if order.get(auto, 99) < order.get(stored, 99):
        return auto
    return stored


# ══════════════════════════════════════════════════════════════════════════════
#  DB HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def get_task_by_id(task_id: int, db: Session) -> Optional[Task]:
    return db.query(Task).filter(Task.id == task_id).first()


def update_task_priority(task_id: int, priority: str, db: Session) -> bool:
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return False
    task.priority = priority
    db.commit()
    return True


def get_all_pending_tasks(db: Session) -> list:
    """Returns ALL pending/in-progress tasks ordered by ID for the wizard."""
    return (
        db.query(Task)
        .filter(Task.status.in_(["pending", "in_progress"]))
        .order_by(Task.id)
        .all()
    )


# ══════════════════════════════════════════════════════════════════════════════
#  DEADLINE PARSER
# ══════════════════════════════════════════════════════════════════════════════

def parse_deadline(message: str) -> Optional[date]:
    """Extract a due date from natural language. Returns a date or None."""
    msg   = message.lower()
    today = datetime.now().date()

    if re.search(r"\b(today|tonight)\b", msg):
        return today

    if re.search(r"\btomorrow\b", msg):
        return today + timedelta(days=1)

    m = re.search(r"\bin\s+(\d+)\s+days?\b", msg)
    if m:
        return today + timedelta(days=int(m.group(1)))

    m = re.search(r"\bnext\s+week\b", msg)
    if m:
        return today + timedelta(days=7)

    m = re.search(r"\bend\s+of\s+(the\s+)?week\b", msg)
    if m:
        days_to_friday = (4 - today.weekday()) % 7
        return today + timedelta(days=days_to_friday or 7)

    days = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6,
    }
    m = re.search(
        r"\b(by\s+|this\s+)(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        msg,
    )
    if m:
        target_day = days[m.group(2)]
        today_day  = today.weekday()
        delta      = (target_day - today_day) % 7 or 7
        return today + timedelta(days=delta)

    # Explicit date e.g. "by 3/25" or "by 25-3"
    m = re.search(r"\bby\s+(\d{1,2})[\/\-](\d{1,2})\b", msg)
    if m:
        try:
            month, day = int(m.group(1)), int(m.group(2))
            target = date(today.year, month, day)
            if target < today:
                target = date(today.year + 1, month, day)
            return target
        except ValueError:
            pass

    return None


# ══════════════════════════════════════════════════════════════════════════════
#  DAILY PRIORITY REFRESH  — call once per session on app load
# ══════════════════════════════════════════════════════════════════════════════

def daily_priority_refresh(db: Session) -> list:
    """
    Re-evaluate task priorities based on deadlines.
    Returns list of (id, title, old_priority, new_priority) tuples.
    """
    pending = db.query(Task).filter(
        Task.status.in_(["pending", "in_progress"]),
        Task.due_date.isnot(None),
    ).all()

    escalated = []
    for task in pending:
        new_priority = compute_auto_priority(task)  # ✅ now defined above
        if new_priority != task.priority:
            old          = task.priority
            task.priority = new_priority
            escalated.append((task.id, task.title, old, new_priority))

    if escalated:
        db.commit()

    return escalated


# ══════════════════════════════════════════════════════════════════════════════
#  TASK EXTRACTION
# ══════════════════════════════════════════════════════════════════════════════

def extract_task_from_message(message: str) -> tuple[dict, bool]:
    """
    Returns (task_data_dict, priority_was_explicit).
    priority_was_explicit = False triggers the inline priority guide.
    """
    msg_lower = message.lower()

    # ── 1. Explicit priority detection ────────────────────────────────────
    priority_was_explicit = True
    explicit_priority     = None

    if any(w in msg_lower for w in ["critical", "urgent", "asap", "immediately"]):
        explicit_priority = "Critical"
    elif any(w in msg_lower for w in ["high priority", "high-priority", "important"]):
        explicit_priority = "High"
    elif re.search(r"\bhigh\b", msg_lower):
        explicit_priority = "High"
    elif any(w in msg_lower for w in ["low priority", "low-priority", "someday", "eventually", "later"]):
        explicit_priority = "Low"
    elif re.search(r"\blow\b", msg_lower):
        explicit_priority = "Low"
    elif any(w in msg_lower for w in ["medium priority", "medium", "middle", "normal priority"]):
        explicit_priority = "Medium"
    else:
        priority_was_explicit = False   # no explicit signal

    # ── 2. Deadline detection → auto-priority ────────────────────────────
    due_date      = parse_deadline(message)  # ✅ always runs, not inside else block
    auto_priority = None

    if due_date:
        days_left = (due_date - date.today()).days
        if days_left <= 0:
            auto_priority = "Critical"
        elif days_left <= 1:
            auto_priority = "Critical"
        elif days_left <= 3:
            auto_priority = "High"
        elif days_left <= 7:
            auto_priority = "Medium"
        else:
            auto_priority = "Low"

        # Deadline-derived priority counts as explicit (no guide needed)
        if auto_priority:
            priority_was_explicit = True

    # ── 3. Final priority: explicit > auto > default ──────────────────────
    order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    if explicit_priority and auto_priority:
        # Take the more urgent of the two
        final_priority = explicit_priority if order[explicit_priority] <= order[auto_priority] else auto_priority
    else:
        final_priority = explicit_priority or auto_priority or "Medium"

    # ── 4. Category ────────────────────────────────────────────────────────
    category = "Work"
    cat_map  = {
        "Development": [
            "code", "bug", "fix", "develop", "api", "database",
            "deploy", "test", "refactor", "frontend", "backend", "pr", "commit", "push",
        ],
        "Learning": [
            "learn", "study", "research", "read", "course", "tutorial", "docs", "documentation",
        ],
        "Personal": [
            "personal", "gym", "health", "family", "grocery", "home",
            "parents", "mom", "dad", "call", "friend", "doctor",
            "dentist", "chores", "cook", "clean", "shopping", "haircut",
        ],
        "Finance": [
            "pay", "bill", "invoice", "bank", "transfer", "budget",
            "tax", "expense", "salary", "finance", "money",
        ],
        "Work": [
            "meeting", "email", "report", "review", "client",
            "presentation", "plan", "project", "boss", "team",
        ],
    }
    for cat, keywords in cat_map.items():
        if any(k in msg_lower for k in keywords):
            category = cat
            break

    # ── 5. Time estimate ────────────────────────────────────────────────────
    est_minutes   = 60
    time_patterns = [
        (r"(\d+)\s*hour",  lambda m: int(m.group(1)) * 60),
        (r"(\d+)\s*hr",    lambda m: int(m.group(1)) * 60),
        (r"(\d+)\s*min",   lambda m: int(m.group(1))),
        (r"half an? hour", lambda _: 30),
        (r"quarter hour",  lambda _: 15),
        (r"2\s*hours?",    lambda _: 120),
    ]
    for pattern, extractor in time_patterns:
        match = re.search(pattern, msg_lower)
        if match:
            try:
                est_minutes = extractor(match)
            except Exception:
                pass
            break

    # ── 6. Title — multi-pass strip ────────────────────────────────────────
    title  = message
    filler = [
        # Leading triggers
        r"^(add|create|make|new|schedule|set up)\s+(a\s+)?(new\s+)?task\s+(to\s+|for\s+)?",
        r"^(remind me to|i need to|i want to|i have to|don'?t forget to)\s+",
        # Trailing: time
        r",?\s*\d+\s*(hour|hr|min|minute)s?(\s+long)?\s*$",
        r",?\s*(half an? hour|quarter hour)\s*$",
        # Trailing: priority phrases
        r",?\s*(top\s+)?priority\s*[:\-]?\s*(critical|urgent|high|medium|middle|low|normal)\s*$",
        r",?\s*(critical|urgent|asap|high|medium|middle|normal|low)\s+priority\s*$",
        r",?\s*it'?s?\s*(critical|urgent|high|medium|low|important)\s*$",
        r",?\s*\b(critical|urgent|asap)\b\s*$",
        r",?\s*\b(high|important)\s*priority\b\s*$",
        r",?\s*\b(low|someday|eventually)\s*priority\b\s*$",
        r",?\s*\bpriority\s+(high|low|medium|critical)\b\s*$",
        r",?\s*\b(high|low|medium|critical)\b\s*$",  # bare trailing priority word
        # Trailing: category
        r",?\s*category\s*[:\-]?\s*\w+\s*$",
        # Trailing: due date
        r",?\s*(due\s+)?(by\s+|this\s+)?(today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s*$",
        r",?\s*due\s+(by\s+)?\d{1,2}[\/\-]\d{1,2}\s*$",
        r",?\s*(in\s+\d+\s+days?|next\s+week|end\s+of\s+(the\s+)?week)\s*$",
        # Trailing: estimate keyword
        r",?\s*estimated?\s*(time\s*)?\d+.*$",
    ]

    for _ in range(5):      # up to 5 passes
        prev = title
        for f in filler:
            title = re.sub(f, "", title, flags=re.IGNORECASE).strip()
        if title == prev:
            break

    # Clean up trailing punctuation / dangling conjunctions
    title = re.sub(r"[,;\-]+$", "", title).strip()
    title = re.sub(r"\s+(and|with|at|in|on|for|to)$", "", title, flags=re.IGNORECASE).strip()

    if not title:
        title = "New Task"
    else:
        title = title[0].upper() + title[1:]

    # ── 7. Return ─────────────────────────────────────────────────────────
    return (
        {
            "title":             title,
            "priority":          final_priority,
            "category":          category,
            "estimated_minutes": est_minutes,
            "due_date":          datetime.combine(due_date, datetime.min.time()) if due_date else None,
            "status":            "pending",
            "notes":             "",
        },
        priority_was_explicit,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  SMART FOLLOW-UP SUGGESTIONS
# ══════════════════════════════════════════════════════════════════════════════

def smart_follow_up(db: Session, last_action: str, task_id: int = None) -> str:
    """Returns a contextual follow-up line appended to any handler reply."""
    pending  = db.query(Task).filter(Task.status.in_(["pending", "in_progress"])).count()
    critical = db.query(Task).filter(
        Task.priority == "Critical", Task.status != "completed"
    ).count()
    unset    = db.query(Task).filter(
        Task.priority == "Medium", Task.status != "completed"
    ).count()

    if last_action == "task_created":
        if critical > 2:
            return f"\n\n💡 *You have {critical} critical tasks — say 'plan my day' to tackle them in order.*"
        if unset > 3:
            return f"\n\n💡 *{unset} tasks have no priority — say 'review priorities' to sort them fast.*"
        return "\n\n💡 *Say 'plan my day' to see your full schedule.*"

    if last_action == "task_completed":
        if critical > 0:
            return f"\n\n🔥 *{critical} critical task(s) still pending — keep the momentum!*"
        if pending == 0:
            return "\n\n🎉 *You cleared everything! Say 'show my stats' to see your progress.*"
        return f"\n\n⏭️ *{pending} tasks left — say 'plan my day' for what's next.*"

    if last_action == "priority_set":
        return "\n\n📅 *Say 'plan my day' to see your updated schedule.*"

    return ""


# ══════════════════════════════════════════════════════════════════════════════
#  EXECUTE TASK ACTION
# ══════════════════════════════════════════════════════════════════════════════

def execute_task_action(intent: str, message: str, db: Session) -> Optional[dict]:
    if intent == "create_task":
        task_data, priority_was_explicit = extract_task_from_message(message)
        db_task = Task(**task_data)
        db.add(db_task)
        db.commit()
        db.refresh(db_task)
        return {
            "action":                "task_created",
            "task_id":               db_task.id,
            "task_title":            db_task.title,
            "priority":              db_task.priority,
            "category":              db_task.category,
            "estimated_minutes":     db_task.estimated_minutes,
            "due_date":              db_task.due_date.date().isoformat() if db_task.due_date else None,
            "priority_was_explicit": priority_was_explicit,
        }
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  DIRECT HANDLERS — Zero Ollama, instant responses
# ══════════════════════════════════════════════════════════════════════════════

def handle_greeting(db: Session) -> dict:
    """Smart time-aware briefing on every greeting."""
    hour = datetime.now().hour

    if hour < 12:
        time_greeting = "Good morning"
        energy_tip    = "🧠 *Morning = peak focus. Tackle your hardest task first.*"
    elif hour < 17:
        time_greeting = "Good afternoon"
        energy_tip    = "☕ *Afternoon slump is real. Start with a quick win to build momentum.*"
    else:
        time_greeting = "Good evening"
        energy_tip    = "🌙 *Evening mode — great time to plan tomorrow or knock out low-effort tasks.*"

    pending   = db.query(Task).filter(Task.status.in_(["pending", "in_progress"])).all()
    critical  = [t for t in pending if t.priority in ("Critical", "Overdue")]
    high      = [t for t in pending if t.priority == "High"]
    total_min = sum(t.estimated_minutes or 60 for t in pending[:8])
    hrs, mins = total_min // 60, total_min % 60

    if not pending:
        return {
            "reply": (
                f"**{time_greeting}! 👋**\n\n"
                f"🎉 Your task list is empty — you're all caught up!\n\n"
                f"{energy_tip}\n\n"
                f"*Say 'add a task to...' whenever you're ready.*"
            ),
            "intent":        "general_chat",
            "action_taken":  None,
            "session_update": {},
        }

    lines = [f"**{time_greeting}! 👋 Here's your snapshot:**\n"]
    lines.append(f"📋 **{len(pending)} tasks** pending · ~{hrs}h {mins}min of work\n")

    if critical:
        lines.append(f"🔴 **{len(critical)} Critical/Overdue** — needs attention today:")
        for t in critical[:3]:
            due_str = f" *(due {t.due_date.date()})*" if t.due_date else ""
            lines.append(f"   → #{t.id} {t.title}{due_str}")
        lines.append("")

    if high:
        lines.append(f"🟠 **{len(high)} High priority** tasks queued")
        lines.append("")

    lines.append(energy_tip)
    lines.append("\n**What would you like to do?**")
    lines.append(
        "> 📅 *'plan my day'* · ➕ *'add a task'* · "
        "✅ *'complete task #X'* · 📊 *'show my stats'*"
    )

    # agent.py — inside handle_greeting()

    patterns = analyze_user_patterns(db, user_id=0)  # pass real user_id
    insight_lines = []

    if patterns.get("peak_hour"):
        h = patterns["peak_hour"]
        insight_lines.append(
            f"⚡ *Your peak focus is usually around {h}:00 — "
            f"schedule your hardest task then.*"
        )

    if patterns.get("tends_to"):
        err = patterns.get("avg_estimate_error_min", 0)
        insight_lines.append(
            f"🎯 *You tend to {patterns['tends_to']} tasks by ~{err:.0f}min — "
            f"I've adjusted your plan.*"
        )

    if patterns.get("best_day"):
        insight_lines.append(
            f"📅 *Your most productive day is {patterns['best_day']}.*"
        )

    if insight_lines:
        lines.append("\n**🧠 Your patterns:**")
        lines.extend(insight_lines)

    return {
        "reply":        "\n".join(lines),
        "intent":       "general_chat",
        "action_taken": None,
        "session_update": {},
    }


def handle_help() -> dict:
    return {
        "reply": (
            "## 🧠 Here's what I can do!\n\n"
            "**➕ Add a Task**\n"
            "> *'add a task to fix the login bug'*\n"
            "> *'add a task to call dentist, high priority, 30 minutes'*\n"
            "> *'remind me to submit report by Friday'* ← deadline auto-sets priority!\n\n"
            "**📋 View Tasks**\n"
            "> *'show my tasks'*\n"
            "> *'show high priority tasks'* · *'show critical tasks'*\n\n"
            "**✅ Complete a Task**\n"
            "> *'complete task #3'* · *'mark task 5 as done'*\n\n"
            "**🎯 Update Priority**\n"
            "> *'set task #3 priority to high'*\n"
            "> *'set tasks #3 high, #4 low, #5 critical'* ← bulk update\n"
            "> *'review priorities'* ← guided wizard for all tasks\n\n"
            "**📅 Plan Your Day**\n"
            "> *'plan my day'* · *'what should I work on today?'*\n\n"
            "**📊 Stats & Insights**\n"
            "> *'show my stats'* · *'how productive have I been?'*\n\n"
            "**🔮 Time Estimates**\n"
            "> *'how long will my tasks take?'*\n\n"
            "**💬 General Chat**\n"
            "> Just talk naturally! Typos are fine — I'll figure it out. 😊"
        ),
        "intent":        "help",
        "action_taken":  None,
        "session_update": {},
    }


def handle_list_tasks(message: str, db: Session) -> dict:
    msg_lower = message.lower()
    query     = db.query(Task)

    if "completed" in msg_lower or "done" in msg_lower:
        tasks  = query.filter(Task.status == "completed").limit(15).all()
        header = "✅ Completed Tasks"
    elif "critical" in msg_lower or "overdue" in msg_lower:
        tasks  = query.filter(
            Task.priority.in_(["Critical", "Overdue"]),
            Task.status.in_(["pending", "in_progress"]),
        ).all()
        header = "🔴 Critical / Overdue Tasks"
    elif "high" in msg_lower:
        tasks  = query.filter(
            Task.priority == "High",
            Task.status.in_(["pending", "in_progress"]),
        ).all()
        header = "🟠 High Priority Tasks"
    elif "low" in msg_lower:
        tasks  = query.filter(
            Task.priority == "Low",
            Task.status.in_(["pending", "in_progress"]),
        ).all()
        header = "🟢 Low Priority Tasks"
    else:
        tasks  = query.filter(Task.status.in_(["pending", "in_progress"])).all()
        header = "📋 Pending Tasks"

    if not tasks:
        return {
            "reply":        "🎉 No tasks found! Try *'add a task to...'* to create one.",
            "intent":       "list_tasks",
            "action_taken": None,
            "session_update": {},
        }

    order        = {"Overdue": 0, "Critical": 1, "High": 2, "Medium": 3, "Low": 4}
    tasks_sorted = sorted(tasks, key=lambda t: order.get(resolve_priority(t), 99))

    lines       = [f"**{header}** — {len(tasks_sorted)} total\n"]
    unset_count = 0
    today       = date.today()

    for t in tasks_sorted:
        display_priority = resolve_priority(t)   # deadline-aware
        p_icon  = PRIORITY_EMOJI.get(display_priority, "⚪")
        s_icon  = STATUS_EMOJI.get(t.status, "❓")
        dur     = f" · ⏱️ {t.estimated_minutes}min" if t.estimated_minutes else ""
        due_str = ""
        if t.due_date:
            d         = t.due_date.date()
            days_left = (d - today).days
            if days_left < 0:
                due_str = f" · 📅 **OVERDUE** ({d})"
            elif days_left == 0:
                due_str = f" · 📅 **Due today!**"
            elif days_left == 1:
                due_str = f" · 📅 Due tomorrow"
            else:
                due_str = f" · 📅 {d}"

        # Flag tasks with no meaningful priority (defaulted to Medium, no deadline)
        is_unset = (t.priority == "Medium" and not t.due_date)
        flag     = " *(no priority set)*" if is_unset else ""
        if is_unset:
            unset_count += 1

        lines.append(f"{p_icon} **#{t.id}** {t.title}{flag} {s_icon}{dur}{due_str}")

    lines.append(
        "\n💡 *Say 'complete task #X' to mark done · 'add a task to...' to create one.*"
    )

    if unset_count >= 3:
        lines.append(
            f"\n─────────────────────────────\n"
            f"💡 **{unset_count} tasks have no priority set.**\n"
            f"Say *'review priorities'* and I'll walk you through them one by one!"
        )

    return {
        "reply":        "\n".join(lines),
        "intent":       "list_tasks",
        "action_taken": None,
        "session_update": {},
    }


def handle_create_task(message: str, db: Session) -> dict:
    action_taken = execute_task_action("create_task", message, db)
    if not action_taken:
        return {
            "reply":        "⚠️ Couldn't parse a task. Try: *'add a task to fix the login bug'*",
            "intent":       "create_task",
            "action_taken": None,
            "session_update": {},
        }

    t                     = action_taken
    p_icon                = PRIORITY_EMOJI.get(t["priority"], "")
    priority_was_explicit = t.get("priority_was_explicit", True)
    dur_str               = f"\n• Estimated: **{t['estimated_minutes']} min**" if t["estimated_minutes"] else ""
    due_str               = f"\n• Due: **{t['due_date']}**" if t.get("due_date") else ""

    priority_hint = ""
    if not priority_was_explicit:
        priority_hint = (
            f"\n\n─────────────────────────────\n"
            f"Does that priority feel right?\n"
            f"🔴 **C**ritical — must happen today\n"
            f"🟠 **H**igh     — important this week\n"
            f"🟡 **M**edium   — flexible, no real deadline ← *current*\n"
            f"🟢 **L**ow      — whenever you get to it\n\n"
            f"*Say 'set task #{t['task_id']} priority to high' to update!*"
        )

    follow_up = smart_follow_up(db, "task_created", t["task_id"])

    return {
        "reply": (
            f"✅ **Task created!**\n\n"
            f"**#{t['task_id']}** {t['task_title']}\n"
            f"• Priority: {p_icon} **{t['priority']}**"
            + ("" if priority_was_explicit else " *(default — no priority mentioned)*")
            + f"\n• Category: **{t['category']}**"
            + dur_str
            + due_str
            + priority_hint
            + follow_up
        ),
        "intent":        "create_task",
        "action_taken":  action_taken,
        "session_update": {},
    }


def handle_complete_task(message: str, db: Session) -> dict:
    id_match = re.search(r"#?(\d+)", message)
    if not id_match:
        return {
            "reply": (
                "Please include the task number, e.g.:\n"
                "*'complete task #3'* or *'mark task 5 as done'*\n\n"
                "Not sure of the ID? Say *'show my tasks'* first."
            ),
            "intent":        "complete_task",
            "action_taken":  None,
            "session_update": {},
        }

    task_id = int(id_match.group(1))
    task    = db.query(Task).filter(Task.id == task_id).first()

    if not task:
        return {
            "reply":        f"⚠️ Couldn't find task **#{task_id}**. Say *'show my tasks'* to see all IDs.",
            "intent":        "complete_task",
            "action_taken":  None,
            "session_update": {},
        }

    if task.status == "completed":
        return {
            "reply":        f"✅ Task **#{task_id} — {task.title}** is already completed!",
            "intent":        "complete_task",
            "action_taken":  None,
            "session_update": {},
        }

    task.status       = "completed"
    task.completed_at = datetime.utcnow()

    # ── ✅ NEW: Track actual time for ML training ──────────────────────
    if task.created_at:
        elapsed = datetime.utcnow() - task.created_at
        elapsed_mins = int(elapsed.total_seconds() / 60)
        # Cap at 8 hours — avoids garbage data from forgotten tasks
        task.actual_minutes = min(elapsed_mins, 480)

    db.commit()

    # ── ✅ NEW: Auto-retrain predictor silently ────────────────────────
    predictor.retrain_if_ready(db)

    follow_up = smart_follow_up(db, "task_completed", task.id)

    # Show ML accuracy hint if trained
    ml_note = ""
    if predictor.is_trained and task.estimated_minutes and task.actual_minutes:
        diff = task.actual_minutes - task.estimated_minutes
        if abs(diff) > 10:
            direction = "longer" if diff > 0 else "shorter"
            ml_note   = f"\n🤖 *Took {abs(diff)}min {direction} than estimated — ML model updated.*"

    return {
        "reply": (
            f"🎉 **Done!** Task marked as complete:\n\n"
            f"**#{task.id}** {task.title}\n"
            f"• Priority was: {PRIORITY_EMOJI.get(task.priority, '')} {task.priority}\n"
            f"• Completed at: {datetime.now().strftime('%H:%M')}"
            + ml_note
            + follow_up
        ),
        "intent":       "complete_task",
        "action_taken": {"action": "task_completed", "task_id": task.id, "task_title": task.title},
        "session_update": {},
    }


def handle_set_priority(message: str, db: Session) -> dict:
    id_match  = re.search(r"#?(\d+)", message)
    pri_match = re.search(r"\b(critical|high|medium|low)\b", message, re.IGNORECASE)

    if not id_match or not pri_match:
        return {
            "reply": (
                "Please specify both the task number and priority, e.g.:\n"
                "*'set task #3 priority to high'*\n\n"
                "Priorities: 🔴 Critical · 🟠 High · 🟡 Medium · 🟢 Low"
            ),
            "intent":        "set_priority",
            "action_taken":  None,
            "session_update": {},
        }

    task_id  = int(id_match.group(1))
    priority = pri_match.group(1).capitalize()
    task     = db.query(Task).filter(Task.id == task_id).first()

    if not task:
        return {
            "reply":        f"⚠️ Task **#{task_id}** not found. Say *'show my tasks'* to see all IDs.",
            "intent":        "set_priority",
            "action_taken":  None,
            "session_update": {},
        }

    task.priority = priority
    db.commit()

    follow_up = smart_follow_up(db, "priority_set")

    return {
        "reply": (
            f"✅ **Updated!**\n\n"
            f"**#{task.id}** {task.title}\n"
            f"• Priority → {PRIORITY_EMOJI.get(priority, '')} **{priority}**"
            + follow_up
        ),
        "intent":       "set_priority",
        "action_taken": {"action": "priority_updated", "task_id": task.id, "priority": priority},
        "session_update": {},
    }


def handle_bulk_set_priority(message: str, db: Session) -> dict:
    pri_map = {
        "critical": "Critical", "high": "High",
        "medium": "Medium",     "low":  "Low",
    }
    pairs = re.findall(r"#?(\d+)\s+(critical|high|medium|low)", message, re.IGNORECASE)

    if not pairs:
        return {
            "reply": (
                "Couldn't parse that. Try:\n"
                "*'set tasks #3 high, #4 low, #5 critical'*"
            ),
            "intent":        "bulk_set_priority",
            "action_taken":  None,
            "session_update": {},
        }

    lines   = ["✅ **Updated priorities:**\n"]
    updated = []
    for task_id_str, pri_str in pairs:
        task_id  = int(task_id_str)
        priority = pri_map[pri_str.lower()]
        ok       = update_task_priority(task_id, priority, db)
        if ok:
            task = get_task_by_id(task_id, db)
            icon = PRIORITY_EMOJI.get(priority, "")
            lines.append(f"{icon} **#{task_id}** {task.title} → **{priority}**")
            updated.append(task_id)
        else:
            lines.append(f"⚠️ #{task_id} not found — skipped")

    lines.append(smart_follow_up(db, "priority_set"))

    return {
        "reply":        "\n".join(lines),
        "intent":       "bulk_set_priority",
        "action_taken": {"action": "bulk_priority_updated", "task_ids": updated},
        "session_update": {},
    }


def handle_start_priority_wizard(db: Session) -> dict:
    all_pending = get_all_pending_tasks(db)

    if not all_pending:
        return {
            "reply":        "🎉 No pending tasks to review! Say *'add a task'* to get started.",
            "intent":       "review_priorities",
            "action_taken": None,
            "session_update": {},
        }

    queue   = [t.id for t in all_pending]
    first   = all_pending[0]
    dur_str = f" ⏱️ {first.estimated_minutes}min" if first.estimated_minutes else ""
    p_icon  = PRIORITY_EMOJI.get(first.priority, "⚪")
    due_str = f" · 📅 due {first.due_date.date()}" if first.due_date else ""

    return {
        "reply": (
            f"Let's review all **{len(queue)} pending tasks** and make sure priorities are right.\n"
            f"Reply with one letter — **S** keeps the current priority.\n\n"
            f"🔴 **C**ritical · 🟠 **H**igh · 🟡 **M**edium · 🟢 **L**ow · ⏭️ **S**kip\n\n"
            f"───────────────────────\n"
            f"{p_icon} **#{first.id}** {first.title}{dur_str}{due_str}\n"
            f"Current: **{first.priority}** · Change to? **[C / H / M / L / S]**"
        ),
        "intent":       "review_priorities",
        "action_taken": None,
        "session_update": {
            "priority_review_active": True,
            "priority_review_queue":  queue,
        },
    }


def handle_priority_wizard_step(message: str, db: Session, session_state: dict) -> dict:
    queue   = list(session_state.get("priority_review_queue", []))
    mapping = {"c": "Critical", "h": "High", "m": "Medium", "l": "Low"}
    key     = message.strip().lower()[0] if message.strip() else ""

    if not queue:
        return {
            "reply": "🎉 All done! Say *'show my tasks'* to see your updated list.",
            "intent": "priority_review_done",
            "action_taken": None,
            "session_update": {
                "priority_review_active": False,
                "priority_review_queue":  [],
            },
        }

    current_task_id = queue[0]

    # Stop commands — handled here too as a safety net
    if message.strip().lower() in ("stop", "exit", "cancel", "quit"):
        return {
            "reply": "✅ Priority review stopped. Say *'show my tasks'* to see where things stand.",
            "intent": "priority_review_done",
            "action_taken": None,
            "session_update": {
                "priority_review_active": False,
                "priority_review_queue":  [],
            },
        }

    if key == "s":
        queue.pop(0)
    elif key in mapping:
        update_task_priority(current_task_id, mapping[key], db)
        queue.pop(0)
    else:
        # Invalid input — re-prompt same task
        task    = get_task_by_id(current_task_id, db)
        p_icon  = PRIORITY_EMOJI.get(task.priority, "⚪") if task else "⚪"
        dur_str = f" ⏱️ {task.estimated_minutes}min" if task and task.estimated_minutes else ""
        due_str = f" · 📅 due {task.due_date.date()}" if task and task.due_date else ""
        return {
            "reply": (
                f"❓ Please reply with just one letter:\n"
                f"🔴 **C** · 🟠 **H** · 🟡 **M** · 🟢 **L** · ⏭️ **S** (keep as-is)\n\n"
                f"{p_icon} **#{task.id}** {task.title}{dur_str}{due_str}\n"
                f"Current: **{task.priority}**"
            ),
            "intent": "priority_review_step",
            "action_taken": None,
            "session_update": {
                "priority_review_active": True,
                "priority_review_queue":  queue,
            },
        }

    if queue:
        next_task = get_task_by_id(queue[0], db)
        p_icon    = PRIORITY_EMOJI.get(next_task.priority, "⚪") if next_task else "⚪"
        dur_str   = f" ⏱️ {next_task.estimated_minutes}min" if next_task and next_task.estimated_minutes else ""
        due_str   = f" · 📅 due {next_task.due_date.date()}" if next_task and next_task.due_date else ""
        remaining = len(queue)
        return {
            "reply": (
                f"*{remaining} left* · ───────────────────────\n"
                f"{p_icon} **#{next_task.id}** {next_task.title}{dur_str}{due_str}\n"
                f"Current: **{next_task.priority}** · Change to? **[C / H / M / L / S]**"
            ),
            "intent": "priority_review_step",
            "action_taken": None,
            "session_update": {
                "priority_review_active": True,
                "priority_review_queue":  queue,
            },
        }
    else:
        return {
            "reply": (
                "🎉 **All priorities reviewed!**\n\n"
                "Say *'plan my day'* to get your optimized schedule."
            ),
            "intent": "priority_review_done",
            "action_taken": None,
            "session_update": {
                "priority_review_active": False,
                "priority_review_queue":  [],
            },
        }


def handle_analytics(db: Session) -> dict:
    from collections import Counter

    total    = db.query(Task).count()
    done     = db.query(Task).filter(Task.status == "completed").count()
    pending  = db.query(Task).filter(Task.status.in_(["pending", "in_progress"])).count()
    rate     = round(done / total * 100, 1) if total > 0 else 0
    critical = db.query(Task).filter(
        Task.priority.in_(["Critical", "Overdue"]), Task.status != "completed"
    ).count()
    high = db.query(Task).filter(
        Task.priority == "High", Task.status != "completed"
    ).count()

    completed_tasks = db.query(Task).filter(Task.status == "completed").all()
    cat_counts      = Counter(t.category for t in completed_tasks)
    cat_lines       = []
    for cat, count in cat_counts.most_common(5):
        bar = "█" * min(count, 10)
        cat_lines.append(f"   `{bar}` {cat}: **{count}** done")

    if rate >= 80:   mood = "🔥 You're on fire! Incredible consistency."
    elif rate >= 60: mood = "💪 Solid progress — keep the momentum going!"
    elif rate >= 40: mood = "📈 Making progress. Push through the backlog!"
    elif rate >= 20: mood = "🌱 Early days — every completed task counts."
    else:            mood = "💡 Just get one task done today — that's all it takes."

    total_actual   = sum(t.actual_minutes or 0 for t in completed_tasks)
    hours_invested = total_actual // 60

    ml_status = (
        "✅ Active — predictions improving with each completed task"
        if predictor.is_trained
        else "⚠️ Not yet trained — complete 5+ tasks to enable ML estimates"
    )

    # ── ✅ Single streak source ────────────────────────────────────────
    streak_data = get_streak(db, user_id=0)
    streak_cur  = streak_data["current"]
    streak_long = streak_data["longest"]
    today_count = streak_data["today_count"]

    lines = [
        "📊 **Your Productivity Stats**\n",
        f"• Total tasks logged: **{total}**",
        f"• ✅ Completed: **{done}** ({rate}%)",
        f"• ⏳ Still pending: **{pending}**",
        f"• 🔴 Critical/Overdue right now: **{critical}**",
        f"• 🟠 High priority remaining: **{high}**",
        f"• 📅 Completed today: **{today_count}**",
    ]

    if hours_invested > 0:
        lines.append(f"• ⏱️ Total time invested: **~{hours_invested}h**")

    # Streak line
    if streak_cur >= 7:
        lines.append(f"• 🔥 **{streak_cur}-day streak!** You're unstoppable.")
    elif streak_cur >= 3:
        lines.append(f"• ⚡ **{streak_cur}-day streak** — keep it alive!")
    elif streak_cur == 1:
        lines.append(f"• ✅ Streak started! Come back tomorrow to keep it going.")

    if streak_long > streak_cur and streak_long >= 3:
        lines.append(f"• 🏆 Longest streak ever: **{streak_long} days**")

    if cat_lines:
        lines.append("\n**📁 Completed by category:**")
        lines.extend(cat_lines)

    # ML predictor accuracy if trained
    if predictor.is_trained:
        estimable = [
            t for t in completed_tasks
            if t.actual_minutes and t.estimated_minutes
        ]
        if estimable:
            mae = sum(abs(t.actual_minutes - t.estimated_minutes) for t in estimable) / len(estimable)
            lines.append(f"\n🤖 ML Predictor: ✅ Active — avg accuracy: **±{mae:.0f}min**")
        else:
            lines.append(f"\n🤖 ML Predictor: {ml_status}")
    else:
        lines.append(f"\n🤖 ML Predictor: {ml_status}")

    lines.append(f"\n{mood}")

    return {
        "reply":        "\n".join(lines),
        "intent":       "task_analytics",
        "action_taken": None,
        "session_update": {},
    }


def handle_get_plan(db: Session) -> dict:
    pending = db.query(Task).filter(Task.status.in_(["pending", "in_progress"])).all()

    if not pending:
        return {
            "reply": (
                "🎉 **No pending tasks!**\n\n"
                "You're completely caught up. Enjoy it — or *'add a task'* to plan ahead."
            ),
            "intent":       "get_plan",
            "action_taken": None,
            "session_update": {},
        }

    today = date.today()

    # Use deadline-aware priority for sorting
    order = {"Overdue": 0, "Critical": 1, "High": 2, "Medium": 3, "Low": 4}
    sorted_tasks = sorted(
        pending,
        key=lambda t: (
            order.get(resolve_priority(t), 99),
            t.due_date or datetime.max,
        ),
    )

    overdue   = [t for t in sorted_tasks if t.due_date and t.due_date.date() < today]
    due_today = [t for t in sorted_tasks if t.due_date and t.due_date.date() == today]
    rest      = [t for t in sorted_tasks if t not in overdue and t not in due_today]

    hour       = datetime.now().hour
    start_hour = max(hour, 8)

    def fmt_time(offset_mins: int) -> str:
        total = start_hour * 60 + offset_mins
        h, m  = divmod(total, 60)
        return f"{h % 24:02d}:{m:02d}"

    lines  = ["📅 **Your Plan for Today**\n"]
    offset = 0

    def add_line(t):
        nonlocal offset
        dur      = t.estimated_minutes or 60
        p_icon   = PRIORITY_EMOJI.get(resolve_priority(t), "⚪")
        slot     = fmt_time(offset)
        end_slot = fmt_time(offset + dur)
        cat      = f" [{t.category}]" if t.category else ""
        overdue_flag = " ⚠️ *overdue*" if t.due_date and t.due_date.date() < today else ""
        lines.append(f"{p_icon} `{slot}–{end_slot}` **#{t.id}** {t.title}{cat}{overdue_flag}")
        offset += dur + 10  # 10min buffer

    if overdue:
        lines.append("🚨 **Overdue — Do First:**")
        for t in overdue:
            add_line(t)
        lines.append("")

    if due_today:
        lines.append("🎯 **Due Today:**")
        for t in due_today:
            add_line(t)
        lines.append("")

    top_rest = rest[:6]
    if top_rest:
        lines.append("📋 **Up Next:**")
        for t in top_rest:
            add_line(t)
        if len(rest) > 6:
            lines.append(f"   *...and {len(rest) - 6} more tasks not shown*")
        lines.append("")

    shown_min  = sum(t.estimated_minutes or 60 for t in overdue + due_today + top_rest)
    total_min  = sum(t.estimated_minutes or 60 for t in sorted_tasks)
    h, m       = divmod(shown_min, 60)
    lines.append(f"⏱️ *Shown: ~{h}h {m}min*")

    if total_min > 480:
        t_h = total_min // 60
        lines.append(
            f"⚠️ *Full backlog = ~{t_h}h. Be realistic — focus Critical/High first.*"
        )

    unset = [t for t in sorted_tasks if t.priority == "Medium" and not t.due_date]
    if unset:
        lines.append(
            f"\n💡 *{len(unset)} tasks have no priority set — say 'review priorities' to sort them.*"
        )

    return {
        "reply":        "\n".join(lines),
        "intent":       "get_plan",
        "action_taken": None,
        "session_update": {},
    }


def handle_predict(message: str, db: Session) -> dict:
    pending = db.query(Task).filter(
        Task.status.in_(["pending", "in_progress"]),
        Task.priority.in_(["Critical", "High", "Overdue"]),
    ).all()

    if not pending:
        pending = db.query(Task).filter(
            Task.status.in_(["pending", "in_progress"])
        ).limit(8).all()

    if not pending:
        return {
            "reply":        "📭 No pending tasks to estimate!",
            "intent":       "task_predict",
            "action_taken": None,
            "session_update": {},
        }

    lines = ["🔮 **Time Estimates for Your Tasks:**\n"]
    total = 0
    for t in pending[:8]:
        est   = t.estimated_minutes or 60
        total += est
        bar   = "█" * max(1, est // 30)
        p     = PRIORITY_EMOJI.get(resolve_priority(t), "⚪")
        lines.append(f"{p} **{t.title}**\n   `{bar}` ~{est} min")

    h, m = divmod(total, 60)
    lines.append(f"\n⏱️ **Total estimated: {h}h {m}min**")
    if predictor.is_trained:
        lines.append("🤖 *Estimates powered by your trained ML model*")
    else:
        lines.append("💡 *Complete more tasks to unlock ML-powered predictions*")

    return {
        "reply":        "\n".join(lines),
        "intent":       "task_predict",
        "action_taken": None,
        "session_update": {},
    }

# ══════════════════════════════════════════════════════════════════════════════
#  DELETE & ARCHIVE HANDLERS
# ══════════════════════════════════════════════════════════════════════════════

def handle_delete_task(message: str, db: Session) -> dict:
    id_match = re.search(r"#?(\d+)", message)
    if not id_match:
        return {
            "reply": (
                "Which task should I delete? Say:\n"
                "delete task #3\n\n"
                "Not sure of the ID? Say show my tasks first."
            ),
            "intent": "delete_task",
            "action_taken": None,
            "session_update": {},
        }

    task_id = int(id_match.group(1))
    task = db.query(Task).filter(Task.id == task_id).first()

    if not task:
        return {
            "reply": f"Task #{task_id} not found. Say show my tasks to see all IDs.",
            "intent": "delete_task",
            "action_taken": None,
            "session_update": {},
        }

    title = task.title
    db.delete(task)
    db.commit()

    return {
        "reply": (
            f"Task #{task_id} {title} deleted.\n\n"
            f"Say show my tasks to see your updated list."
        ),
        "intent": "delete_task",
        "action_taken": {"action": "task_deleted", "task_id": task_id, "task_title": title},
        "session_update": {},
    }


def auto_archive_completed(db: Session) -> int:
    """
    Archive (soft-delete) tasks completed more than 24h ago.
    Call this on app startup or once per session.
    Returns count of archived tasks.
    """
    cutoff = datetime.utcnow() - timedelta(hours=24)
    old_completed = db.query(Task).filter(
        Task.status == "completed",
        Task.completed_at < cutoff,
    ).all()

    count = len(old_completed)
    for task in old_completed:
        task.status = "archived"   # add 'archived' to your status enum

    if count:
        db.commit()
        logger.info(f"[AUTO-ARCHIVE] Archived {count} completed tasks")

    return count

# ══════════════════════════════════════════════════════════════════════════════
#  CONTEXT BUILDER  (for Ollama general_chat only)
# ══════════════════════════════════════════════════════════════════════════════

def build_task_context(db: Session) -> str:
    try:
        total    = db.query(Task).count()
        done     = db.query(Task).filter(Task.status == "completed").count()
        pending  = db.query(Task).filter(Task.status.in_(["pending", "in_progress"])).count()
        critical = db.query(Task).filter(
            Task.priority.in_(["Critical", "Overdue"]), Task.status != "completed"
        ).count()
        return (
            f"User has {total} tasks: {done} completed, {pending} pending, "
            f"{critical} critical/overdue."
        )
    except Exception as e:
        logger.warning(f"Context build failed: {e}")
        return ""


SYSTEM_PROMPT = (
    "You are Cognitive — a warm, smart AI productivity coach. "
    "Keep replies concise and encouraging. Never robotic. "
    "If the user seems stressed or overwhelmed, acknowledge it briefly before helping. "
    "Use emojis sparingly. Never say 'As an AI...'."
)


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN SMART CHAT  ← ROUTING TABLE
# ══════════════════════════════════════════════════════════════════════════════

GREETINGS = frozenset([
    "hi", "hello", "hey", "good morning", "good afternoon",
    "good evening", "sup", "yo", "morning", "howdy", "hiya",
])


def smart_chat(
    message: str,
    user_id: int,
    db: Session,
    session_state: dict,
    conversation_history: list | None = None,
) -> dict:

    # ── Define _clean FIRST before anything else ──────────────────────────
    def _clean(result: dict) -> dict:
        """Strip markdown from any handler reply before returning."""
        if "reply" in result:
            result["reply"] = strip_markdown(result["reply"])
        return result
    # ──────────────────────────────────────────────────────────────────────
 
    if conversation_history is None:
        conversation_history = []

    msg_stripped = message.strip()
    msg_lower    = msg_stripped.lower()

    # ── 1. Wizard intercepts ALL input while active ───────────────────────
    if session_state.get("priority_review_active"):
        return handle_priority_wizard_step(msg_stripped, db, session_state)

    # ── 2. Greeting check — BEFORE intent detection ───────────────────────
    if any(msg_lower == g or msg_lower.startswith(g + " ") for g in GREETINGS):
        return _clean(handle_greeting(db))
 

    # ── 3. Regex intent detection ─────────────────────────────────────────
    intent = detect_intent(msg_lower)
    logger.info(f"[SMART CHAT] Regex intent: {intent} | msg: {msg_stripped[:60]}")

    # ── 4. Fuzzy fallback if regex didn't match ───────────────────────────
    if intent == "general_chat":
        # Fuzzy keyword scoring fallback
        _scores = {
            "create_task":    sum(msg_lower.count(w) for w in ["task", "add", "todo", "need", "create", "remind", "finish"]),
            "complete_task":  sum(msg_lower.count(w) for w in ["done", "complete", "finished", "completed", "mark"]),
            "list_tasks":     sum(msg_lower.count(w) for w in ["list", "show", "pending", "see", "view"]),
            "get_plan":       sum(msg_lower.count(w) for w in ["plan", "day", "schedule", "today", "focus", "should"]),
            "task_analytics": sum(msg_lower.count(w) for w in ["stats", "streak", "progress", "analytics", "how"]),
            "set_priority":   sum(msg_lower.count(w) for w in ["priority", "urgent", "critical", "wizard", "review"]),
            "delete_task":    sum(msg_lower.count(w) for w in ["delete", "remove", "cancel"]),
        }
        _best = max(_scores, key=_scores.get)
        fuzzy_intent = _best if _scores[_best] > 0 else "general_chat"

        if fuzzy_intent:
            logger.info(f"[SMART CHAT] Fuzzy fallback: {fuzzy_intent}")
            intent = fuzzy_intent

    def _clean(result: dict) -> dict:
        """Strip markdown from any handler reply before returning."""
        if "reply" in result:
            result["reply"] = strip_markdown(result["reply"])
        return result

    # ── 5. Route to direct handlers ───────────────────────────────────────
    if intent == "help":
        return _clean(handle_help())

    if intent == "list_tasks":
        return _clean(handle_list_tasks(msg_stripped, db))

    if intent == "create_task":
        return _clean(handle_create_task(msg_stripped, db))

    if intent == "complete_task":
        return _clean(handle_complete_task(msg_stripped, db))

    if intent == "bulk_set_priority":
        return _clean(handle_bulk_set_priority(msg_stripped, db))

    if intent == "set_priority":
        return _clean(handle_set_priority(msg_stripped, db))

    if intent == "review_priorities":
        return _clean(handle_start_priority_wizard(db))

    if intent == "task_analytics":
        return _clean(handle_analytics(db))

    if intent == "get_plan":
        return _clean(handle_get_plan(db))

    if intent == "task_predict":
        return _clean(handle_predict(msg_stripped, db))

    if intent == "delete_task":
        return _clean(handle_delete_task(msg_stripped, db))

    # ── 6. General chat → Ollama ──────────────────────────────────────────
    task_summary = build_task_context(db)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": f"Context: {task_summary}"},
        *conversation_history[-6:],
        {"role": "user", "content": msg_stripped},
    ]

    try:
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(
                f"{OLLAMA_BASE_URL}/api/chat",
                json={
                    "model":   OLLAMA_MODEL,
                    "messages": messages,
                    "stream":  False,
                    "options": {"temperature": 0.7, "top_p": 0.9, "num_predict": 256},
                },
            )
            resp.raise_for_status()
            reply = resp.json()["message"]["content"].strip()

    except httpx.ConnectError:
        reply = "⚠️ Ollama is offline. Task features still work — just ask about your tasks!"
    except Exception as e:
        logger.error(f"Ollama error: {e}")
        reply = "💬 I'm here! Ask me to show your tasks, add one, or plan your day."

    return {
        "reply":             strip_markdown(reply),
        "intent":            intent,
        "action_taken":      None,
        "session_update":    {},
        "task_context_used": False,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  BACKWARDS COMPATIBILITY
# ══════════════════════════════════════════════════════════════════════════════

def query_with_memory(db: Session, user_query: str) -> str:
    return smart_chat(
        message=user_query, user_id=0, db=db, session_state={}
    )["reply"]


def generate_daily_plan(db: Session) -> str:
    return smart_chat(
        message="plan my day",
        user_id=0, db=db, session_state={}
    )["reply"]