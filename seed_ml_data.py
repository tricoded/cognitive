# seed_ml_data.py — Uses raw sqlite3, hardcoded correct path
import sqlite3
import os
from datetime import datetime, timedelta

# ── Hardcoded to the correct live database ───────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "data", "cognitive.db")

if not os.path.exists(DB_PATH):
    print(f"❌ Database not found at: {DB_PATH}")
    exit(1)

print(f"✅ Found database at: {DB_PATH}")

# ── Connect ──────────────────────────────────────────────────────────────────
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# ── Peek at table structure ──────────────────────────────────────────────────
cursor.execute("PRAGMA table_info(tasks)")
columns = [row[1] for row in cursor.fetchall()]
print(f"📋 Tasks table columns: {columns}\n")

# ── Seed data ────────────────────────────────────────────────────────────────
seed_tasks = [
    # (title, priority, category, estimated_min, actual_min, energy_start, energy_end, distractions)
    ("Write project proposal",      "High",     "Work",        60,  72,  8, 7, 1),
    ("Code review session",         "Medium",   "Work",        45,  38,  6, 5, 2),
    ("Fix authentication bug",      "High",     "Development", 90,  140, 7, 6, 0),
    ("Design database schema",      "High",     "Development", 120, 95,  9, 8, 1),
    ("Write unit tests",            "Medium",   "Work",        30,  55,  5, 4, 3),
    ("Deploy to staging",           "Critical", "Work",        45,  60,  8, 7, 0),
    ("Update documentation",        "Low",      "Work",        20,  25,  4, 3, 2),
    ("Team standup prep",           "Medium",   "Work",        15,  10,  6, 6, 1),
    ("Refactor payment module",     "High",     "Development", 90,  130, 7, 5, 0),
    ("Research ML frameworks",      "Medium",   "Learning",    60,  80,  7, 6, 1),
    ("Write API endpoints",         "High",     "Development", 75,  85,  8, 7, 2),
    ("Performance optimization",    "Medium",   "Work",        120, 150, 5, 4, 3),
    ("Security audit review",       "High",     "Work",        60,  70,  6, 5, 0),
    ("Client presentation prep",    "Critical", "Work",        90,  75,  9, 8, 0),
    ("Sprint planning session",     "Medium",   "Work",        60,  65,  7, 6, 1),
]

print("🌱 Seeding ML training data...")
print("-" * 60)

updated = 0
created = 0
now = datetime.now()

for title, priority, category, est, actual, energy_s, energy_e, distractions in seed_tasks:
    started_at   = (now - timedelta(minutes=actual + 10)).strftime("%Y-%m-%d %H:%M:%S")
    completed_at = (now - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("SELECT id FROM tasks WHERE title = ?", (title,))
    row = cursor.fetchone()

    if row:
        task_id = row[0]
        cursor.execute("""
            UPDATE tasks SET
                actual_minutes     = ?,
                energy_level_start = ?,
                energy_level_end   = ?,
                distraction_count  = ?,
                status             = 'completed',
                started_at         = ?,
                completed_at       = ?
            WHERE id = ?
        """, (actual, energy_s, energy_e, distractions,
              started_at, completed_at, task_id))
        print(f"  🔄 Updated  (ID {task_id:>2}): {title:<38} actual={actual}min")
        updated += 1
    else:
        cursor.execute("""
            INSERT INTO tasks (
                title, priority, category, estimated_minutes,
                actual_minutes, energy_level_start, energy_level_end,
                distraction_count, status, started_at, completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'completed', ?, ?)
        """, (title, priority, category, est, actual,
              energy_s, energy_e, distractions, started_at, completed_at))
        task_id = cursor.lastrowid
        print(f"  ✅ Created  (ID {task_id:>2}): {title:<38} actual={actual}min")
        created += 1

conn.commit()

# ── Verify ───────────────────────────────────────────────────────────────────
cursor.execute("""
    SELECT COUNT(*) FROM tasks
    WHERE status = 'completed' AND actual_minutes > 0
""")
qualifying = cursor.fetchone()[0]
conn.close()

print("-" * 60)
print(f"\n📊 Summary:")
print(f"   🔄 Updated : {updated} existing tasks")
print(f"   ✅ Created : {created} new tasks")
print(f"   🎯 Qualifying for ML training: {qualifying} tasks")

if qualifying >= 10:
    print(f"\n🚀 Ready! Now run these 3 commands:")
    print(f"   curl -X POST http://localhost:8000/ml/train | python -m json.tool")
    print(f"   curl -X POST http://localhost:8000/ml/predict -H 'Content-Type: application/json' \\")
    print(f"        -d '{{\"estimated_minutes\":60,\"priority\":\"High\",\"category\":\"Work\",\"energy_level_start\":8}}' \\")
    print(f"        | python -m json.tool")
    print(f"   curl http://localhost:8000/ml/feature-importance | python -m json.tool")
else:
    print(f"\n⚠️  Still need {10 - qualifying} more qualifying tasks.")
