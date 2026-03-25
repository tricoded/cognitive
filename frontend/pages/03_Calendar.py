# cognitive/app/frontend/03_Calendar.py
import streamlit as st
import requests
import json
import calendar
from datetime import date, timedelta
from collections import defaultdict
from pathlib import Path

API      = "http://localhost:8000"
CSS_PATH = Path(__file__).parent.parent.parent / "assets" / "style.css"
PFILE    = Path(__file__).parent.parent.parent / "user_profile.json"

st.set_page_config(page_title="Calendar", layout="wide", page_icon="📅")

# ── Inject CSS ────────────────────────────────────────────────────────────────
def inject_css():
    try:
        with open(CSS_PATH, encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    except FileNotFoundError:
        st.warning(f"CSS not found: {CSS_PATH}")
inject_css()

# ── Profile ───────────────────────────────────────────────────────────────────
def load_profile():
    if PFILE.exists():
        with open(PFILE) as f:
            return json.load(f)
    return {"daily_goal": 5, "name": ""}

DAILY_GOAL = load_profile().get("daily_goal", 5)

# ── Fetch completed tasks ──────────────────────────────────────────────────────
@st.cache_data(ttl=30)
def fetch_completed():
    try:
        r = requests.get(f"{API}/tasks", timeout=5)
        data = r.json() if r.status_code == 200 else []
        return [t for t in data if t.get("status") == "completed"]
    except Exception:
        return []

completed     = fetch_completed()
tasks_by_date = defaultdict(list)
for t in completed:
    raw = t.get("completed_at") or t.get("created_at", "")
    if raw:
        tasks_by_date[raw[:10]].append(t)

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("## 📅 Activity Calendar")
st.caption(f"Daily goal: **{DAILY_GOAL} tasks**. Browse days to see what you completed.")

# ── Session state ──────────────────────────────────────────────────────────────
today = date.today()
if "cal_year"  not in st.session_state: st.session_state.cal_year  = today.year
if "cal_month" not in st.session_state: st.session_state.cal_month = today.month

# ── Month nav ──────────────────────────────────────────────────────────────────
nav_l, nav_c, nav_r = st.columns([1, 5, 1])
with nav_l:
    if st.button("← Prev", use_container_width=True):
        if st.session_state.cal_month == 1:
            st.session_state.cal_month = 12
            st.session_state.cal_year -= 1
        else:
            st.session_state.cal_month -= 1
        st.rerun()
with nav_c:
    st.markdown(
        f"<h3 style='text-align:center;margin:0;color:var(--text,#1a1a2e)'>"
        f"{calendar.month_name[st.session_state.cal_month]} "
        f"{st.session_state.cal_year}</h3>",
        unsafe_allow_html=True,
    )
with nav_r:
    if st.button("Next →", use_container_width=True):
        if st.session_state.cal_month == 12:
            st.session_state.cal_month = 1
            st.session_state.cal_year += 1
        else:
            st.session_state.cal_month += 1
        st.rerun()

# ── Streak set ────────────────────────────────────────────────────────────────
year  = st.session_state.cal_year
month = st.session_state.cal_month

streak_days: set[str] = set()
if tasks_by_date:
    sd = today
    for _ in range(365):
        ds = sd.strftime("%Y-%m-%d")
        if ds in tasks_by_date:
            streak_days.add(ds)
            sd -= timedelta(days=1)
        else:
            if sd != today: break
            sd -= timedelta(days=1)

# ── Build calendar using Streamlit columns ───────────────────────────────
DAY_HEADERS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

C = {
    "bg_surface":   "#ffffff",
    "border":       "#e0dfd8",
    "text":         "#1a1a2e",
    "muted":        "#7a788a",
    "accent":       "#5b52e8",
    "accent_lt":    "rgba(91,82,232,0.12)",
    "accent_ring":  "rgba(91,82,232,0.30)",
    "success_lt":   "rgba(31,158,110,0.14)",
    "success_bdr":  "rgba(31,158,110,0.35)",
    "gold_lt":      "rgba(255,215,0,0.12)",
    "gold_bdr":     "rgba(255,215,0,0.35)",
}

hdr_cols = st.columns(7)
for i, h in enumerate(DAY_HEADERS):
    with hdr_cols[i]:
        st.markdown(
            f"<div style='text-align:center;font-size:0.75rem;font-weight:700;color:{C['muted']};padding:6px 0'>{h}</div>",
            unsafe_allow_html=True,
        )

for week in calendar.monthcalendar(year, month):
    cols = st.columns(7)
    for i, day_num in enumerate(week):
        with cols[i]:
            if day_num == 0:
                st.markdown("<div style='height:64px;'></div>", unsafe_allow_html=True)
                continue

            d_str = f"{year}-{month:02d}-{day_num:02d}"
            d_obj = date(year, month, day_num)
            count = len(tasks_by_date.get(d_str, []))
            is_today = (d_obj == today)
            in_streak = d_str in streak_days
            beat_goal = count >= DAILY_GOAL and count > 0

            if beat_goal:
                bg = C["gold_lt"]
                bdr = C["gold_bdr"]
                emoji = "🏆"
            elif in_streak and count > 0:
                bg = C["success_lt"]
                bdr = C["success_bdr"]
                emoji = "🔥"
            elif is_today:
                bg = C["accent_lt"]
                bdr = C["accent"]
                emoji = ""
            else:
                bg = C["bg_surface"]
                bdr = C["border"]
                emoji = ""

            ring = f"box-shadow:0 0 0 2px {C['accent_ring']};" if is_today else ""
            num_color = C["accent"] if is_today else C["text"]

            if emoji:
                sub_html = f"<div style='font-size:0.85rem;margin-top:2px'>{emoji}</div>"
            elif count > 0:
                sub_html = (
                    f"<div style='width:6px;height:6px;border-radius:50%;"
                    f"background:{C['accent']};margin:4px auto 0'></div>"
                )
            else:
                sub_html = ""

            cell_html = (
                f"<div title='{count} task{'s' if count != 1 else ''} on {d_str}' "
                f"style='height:64px;"
                f"border-radius:10px;"
                f"border:1px solid {bdr};"
                f"background:{bg};"
                f"display:flex;"
                f"flex-direction:column;"
                f"align-items:center;"
                f"justify-content:center;"
                f"margin-bottom:6px;"
                f"{ring}'>"
                f"<div style='font-size:0.82rem;font-weight:700;color:{num_color};'>"
                f"{day_num}"
                f"</div>"
                f"{sub_html}"
                f"</div>"
            )
            st.markdown(cell_html, unsafe_allow_html=True)
            
# ── Legend ────────────────────────────────────────────────────────────────────
st.markdown(
    f"<div style='display:flex;gap:18px;margin-top:14px;font-size:0.78rem;"
    f"color:{C['muted']};flex-wrap:wrap;align-items:center'>"
    f"<span>🏆 Beat daily goal</span>"
    f"<span>🔥 On streak</span>"
    f"<span style='display:flex;align-items:center;gap:5px'>"
    f"<span style='width:7px;height:7px;border-radius:50%;"
    f"background:{C['accent']};display:inline-block'></span> Tasks done</span>"
    f"<span style='border:1.5px solid {C['accent']};border-radius:6px;"
    f"padding:1px 8px;color:{C['accent']}'>Today</span>"
    f"</div>",
    unsafe_allow_html=True,
)

st.divider()

# ── Browse a Day ──────────────────────────────────────────────────────────────
st.markdown("#### 📋 Browse a Day")
st.caption("Select a date to see tasks completed that day.")
selected = st.date_input("Pick date", value=today, label_visibility="collapsed")

if selected:
    sel_str   = selected.strftime("%Y-%m-%d")
    day_tasks = tasks_by_date.get(sel_str, [])

    if not day_tasks:
        st.markdown(
            f"<div style='background:{C['bg_surface']};border:1px solid {C['border']};"
            f"border-radius:12px;padding:32px;text-align:center;"
            f"color:{C['muted']};margin-top:8px'>"
            f"No tasks completed on <b>{sel_str}</b>.</div>",
            unsafe_allow_html=True,
        )
    else:
        goal_met = len(day_tasks) >= DAILY_GOAL
        banner   = "🏆 Goal smashed!" if len(day_tasks) > DAILY_GOAL else "✅ Goal met!" if goal_met else ""

        st.markdown(
            f"<div style='font-size:0.9rem;color:{C['muted']};margin:8px 0 12px'>"
            f"<b style='color:{C['text']}'>{len(day_tasks)} tasks</b> on "
            f"<b style='color:{C['accent']}'>{selected.strftime('%B %d, %Y')}</b>"
            + (f" &nbsp;<span style='color:#d4a017'>{banner}</span>" if banner else "")
            + "</div>",
            unsafe_allow_html=True,
        )

        PRI_COL = {
            "Critical": "#e8394a", "High": "#d97706",
            "Medium": "#5b52e8",  "Low":  "#1f9e6e",
        }
        for t in day_tasks:
            pri   = t.get("priority", "Medium")
            col   = PRI_COL.get(pri, "#5b52e8")
            cat   = t.get("category", "")
            est   = t.get("estimated_minutes", 0)
            act   = t.get("actual_minutes",    0)
            title = str(t.get("title", ""))

            tnote = ""
            if est and act:
                diff  = act - est
                tnote = (
                    f"⏱️ {act}min ({'+'if diff>0 else ''}{diff}min vs est.)"
                    if abs(diff) > 5 else f"⏱️ {act}min"
                )
            elif est:
                tnote = f"⏱️ ~{est}min est."

            st.markdown(f"""
            <div style='background:{C["bg_surface"]};border:1px solid {C["border"]};
                        border-left:3px solid {col};border-radius:12px;
                        padding:14px 18px;margin-bottom:8px;
                        box-shadow:0 1px 4px rgba(0,0,0,.07)'>
                <div style='font-weight:600;color:{C["text"]}'>
                    ✅ <span style='color:{C["muted"]};font-size:0.8rem'>#{t["id"]}</span>
                    &nbsp; {title}
                </div>
                <div style='font-size:0.78rem;color:{C["muted"]};margin-top:5px;
                            display:flex;gap:10px;flex-wrap:wrap;align-items:center'>
                    <span style='background:{col}20;color:{col};border:1px solid {col}50;
                                 padding:1px 9px;border-radius:20px;font-size:0.7rem;
                                 font-weight:600'>{pri}</span>
                    {'<span>📁 ' + cat + '</span>' if cat else ''}
                    {'<span>' + tnote + '</span>' if tnote else ''}
                </div>
            </div>
            """, unsafe_allow_html=True)

# ── Monthly summary ───────────────────────────────────────────────────────────
st.divider()
st.markdown("#### 📊 This Month At a Glance")
prefix         = f"{year}-{month:02d}"
m_total        = sum(len(v) for k,v in tasks_by_date.items() if k.startswith(prefix))
m_active       = sum(1     for k   in tasks_by_date          if k.startswith(prefix))
m_beat         = sum(1     for k,v in tasks_by_date.items()
                     if k.startswith(prefix) and len(v) >= DAILY_GOAL)
m_streak       = len(streak_days)

m1, m2, m3, m4 = st.columns(4)
m1.metric("Tasks This Month",  m_total)
m2.metric("Active Days",       m_active)
m3.metric("Days Beat Goal 🏆", m_beat)
m4.metric("Current Streak 🔥", f"{m_streak}d")