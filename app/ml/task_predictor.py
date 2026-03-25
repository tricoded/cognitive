# app/ml/task_predictor.py

import pickle
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

MODEL_PATH = Path("app/ml/models/time_predictor.pkl")

# Feature encoding maps
PRIORITY_MAP = {"Critical": 5, "High": 4, "Medium": 3, "Low": 2, "Overdue": 6}
CATEGORY_MAP = {
    "Development": 5,
    "Work":        4,
    "Learning":    3,
    "Personal":    2,
    "Finance":     1,
}


class TaskDifficultyPredictor:
    """
    Predicts how long a task will actually take (in minutes).

    Training:  GradientBoostingRegressor on completed tasks with actual_minutes.
    Fallback:  Returns task.estimated_minutes if not trained, or 60 if neither.
    Auto-trains: After every 5th task completion via retrain_if_ready().
    """

    def __init__(self):
        self.model      = None
        self.is_trained = False
        self._load()

    # ── Persistence ────────────────────────────────────────────────────
    def _load(self):
        if MODEL_PATH.exists():
            try:
                with open(MODEL_PATH, "rb") as f:
                    self.model = pickle.load(f)
                self.is_trained = True
                logger.info("[Predictor] Model loaded from disk.")
            except Exception as e:
                logger.warning(f"[Predictor] Failed to load model: {e}")

    def _save(self):
        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(MODEL_PATH, "wb") as f:
            pickle.dump(self.model, f)

    # ── Feature Engineering ─────────────────────────────────────────────
    def _featurize(self, task) -> list[float]:
        """
        Convert a task ORM object into a numeric feature vector.
        Features: [title_word_count, priority_score, category_score,
                   hour_created, has_deadline, days_until_due]
        """
        title_words  = len((task.title or "").split())
        priority     = PRIORITY_MAP.get(task.priority or "Medium", 3)
        category     = CATEGORY_MAP.get(task.category or "Work", 4)
        hour_created = task.created_at.hour if task.created_at else 9
        has_deadline = 1 if task.due_date else 0

        # Days until due (0 if overdue, 30 if no deadline)
        days_until_due = 30
        if task.due_date:
            from datetime import date
            due = task.due_date.date() if hasattr(task.due_date, "date") else task.due_date
            days_until_due = max(0, (due - date.today()).days)

        return [
            title_words,
            priority,
            category,
            hour_created,
            has_deadline,
            days_until_due,
        ]

    # ── Training ────────────────────────────────────────────────────────
    def train(self, completed_tasks: list) -> bool:
        """
        Train on completed tasks that have actual_minutes recorded.
        Returns True if training succeeded, False if not enough data.
        """
        try:
            from sklearn.ensemble import GradientBoostingRegressor
            from sklearn.model_selection import cross_val_score
            import numpy as np
        except ImportError:
            logger.error("[Predictor] scikit-learn not installed. Run: pip install scikit-learn")
            return False

        # Only train on tasks with real time data
        trainable = [
            t for t in completed_tasks
            if t.actual_minutes and t.actual_minutes > 0
        ]

        if len(trainable) < 5:
            logger.info(f"[Predictor] Not enough data: {len(trainable)}/5 tasks needed.")
            return False

        X = [self._featurize(t) for t in trainable]
        y = [float(t.actual_minutes) for t in trainable]

        self.model = GradientBoostingRegressor(
            n_estimators  = 100,
            max_depth     = 3,
            learning_rate = 0.1,
            subsample     = 0.8,
            random_state  = 42,
        )
        self.model.fit(X, y)
        self._save()
        self.is_trained = True

        # Log cross-val MAE if enough data
        if len(trainable) >= 10:
            scores = cross_val_score(
                self.model, X, y,
                cv=min(5, len(trainable)),
                scoring="neg_mean_absolute_error",
            )
            mae = -scores.mean()
            logger.info(f"[Predictor] Trained on {len(trainable)} tasks. CV MAE: {mae:.1f} min")
        else:
            logger.info(f"[Predictor] Trained on {len(trainable)} tasks.")

        return True

    # ── Prediction ──────────────────────────────────────────────────────
    def predict(self, task) -> int:
        """
        Returns predicted minutes for a single task.
        Falls back to estimated_minutes → 60 if model not ready.
        """
        if not self.is_trained or self.model is None:
            return task.estimated_minutes or 60

        try:
            features = self._featurize(task)
            raw      = self.model.predict([features])[0]
            # Round to nearest 5 minutes, minimum 5
            return max(5, int(round(raw / 5) * 5))
        except Exception as e:
            logger.warning(f"[Predictor] Prediction failed: {e}")
            return task.estimated_minutes or 60

    # ── Auto-retrain trigger ─────────────────────────────────────────────
    def retrain_if_ready(self, db) -> bool:
        """
        Called after every task completion.
        Retrains automatically when we have 5, 10, 20, 50+ completions
        (threshold-based so it doesn't retrain on every single task).
        """
        from app.models import Task

        completed = db.query(Task).filter(
            Task.status == "completed",
            Task.actual_minutes.isnot(None),
        ).all()

        count = len(completed)

        # Retrain at: 5, 10, 20, then every 10 after that
        thresholds = {5, 10, 20}
        should_retrain = (
            count in thresholds or
            (count >= 20 and count % 10 == 0)
        )

        if should_retrain:
            success = self.train(completed)
            if success:
                logger.info(f"[Predictor] Auto-retrained at {count} completions.")
            return success

        return False


# ── Singleton ────────────────────────────────────────────────────────────────
predictor = TaskDifficultyPredictor()
