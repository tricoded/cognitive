# app/ml/user_patterns.py

from collections import defaultdict
from datetime import date, timedelta
from sqlalchemy.orm import Session
from app.models import Task


def analyze_user_patterns(db: Session, user_id: int) -> dict:
    """
    Derives personal productivity patterns from completed task history.
    Returns a dict of insights — empty dict if not enough data.
    Called in handle_greeting() for the morning briefing.
    """
    completed = db.query(Task).filter(Task.status == "completed").all()

    # Need at least 3 completed tasks to say anything meaningful
    if len(completed) < 3:
        return {}

    patterns = {}

    # ── Peak productivity hour ──────────────────────────────────────────
    hour_counts = defaultdict(int)
    for t in completed:
        if t.completed_at:
            hour_counts[t.completed_at.hour] += 1

    if hour_counts:
        peak_hour = max(hour_counts, key=hour_counts.get)
        patterns["peak_hour"] = peak_hour
        patterns["peak_hour_label"] = (
            "morning"   if peak_hour < 12 else
            "afternoon" if peak_hour < 17 else
            "evening"
        )

    # ── Most productive day of week ─────────────────────────────────────
    day_names  = ["Monday", "Tuesday", "Wednesday", "Thursday",
                  "Friday", "Saturday", "Sunday"]
    day_counts = defaultdict(int)
    for t in completed:
        if t.completed_at:
            day_counts[t.completed_at.weekday()] += 1

    if day_counts:
        best_day_idx         = max(day_counts, key=day_counts.get)
        patterns["best_day"] = day_names[best_day_idx]

    # ── Fastest / slowest category ──────────────────────────────────────
    cat_times = defaultdict(list)
    for t in completed:
        if t.actual_minutes and t.category:
            cat_times[t.category].append(t.actual_minutes)

    if cat_times:
        cat_avgs = {c: sum(v) / len(v) for c, v in cat_times.items() if v}
        if cat_avgs:
            patterns["fastest_category"] = min(cat_avgs, key=cat_avgs.get)
            patterns["slowest_category"] = max(cat_avgs, key=cat_avgs.get)

    # ── Estimate accuracy (do you under/over-estimate?) ─────────────────
    estimable = [
        t for t in completed
        if t.estimated_minutes and t.actual_minutes and t.actual_minutes > 0
    ]
    if len(estimable) >= 3:
        errors = [t.actual_minutes - t.estimated_minutes for t in estimable]
        avg_error = sum(errors) / len(errors)
        patterns["tends_to"]              = "underestimate" if avg_error > 0 else "overestimate"
        patterns["avg_estimate_error_min"] = round(abs(avg_error), 1)

    # ── Average tasks completed per active day ──────────────────────────
    active_days = set(
        t.completed_at.date()
        for t in completed
        if t.completed_at
    )
    if active_days:
        patterns["avg_tasks_per_day"] = round(len(completed) / len(active_days), 1)

    return patterns
