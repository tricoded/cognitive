import streamlit as st
from utils.api import get_memories, clear_memory

st.set_page_config(
    page_title="Memory — Cognitive",
    page_icon="🗃️",
    layout="wide",
)

st.title("🗃️ Memory Viewer")
st.caption("Browse what your cognitive assistant remembers.")

# ── Session Selector ─────────────────────────────────────
session_id = st.text_input("Session ID to inspect", value="default")

col1, col2 = st.columns([1, 5])
with col1:
    if st.button("🔄 Load Memories", use_container_width=True):
        st.session_state.memories = get_memories(session_id)

with col2:
    if st.button("🗑️ Clear This Session's Memory", use_container_width=True):
        clear_memory(session_id)
        st.session_state.memories = []
        st.success(f"Memory cleared for session: `{session_id}`")

st.divider()

# ── Memory Display ───────────────────────────────────────
memories = st.session_state.get("memories", [])

if not memories:
    st.info("No memories loaded yet. Enter a session ID and click **Load Memories**.")
else:
    st.success(f"Found **{len(memories)}** memory entries for session `{session_id}`")
    for i, mem in enumerate(memories):
        with st.expander(f"🧩 Memory #{i + 1}", expanded=False):
            st.json(mem)
