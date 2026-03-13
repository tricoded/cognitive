import streamlit as st
import httpx
from utils.api import BASE_URL
from datetime import datetime, date

st.set_page_config(
    page_title="Tasks — Cognitive",
    page_icon="📝",
    layout="wide",
)

st.title("📝 Task Manager")
st.caption("Organize your tasks and let your assistant help prioritize.")

# ── Add New Task ─────────────────────────────────────────
st.header("Add New Task")

with st.form("new_task", clear_on_submit=True):
    task_title = st.text_input("Task Title*", placeholder="e.g., Finish project proposal")
    
    col1, col2 = st.columns(2)
    with col1:
        priority = st.selectbox("Priority", [
            "Critical", "High", "Medium", "Low"
        ])
        category = st.selectbox("Category", [
            "Work", "Personal", "Learning", "Health", "Other"
        ])
    
    with col2:
        due_date = st.date_input("Due Date", value=date.today())
        estimated_time = st.number_input(
            "Estimated Time (minutes)",
            min_value=5,
            max_value=480,
            value=60,
            step=15
        )
    
    notes = st.text_area("Notes (optional)", placeholder="Any additional context...")
    
    submitted = st.form_submit_button("Add Task", type="primary", use_container_width=True)
    
    if submitted:
        if not task_title:
            st.error("Please enter a task title")
        else:
            task_data = {
                "title": task_title,
                "priority": priority,
                "category": category,
                "due_date": due_date.isoformat(),
                "estimated_minutes": estimated_time,
                "notes": notes,
                "status": "pending"
            }
            
            try:
                response = httpx.post(
                    f"{BASE_URL}/tasks",
                    json=task_data,
                    timeout=30
                )
                
                if response.status_code == 200:
                    st.success("Task added successfully!")
                    st.rerun()
                else:
                    st.error(f"Error: {response.text}")
            except Exception as e:
                st.error(f"Connection error: {str(e)}")

st.divider()

# ── View Tasks ───────────────────────────────────────────
st.header("Your Tasks")

# Filter options
col1, col2, col3 = st.columns(3)
with col1:
    filter_status = st.selectbox("Status", ["All", "Pending", "Completed"])
with col2:
    filter_priority = st.selectbox("Priority", ["All", "Critical", "High", "Medium", "Low"])
with col3:
    if st.button("Refresh Tasks", use_container_width=True):
        st.rerun()

try:
    response = httpx.get(f"{BASE_URL}/tasks", timeout=30)
    
    if response.status_code == 200:
        tasks = response.json()
        
        # Apply filters
        if filter_status != "All":
            tasks = [t for t in tasks if t["status"] == filter_status.lower()]
        if filter_priority != "All":
            tasks = [t for t in tasks if t["priority"] == filter_priority]
        
        if not tasks:
            st.info("No tasks found. Add one above!")
        else:
            st.success(f"Found **{len(tasks)}** task(s)")
            
            # Group by status
            pending_tasks = [t for t in tasks if t["status"] == "pending"]
            completed_tasks = [t for t in tasks if t["status"] == "completed"]
            
            # Display pending tasks
            if pending_tasks:
                st.subheader(f"⏳ Pending ({len(pending_tasks)})")
                for task in pending_tasks:
                    priority_emoji = {
                        "Critical": "🔴",
                        "High": "🟠",
                        "Medium": "🟡",
                        "Low": "🟢"
                    }.get(task["priority"], "⚪")
                    
                    with st.expander(f"{priority_emoji} {task['title']}"):
                        col_a, col_b = st.columns(2)
                        with col_a:
                            st.write(f"**Priority:** {task['priority']}")
                            st.write(f"**Category:** {task['category']}")
                        with col_b:
                            st.write(f"**Due:** {task['due_date']}")
                            st.write(f"**Time:** {task['estimated_minutes']} min")
                        
                        if task.get('notes'):
                            st.write(f"**Notes:** {task['notes']}")
                        
                        col_x, col_y = st.columns(2)
                        with col_x:
                            if st.button("Mark Complete", key=f"done_{task['id']}", use_container_width=True):
                                try:
                                    httpx.patch(
                                        f"{BASE_URL}/tasks/{task['id']}/complete",
                                        timeout=30
                                    )
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error: {str(e)}")
                        with col_y:
                            if st.button("🗑️ Delete", key=f"del_{task['id']}", use_container_width=True):
                                try:
                                    httpx.delete(
                                        f"{BASE_URL}/tasks/{task['id']}",
                                        timeout=30
                                    )
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error: {str(e)}")
            
            # Display completed tasks
            if completed_tasks:
                st.subheader(f"Completed ({len(completed_tasks)})")
                for task in completed_tasks:
                    with st.expander(f"{task['title']}"):
                        st.write(f"**Category:** {task['category']}")
                        st.write(f"**Completed on:** {task['due_date']}")
                        
                        if st.button("🗑️ Delete", key=f"del_{task['id']}", use_container_width=True):
                            try:
                                httpx.delete(
                                    f"{BASE_URL}/tasks/{task['id']}",
                                    timeout=30
                                )
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error: {str(e)}")
    else:
        st.error(f"⚠️ Could not load tasks: {response.status_code}")
        
except Exception as e:
    st.error(f"Connection error: {str(e)}")
    st.info("💡 Make sure the backend is running at http://localhost:8000")
