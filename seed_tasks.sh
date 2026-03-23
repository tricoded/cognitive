#!/bin/bash
# seed_tasks.sh — Creates 15 realistic completed tasks for ML training

BASE="http://localhost:8000"

echo "🌱 Seeding training data..."

declare -a TITLES=(
  "Write project proposal"
  "Code review session"
  "Fix authentication bug"
  "Design database schema"
  "Write unit tests"
  "Deploy to staging"
  "Update documentation"
  "Team standup prep"
  "Refactor payment module"
  "Research ML frameworks"
  "Write API endpoints"
  "Performance optimization"
  "Security audit review"
  "Client presentation prep"
  "Sprint planning session"
)

declare -a PRIORITIES=("High" "Medium" "High" "High" "Medium" "Critical" "Low" "Medium" "High" "Medium" "High" "Medium" "High" "Critical" "Medium")
declare -a CATEGORIES=("Work" "Work" "Development" "Development" "Work" "Work" "Work" "Work" "Development" "Learning" "Development" "Work" "Work" "Work" "Work")
declare -a ESTIMATES=(  60     45     90            120          30       45      20       15        90               60        75            120              60             90              60)
declare -a ENERGIES=(   8      6      7             9            5        8       4        6         7                7         8             5                6              9               7)
declare -a DISTRACTIONS=(1     2      0             1            3        0       2        1         0                1         2             3                0              0               1)

for i in "${!TITLES[@]}"; do
  TITLE="${TITLES[$i]}"
  PRIORITY="${PRIORITIES[$i]}"
  CATEGORY="${CATEGORIES[$i]}"
  ESTIMATE="${ESTIMATES[$i]}"
  ENERGY="${ENERGIES[$i]}"
  DISTRACTION="${DISTRACTIONS[$i]}"

  # ── Step 1: Create task ──────────────────────────────────
  RESPONSE=$(curl -s -X POST "$BASE/tasks" \
    -H "Content-Type: application/json" \
    -d "{
      \"title\": \"$TITLE\",
      \"priority\": \"$PRIORITY\",
      \"category\": \"$CATEGORY\",
      \"estimated_minutes\": $ESTIMATE
    }")

  TASK_ID=$(echo "$RESPONSE" | python -c "import sys,json; print(json.load(sys.stdin)['id'])" 2>/dev/null)

  if [ -z "$TASK_ID" ]; then
    echo "  ❌ Failed to create: $TITLE"
    continue
  fi

  # ── Step 2: Start task ───────────────────────────────────
  curl -s -X POST "$BASE/tasks/$TASK_ID/start?energy_level=$ENERGY" > /dev/null

  # ── Step 3: Small delay so actual_minutes > 0 ───────────
  sleep 2

  # ── Step 4: Complete task ────────────────────────────────
  curl -s -X POST "$BASE/tasks/$TASK_ID/complete?energy_level=$((ENERGY - 1))&distractions=$DISTRACTION" > /dev/null

  echo "  ✅ [$((i+1))/15] $TITLE (ID: $TASK_ID) — est: ${ESTIMATE}min, energy: $ENERGY"
done

echo ""
echo "🏋️  Triggering ML training..."
TRAIN_RESULT=$(curl -s -X POST "$BASE/ml/train")
echo "$TRAIN_RESULT" | python -m json.tool

echo ""
echo "🔮 Testing prediction..."
curl -s -X POST "$BASE/ml/predict" \
  -H "Content-Type: application/json" \
  -d '{"estimated_minutes": 60, "priority": "High", "category": "Work", "energy_level_start": 7}' \
  | python -m json.tool

echo ""
echo "📊 Feature importance..."
curl -s "$BASE/ml/feature-importance" | python -m json.tool

echo ""
echo "✅ Done! ML pipeline is live."
