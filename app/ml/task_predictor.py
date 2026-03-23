import os
import json
import logging
import numpy as np
import joblib

from datetime import datetime
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import LabelEncoder
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

MODEL_PATH    = "models/task_predictor.pkl"
ENCODER_PATH  = "models/task_encoders.pkl"
META_PATH     = "models/training_meta.json"
MIN_SAMPLES   = 10

# Safe known labels so encoder never crashes on unseen values
KNOWN_PRIORITIES  = ["Low", "Medium", "High", "Critical"]
KNOWN_CATEGORIES  = [
    "Work", "Personal", "Health", "Learning",
    "Finance", "Other", "Creative", "Admin"
]


class TaskDifficultyPredictor:
    """
    ML model to predict task completion time based on historical data.
    Upgraded: persistent encoders, MAE tracking, graceful fallback.
    """

    def __init__(self):
        self.model            = RandomForestRegressor(
            n_estimators=100,
            max_depth=6,
            min_samples_leaf=2,
            random_state=42
        )
        self.priority_encoder = LabelEncoder()
        self.category_encoder = LabelEncoder()
        self.is_trained       = False

        # Pre-fit encoders with known labels so they never crash
        self.priority_encoder.fit(KNOWN_PRIORITIES)
        self.category_encoder.fit(KNOWN_CATEGORIES)

        # Try to load existing saved model on startup
        self._load_if_exists()

    # ──────────────────────────────────────────────────────────
    #  INTERNAL HELPERS
    # ──────────────────────────────────────────────────────────

    def _safe_priority_encode(self, priority: str) -> int:
        """Encode priority; fall back to 'Medium' if unseen."""
        if priority not in self.priority_encoder.classes_:
            priority = "Medium"
        return int(self.priority_encoder.transform([priority])[0])

    def _safe_category_encode(self, category: str) -> int:
        """Encode category; fall back to 'Other' if unseen."""
        if category not in self.category_encoder.classes_:
            category = "Other"
        return int(self.category_encoder.transform([category])[0])

    def _load_if_exists(self):
        """Load saved model + encoders from disk if available."""
        if os.path.exists(MODEL_PATH) and os.path.exists(ENCODER_PATH):
            try:
                self.model            = joblib.load(MODEL_PATH)
                encoders              = joblib.load(ENCODER_PATH)
                self.priority_encoder = encoders["priority"]
                self.category_encoder = encoders["category"]
                self.is_trained       = True
                logger.info("ML model loaded from disk.")
            except Exception as e:
                logger.warning(f"Could not load saved model: {e}")

    # ──────────────────────────────────────────────────────────
    #  FEATURE ENGINEERING
    # ──────────────────────────────────────────────────────────

    def prepare_features(self, task_data: List[Dict]) -> np.ndarray:
        """Extract numeric features from task dicts."""
        features = []
        for task in task_data:
            features.append([
                self._safe_priority_encode(task.get("priority", "Medium")),
                self._safe_category_encode(task.get("category", "Other")),
                float(task.get("estimated_minutes", 60)),
                float(task.get("distraction_count", 0)),
                float(task.get("energy_level_start", 5)),
            ])
        return np.array(features)

    @staticmethod
    def feature_names() -> List[str]:
        return [
            "priority",
            "category",
            "estimated_minutes",
            "distraction_count",
            "energy_level_start"
        ]

    # ──────────────────────────────────────────────────────────
    #  TRAINING
    # ──────────────────────────────────────────────────────────

    def train(self, historical_tasks: List[Dict]) -> Dict:
        """
        Train on completed task history.
        Returns a dict with status and metrics.
        """
        if len(historical_tasks) < MIN_SAMPLES:
            msg = (
                f"Need at least {MIN_SAMPLES} completed tasks. "
                f"Currently have {len(historical_tasks)}."
            )
            logger.warning(msg)
            return {
                "status": "skipped",
                "reason": msg,
                "ml_enabled": False
            }

        # Re-fit encoders to include any new labels seen in data
        all_priorities = list(set(
            KNOWN_PRIORITIES + [t.get("priority", "Medium") for t in historical_tasks]
        ))
        all_categories = list(set(
            KNOWN_CATEGORIES + [t.get("category", "Other") for t in historical_tasks]
        ))
        self.priority_encoder.fit(all_priorities)
        self.category_encoder.fit(all_categories)

        X = self.prepare_features(historical_tasks)
        y = np.array([float(t["actual_minutes"]) for t in historical_tasks])

        # Split only if we have enough data
        if len(historical_tasks) >= 20:
            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=0.2, random_state=42
            )
        else:
            X_train, X_test, y_train, y_test = X, X, y, y

        self.model.fit(X_train, y_train)
        self.is_trained = True

        # Metrics
        y_pred = self.model.predict(X_test)
        mae    = round(float(mean_absolute_error(y_test, y_pred)), 2)

        # Persist model + encoders
        os.makedirs("models", exist_ok=True)
        joblib.dump(self.model, MODEL_PATH)
        joblib.dump(
            {"priority": self.priority_encoder, "category": self.category_encoder},
            ENCODER_PATH
        )

        # Persist metadata
        meta = {
            "trained_at":   datetime.utcnow().isoformat(),
            "num_samples":  len(historical_tasks),
            "mae_minutes":  mae,
            "ml_enabled":   True
        }
        with open(META_PATH, "w") as f:
            json.dump(meta, f, indent=2)

        logger.info(f"Model trained. Samples: {len(historical_tasks)}, MAE: {mae} min")

        return {
            "status":       "trained",
            "samples_used": len(historical_tasks),
            "mae_minutes":  mae,
            "trained_at":   meta["trained_at"],
            "ml_enabled":   True
        }

    # ──────────────────────────────────────────────────────────
    #  PREDICTION
    # ──────────────────────────────────────────────────────────

    def predict_duration(self, task: Dict) -> Dict:
        """
        Predict actual duration for a new task.
        Returns a rich dict (not just an int) with confidence + insight.
        """
        estimated = task.get("estimated_minutes", 60)

        if not self.is_trained:
            # Rule-based fallback
            energy     = task.get("energy_level_start", 5)
            multiplier = 1.0 + (0.05 * (10 - energy))
            predicted  = round(estimated * multiplier)
            return {
                "predicted_actual_minutes": predicted,
                "confidence":  "low",
                "ml_enabled":  False,
                "method":      "rule_based_fallback",
                "insight": (
                    "Complete more tasks to unlock ML predictions. "
                    f"Rule-based estimate: ~{predicted} min."
                )
            }

        X         = self.prepare_features([task])
        predicted = round(float(self.model.predict(X)[0]), 1)
        predicted = max(15.0, predicted)  # Minimum 15 min

        # Confidence from tree variance
        all_preds = np.array([
            tree.predict(X)[0] for tree in self.model.estimators_
        ])
        std_dev = round(float(np.std(all_preds)), 1)

        if std_dev < 3:
            confidence = "high"
        elif std_dev < 8:
            confidence = "medium"
        else:
            confidence = "low"

        # Human insight
        diff = predicted - estimated
        if diff > 2:
            insight = (
                f"Based on your history, this will likely take "
                f"~{round(diff)} min longer than estimated."
            )
        elif diff < -2:
            insight = (
                f"Based on your history, you may finish "
                f"~{abs(round(diff))} min ahead of estimate."
            )
        else:
            insight = "Your estimate looks accurate based on past performance."

        return {
            "predicted_actual_minutes": predicted,
            "confidence":              confidence,
            "std_dev_minutes":         std_dev,
            "ml_enabled":              True,
            "method":                  "random_forest",
            "insight":                 insight
        }

    # ──────────────────────────────────────────────────────────
    #  STATUS & EXPLAINABILITY
    # ──────────────────────────────────────────────────────────

    def get_status(self) -> Dict:
        """Return current model status and training metadata."""
        if not os.path.exists(META_PATH):
            return {
                "ml_enabled": False,
                "reason": "No model trained yet. POST /ml/train first."
            }
        with open(META_PATH) as f:
            return json.load(f)

    def get_feature_importance(self) -> Optional[Dict]:
        """Return feature importances sorted by impact."""
        if not self.is_trained:
            return None
        importance = dict(zip(
            self.feature_names(),
            [round(float(i), 4) for i in self.model.feature_importances_]
        ))
        return dict(
            sorted(importance.items(), key=lambda x: x[1], reverse=True)
        )
