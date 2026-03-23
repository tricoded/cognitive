# frontend/pages/01_Chat.py
# Task-Aware AI Chat Interface — Cognitive Assistant

import streamlit as st
import requests
from datetime import datetime

API_BASE = "http://localhost:8000"

st.set_page_config(
    page_title="Cognitive · Chat",
    page_icon="💬",
    layout="wide"
)

# ── Custom CSS ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .user-bubble {
        background: #1e40af;
        color: white;
        padding: 0.85rem 1.2rem;
        border-radius: 18px 18px 4px 18px;
        margin: 0.4rem 0 0.4rem 15%;
        line-height: 1.6;
        word-wrap: break-word;
    }
    .ai-bubble {
        background: #1f2937;
        color: #f3f4f6;
        border: 1px solid #374151;
        padding: 0.85rem 1.2rem;
        border-radius: 18px 18px 18px 4px;
        margin: 0.4rem 15% 0.4rem 0;
        line-height: 1.6;
        word-wrap: break-word;
    }
    .badge-intent {
        font-size: 0.68rem;
        padding: 2px 8px;
        border-radius: 20px;
        background: #374151;
        color: #9ca3af;
        display: inline-block;
        margin-bottom: 6px;
    }
    .badge-action {
        font-size: 0.7rem;
        padding: 2px 10px;
        border-radius: 20px;
        background: #064e3b;
        color: #6ee7b7;
        display: inline-block;
        margin-bottom: 6px;
    }
    .timestamp {
        font-size: 0.65rem;
        color: #6b7280;
        margin-top: 4px;
    }
    #MainMenu, footer { visibility: hidden; }

    /* Push chat_input to bottom */
    .stChatInput {
        position: fixed !important;
        bottom: 1rem;
        left: 0;
        right: 0;
        padding: 0 2rem;
        z-index: 999;
        background: transparent;
    }
    /* Add bottom padding so messages don't hide behind fixed input */
    .main .block-container {
        padding-bottom: 6rem !important;
    }
</style>
""", unsafe_allow_html=True)

# ── Session State ──────────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []
if "conv_history" not in st.session_state:
    st.session_state.conv_history = []

# ── Header ─────────────────────────────────────────────────────────────────
col_title, col_clear = st.columns([5, 1])
with col_title:
    st.title("💬 Cognitive AI Chat")
    st.caption("Talk to me like ChatGPT — but I know your tasks, your patterns, and your goals.")
with col_clear:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🗑️ Clear", use_container_width=True):
        st.session_state.messages = []
        st.session_state.conv_history = []
        st.rerun()

# ── Quick Actions ──────────────────────────────────────────────────────────
with st.expander("⚡ Quick Actions", expanded=True):
    q1, q2, q3, q4, q5 = st.columns(5)
    quick_map = {
        q1: ("📋 My Tasks",      "Show me all my pending tasks"),
        q2: ("📅 Plan My Day",   "What should I work on today and in what order?"),
        q3: ("📊 My Stats",      "How productive have I been? Show me my stats."),
        q4: ("⚡ Quick Win",     "What's a quick task I can knock out in under 30 minutes?"),
        q5: ("🔮 Time Estimate", "How long will my high priority tasks actually take?"),
    }
    triggered = None
    for col, (label, prompt) in quick_map.items():
        with col:
            if st.button(label, use_container_width=True):
                triggered = prompt

st.divider()

# ── Chat History ───────────────────────────────────────────────────────────
chat_area = st.container()

with chat_area:
    if not st.session_state.messages:
        st.markdown("""
        <div style="text-align:center; padding: 2.5rem 1rem; color:#6b7280;">
            <div style="font-size:3rem">🧠</div>
            <h3 style="color:#9ca3af;">Hey, I'm Cognitive!</h3>
            <p>I'm your personal AI assistant — I know your tasks, your time patterns, and your productivity stats.</p>
            <p style="font-size:0.9rem; margin-top:1rem;">
                Try: <em>"Add a high priority task to fix the login bug, 2 hours"</em><br>
                Or: <em>"What should I work on right now?"</em><br>
                Or just: <em>"Hey, how's it going?"</em>
            </p>
        </div>
        """, unsafe_allow_html=True)
    else:
        for msg in st.session_state.messages:
            ts = msg.get("time", "")
            if msg["role"] == "user":
                st.markdown(f"""
                <div class="user-bubble">
                    {msg["content"]}
                    <div class="timestamp" style="text-align:right">{ts}</div>
                </div>
                """, unsafe_allow_html=True)
            else:
                intent     = msg.get("intent", "")
                action     = msg.get("action_taken")
                badge_html = ""

                if intent and intent != "general_chat":
                    label = intent.replace("_", " ").title()
                    badge_html += f'<span class="badge-intent">🎯 {label}</span> '

                if action and action.get("action") == "task_created":
                    tid = action.get("task_id", "?")
                    badge_html += f'<span class="badge-action">✅ Task #{tid} created in DB</span>'

                if badge_html:
                    badge_html += "<br>"

                content_html = msg["content"].replace("\n", "<br>")
                st.markdown(f"""
                <div class="ai-bubble">
                    {badge_html}{content_html}
                    <div class="timestamp">{ts}</div>
                </div>
                """, unsafe_allow_html=True)

# ── Send Logic ─────────────────────────────────────────────────────────────
def send_message(text: str):
    if not text.strip():
        return

    now = datetime.now().strftime("%H:%M")

    # Add user message immediately
    st.session_state.messages.append({
        "role": "user", "content": text, "time": now
    })
    st.session_state.conv_history.append({
        "role": "user", "content": text
    })

    with st.spinner("Thinking..."):
        try:
            resp = requests.post(
                f"{API_BASE}/ai/chat",
                json={
                    "message": text,
                    "conversation_history": st.session_state.conv_history[-6:]
                },
                timeout=180  # ✅ Give Ollama/Mistral plenty of time
            )
            resp.raise_for_status()
            data   = resp.json()
            reply  = data.get("reply", "Sorry, something went wrong.")
            intent = data.get("intent", "general_chat")
            action = data.get("action_taken")

        except requests.exceptions.Timeout:
            reply  = "⏱️ Ollama took too long to respond. Try a shorter message, or check if Mistral is fully loaded."
            intent = "error"
            action = None
        except requests.exceptions.ConnectionError:
            reply  = "⚠️ Can't reach the backend. Make sure `uvicorn app.main:app --reload` is running."
            intent = "error"
            action = None
        except Exception as e:
            reply  = f"⚠️ Error: {str(e)}"
            intent = "error"
            action = None

    # Add AI response
    st.session_state.messages.append({
        "role":         "assistant",
        "content":      reply,
        "intent":       intent,
        "action_taken": action,
        "time":         datetime.now().strftime("%H:%M"),
    })
    st.session_state.conv_history.append({
        "role": "assistant", "content": reply
    })
    st.rerun()


# ── Trigger from Quick Action buttons ─────────────────────────────────────
if triggered:
    send_message(triggered)

# ── ✅ Chat Input — Enter works + auto-clears (replaces text_input + button)
user_input = st.chat_input("Ask about your tasks, or just chat...")  # ← THE FIX

if user_input:
    send_message(user_input)

# ── Sidebar ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 📊 Live Snapshot")
    try:
        r = requests.get(f"{API_BASE}/tasks", timeout=5)
        if r.ok:
            tasks     = r.json()
            pending   = [t for t in tasks if t["status"] in ("pending", "in_progress")]
            completed = [t for t in tasks if t["status"] == "completed"]
            total     = len(tasks)

            st.metric("Pending",   len(pending))
            st.metric("Completed", len(completed))
            rate = round(len(completed) / total * 100, 1) if total else 0
            st.metric("Done Rate", f"{rate}%")

            if pending:
                st.markdown("---")
                st.markdown("**🔥 Top 3 by Priority:**")
                order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
                top3  = sorted(pending, key=lambda t: order.get(t["priority"], 99))[:3]
                for t in top3:
                    pri_emoji = {"Critical": "🔴", "High": "🟠", "Medium": "🟡", "Low": "🟢"}.get(t["priority"], "⚪")
                    title_short = t["title"][:30] + ("..." if len(t["title"]) > 30 else "")
                    st.markdown(f"{pri_emoji} {title_short}")
    except Exception:
        st.info("Backend offline")

    st.markdown("---")
    st.markdown("**💡 What I can do:**")
    st.markdown("""
    - Create & manage tasks by talking
    - Plan your day intelligently  
    - Predict how long tasks will take
    - Show your productivity stats
    - Just... chat 😊
    """)
    st.markdown("---")
    st.caption(f"🕐 {datetime.now().strftime('%H:%M')} · Cognitive v1.0")