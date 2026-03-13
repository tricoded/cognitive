import streamlit as st
from utils.api import send_message, clear_memory

st.set_page_config(
    page_title="Chat — Cognitive",
    page_icon="💬",
    layout="centered",
)

st.title("💬 Chat")
st.caption("Talk to your local cognitive assistant.")

# ── Session State Init ───────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []

if "session_id" not in st.session_state:
    st.session_state.session_id = "default"

# ── Sidebar Controls ─────────────────────────────────────
with st.sidebar:
    st.header("🛠️ Chat Controls")
    session_id = st.text_input("Session ID", value=st.session_state.session_id)
    st.session_state.session_id = session_id

    if st.button("🗑️ Clear Chat History", use_container_width=True):
        st.session_state.messages = []
        clear_memory(session_id)
        st.success("Chat cleared!")
        st.rerun()

# ── Chat History Display ─────────────────────────────────
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ── Chat Input ───────────────────────────────────────────
if prompt := st.chat_input("Ask your cognitive assistant..."):

    # Add user message
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Get assistant response
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            result = send_message(prompt, st.session_state.session_id)
            reply = result.get("response", "⚠️ No response received.")
        st.markdown(reply)

    st.session_state.messages.append({"role": "assistant", "content": reply})
