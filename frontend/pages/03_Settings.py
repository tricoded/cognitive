import streamlit as st
import httpx
from utils.api import BASE_URL

st.set_page_config(
    page_title="Settings — Cognitive",
    page_icon="⚙️",
    layout="centered",
)

st.title("⚙️ Settings")
st.caption("Configure your cognitive assistant preferences.")

st.divider()

# ── User Profile ─────────────────────────────────────────
st.subheader("👤 Your Profile")

col1, col2 = st.columns(2)
with col1:
    name = st.text_input("Name", value="Patricia")
    timezone = st.selectbox("Timezone", [
        "America/New_York", "America/Chicago", 
        "America/Denver", "America/Los_Angeles",
        "Europe/London", "Asia/Tokyo"
    ])

with col2:
    work_start = st.time_input("Work Start Time", value=None)
    work_end = st.time_input("Work End Time", value=None)

st.divider()

# ── Energy Patterns ──────────────────────────────────────
st.subheader("⚡ Energy Patterns")

st.caption("When are you most productive?")
peak_hours = st.multiselect(
    "Peak Energy Hours",
    options=list(range(24)),
    default=[9, 10, 11],
    format_func=lambda x: f"{x:02d}:00"
)

st.caption("When do you typically crash?")
low_hours = st.multiselect(
    "Low Energy Hours", 
    options=list(range(24)),
    default=[13, 14, 15],
    format_func=lambda x: f"{x:02d}:00"
)

st.divider()

# ── Work Preferences ─────────────────────────────────────
st.subheader("💼 Work Style")

focus_duration = st.slider(
    "Deep Focus Session Length (minutes)",
    min_value=15,
    max_value=120,
    value=90,
    step=15
)

break_duration = st.slider(
    "Preferred Break Length (minutes)",
    min_value=5,
    max_value=30,
    value=15,
    step=5
)

priorities = st.multiselect(
    "Current Priorities",
    ["Health", "Career", "Learning", "Relationships", "Finance", "Hobbies"],
    default=["Career", "Health"]
)

st.divider()

# ── Model Settings ───────────────────────────────────────
st.subheader("🤖 Model Configuration")

model = st.selectbox(
    "Ollama Model",
    ["llama3", "mistral", "phi3", "gemma2", "llama3.2"],
    index=4,  # llama3.2 is default
)

temperature = st.slider("Temperature", min_value=0.0, max_value=2.0, value=0.7, step=0.1)
max_tokens = st.number_input("Max Tokens", min_value=64, max_value=4096, value=512, step=64)

st.divider()

# ── Backend Settings ─────────────────────────────────────
st.subheader("🔌 Backend")
backend_url = st.text_input("FastAPI Backend URL", value="http://localhost:8000")
ollama_url = st.text_input("Ollama Host URL", value="http://localhost:11434")

st.divider()

# ── Save Button ──────────────────────────────────────────
if st.button("💾 Save All Settings", use_container_width=True):
    # Save profile to backend
    profile_data = {
        "name": name,
        "timezone": timezone,
        "work_start": str(work_start) if work_start else "09:00:00",
        "work_end": str(work_end) if work_end else "17:00:00",
        "peak_hours": peak_hours,
        "low_hours": low_hours,
        "focus_duration": focus_duration,
        "break_duration": break_duration,
        "priorities": priorities
    }
    
    # Save model settings to session state
    st.session_state.settings = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "backend_url": backend_url,
        "ollama_url": ollama_url,
    }
    
    try:
        response = httpx.post(
            f"{backend_url}/profile",
            json=profile_data,
            timeout=30
        )
        
        if response.status_code == 200:
            st.success("Profile and settings saved successfully!")
        else:
            st.error(f"Backend error: {response.text}")
    except Exception as e:
        st.error(f"Connection error: {str(e)}")
        st.info("💡 Model settings saved locally. Profile will sync when backend is available.")

st.caption("⚠️ Model settings are session-only. Profile is stored in backend memory.")
