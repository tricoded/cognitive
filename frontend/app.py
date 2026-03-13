import streamlit as st
from utils.api import health_check

# ── Page Config ──────────────────────────────────────────
st.set_page_config(
    page_title="Cognitive Assistant",
    page_icon="🧠",
    layout="centered",
    initial_sidebar_state="expanded",
)

# ── Header ───────────────────────────────────────────────
st.title("🧠 Cognitive Assistant")
st.caption("Your local AI-powered memory assistant — running 100% on your machine.")

st.divider()

# ── Backend Status ───────────────────────────────────────
st.subheader("🔌 Backend Status")

with st.spinner("Checking connection to backend..."):
    status = health_check()

if "error" not in str(status.get("status", "")):
    st.success("FastAPI backend is online and healthy.")
else:
    st.error("Cannot reach the FastAPI backend. Is uvicorn running?")
    st.code("uvicorn app.main:app --reload", language="bash")

st.divider()

# ── Navigation Guide ─────────────────────────────────────
st.subheader("📌 Navigation")

col1, col2, col3 = st.columns(3)

with col1:
    st.info("💬 **Chat**\nTalk to your cognitive assistant")

with col2:
    st.info("🗃️ **Memory**\nBrowse stored memories & context")

with col3:
    st.info("⚙️ **Settings**\nConfigure model & session options")

st.divider()
st.caption("Built with FastAPI + Ollama + Streamlit · Running locally · No data leaves your machine 🔒")
