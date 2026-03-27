// popup/popup.js
// Connects to background.js via chrome.runtime.sendMessage

const STREAMLIT_FALLBACK = "http://localhost:8501";

// ── Elements ──────────────────────────────────────────────────────────────────
// NOTE: Every element is fetched with getElementById — if it doesn't exist in
// the HTML, it returns null. We guard ALL event listeners with ?. so a missing
// element NEVER crashes the script and breaks sessions rendering.

const statusDot        = document.getElementById("statusDot");
const budgetValue      = document.getElementById("budgetValue");
const barFill          = document.getElementById("barFill");
const budgetLeft       = document.getElementById("budgetLeft");
const budgetPct        = document.getElementById("budgetPct");
const sessionsList     = document.getElementById("sessionsList");
const refreshBtn       = document.getElementById("refreshBtn");
const lastUpdated      = document.getElementById("lastUpdated");
const overBudgetBanner = document.getElementById("overBudgetBanner");
const openDashboard    = document.getElementById("openDashboard");
// openTracker is GONE from HTML — we no longer reference it at all ✅

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatMs(ms) {
  const totalSec = Math.floor(ms / 1000);
  const mins = Math.floor(totalSec / 60);
  const secs = totalSec % 60;
  if (mins === 0) return `${secs}s`;
  return `${mins}m ${secs}s`;
}

function formatTime(date) {
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function platformIcon(name) {
  const icons = {
    ChatGPT:    "🤖",
    Claude:     "🧠",
    Gemini:     "♊",
    DeepSeek:   "🔍",
    Perplexity: "🔮",
    Copilot:    "💡",
  };
  return icons[name] || "🤖";
}

// ── Render sessions ───────────────────────────────────────────────────────────

function renderSessions(sessions) {
  if (!sessionsList) return; // guard: element must exist

  if (!sessions || sessions.length === 0) {
    sessionsList.innerHTML = `
      <div class="empty">
        <div class="empty-icon">😴</div>
        <div>No AI tools open right now</div>
      </div>`;
    if (statusDot) statusDot.className = "status-dot";
    return;
  }

  const activeSessions = sessions.filter(s => s.isActive);
  if (statusDot) {
    statusDot.className = activeSessions.length > 0
      ? "status-dot active"
      : "status-dot";
  }

  sessionsList.innerHTML = sessions.map(session => {
    const icon    = platformIcon(session.platformName);
    const timeStr = formatMs(session.activeMs);
    const isActive = session.isActive;
    // Category badge — comes from config.js via background.js automatically
    const category = session.category || "chatbot";

    return `
      <div class="session-card ${isActive ? "active-tab" : ""}">
        <div>
          <div class="session-name">${icon} ${session.platformName}</div>
          <div class="badges">
            <span class="cat-badge">${category}</span>
            <span class="msg-badge">💬 ${session.messageCount} msg${session.messageCount !== 1 ? "s" : ""}</span>
          </div>
        </div>
        <div style="text-align:right;">
          <div class="session-time">${timeStr}</div>
          ${isActive
            ? `<div style="font-size:9px; color:var(--accent2); margin-top:2px;">● LIVE</div>`
            : `<div style="font-size:9px; color:var(--muted); margin-top:2px;">paused</div>`
          }
        </div>
      </div>`;
  }).join("");
}

// ── Render budget ─────────────────────────────────────────────────────────────

function renderBudget(totalMins, budgetMins) {
  if (!budgetValue || !barFill || !budgetPct || !budgetLeft) return; // guard

  const pct       = Math.min((totalMins / budgetMins) * 100, 100);
  const remaining = budgetMins - totalMins;
  const over      = totalMins > budgetMins;

  budgetValue.innerHTML = `${totalMins}<span> / ${budgetMins}min</span>`;

  barFill.style.width      = `${pct}%`;
  barFill.style.background = over
    ? "var(--danger)"
    : pct >= 80 ? "var(--warn)" : "var(--accent2)";

  budgetPct.textContent  = `${pct.toFixed(0)}%`;
  budgetLeft.textContent = over
    ? `⚠️ ${Math.abs(remaining)}min over budget`
    : `${remaining}min remaining`;
  budgetLeft.style.color = over
    ? "var(--danger)"
    : pct >= 80 ? "var(--warn)" : "var(--muted)";

  if (statusDot) {
    if (over) {
      statusDot.classList.add("danger");
      statusDot.classList.remove("warn");
    } else if (pct >= 80) {
      statusDot.classList.add("warn");
      statusDot.classList.remove("danger");
    }
  }

  if (overBudgetBanner) {
    overBudgetBanner.classList.toggle("visible", over);
  }
}

// ── Main fetch & render ───────────────────────────────────────────────────────

async function refresh() {
  if (refreshBtn) refreshBtn.classList.add("spinning");

  try {
    // 1. Sessions
    const sessionRes = await chrome.runtime.sendMessage({ type: "GET_SESSIONS" });
    renderSessions(sessionRes?.sessions || []);

    // 2. Budget
    const todayRes = await chrome.runtime.sendMessage({ type: "GET_TODAY_TOTAL" });
    const total    = todayRes?.total  ?? 0;
    const budget   = todayRes?.budget ?? 120;
    renderBudget(total, budget);

    if (lastUpdated) lastUpdated.textContent = `Updated ${formatTime(new Date())}`;
  } catch (err) {
    console.error("[Popup] Refresh error:", err);
    if (sessionsList) {
      sessionsList.innerHTML = `<div class="empty"><div>⚠️ Could not reach extension background</div></div>`;
    }
    if (lastUpdated) lastUpdated.textContent = "Update failed";
  }

  setTimeout(() => {
    if (refreshBtn) refreshBtn.classList.remove("spinning");
  }, 500);
}

// ── Button actions ────────────────────────────────────────────────────────────

// Guard with ?. — if button doesn't exist in HTML, this is a no-op, not a crash
openDashboard?.addEventListener("click", async () => {
  const res = await chrome.storage.sync.get(["appUrl"]);
  const url = res.appUrl || STREAMLIT_FALLBACK;
  chrome.tabs.create({ url });
  window.close();
});

refreshBtn?.addEventListener("click", () => refresh());

// ── Auto-refresh every 5 seconds ─────────────────────────────────────────────
refresh();
const interval = setInterval(refresh, 5000);
window.addEventListener("unload", () => clearInterval(interval));
