// popup/popup.js
// Connects to background.js via chrome.runtime.sendMessage

const API_FALLBACK = "http://localhost:8000";
const STREAMLIT_FALLBACK = "http://localhost:8501";

// ── Elements ──────────────────────────────────────────────────────────────────
const statusDot       = document.getElementById("statusDot");
const budgetValue     = document.getElementById("budgetValue");
const barFill         = document.getElementById("barFill");
const budgetLeft      = document.getElementById("budgetLeft");
const budgetPct       = document.getElementById("budgetPct");
const sessionsList    = document.getElementById("sessionsList");
const refreshBtn      = document.getElementById("refreshBtn");
const lastUpdated     = document.getElementById("lastUpdated");
const overBudgetBanner = document.getElementById("overBudgetBanner");
const openDashboard   = document.getElementById("openDashboard");
const openTracker     = document.getElementById("openTracker");

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
  if (!sessions || sessions.length === 0) {
    sessionsList.innerHTML = `
      <div class="empty">
        <div class="empty-icon">😴</div>
        <div>No AI tools open right now</div>
      </div>`;
    statusDot.className = "status-dot";
    return;
  }

  const activeSessions = sessions.filter(s => s.isActive);
  statusDot.className = activeSessions.length > 0
    ? "status-dot active"
    : "status-dot";

  sessionsList.innerHTML = sessions.map(session => {
    const icon = platformIcon(session.platformName);
    const timeStr = formatMs(session.activeMs);
    const isActive = session.isActive;

    return `
      <div class="session-card ${isActive ? "active-tab" : ""}">
        <div>
          <div class="session-name">${icon} ${session.platformName}</div>
          <div class="session-meta">${session.category}</div>
          <span class="msg-badge">💬 ${session.messageCount} msg${session.messageCount !== 1 ? "s" : ""}</span>
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
  const pct = Math.min((totalMins / budgetMins) * 100, 100);
  const remaining = budgetMins - totalMins;
  const over = totalMins > budgetMins;

  // Value display
  budgetValue.innerHTML = `${totalMins}<span> / ${budgetMins}min</span>`;

  // Bar
  barFill.style.width = `${pct}%`;
  barFill.style.background = over
    ? "var(--danger)"
    : pct >= 80
    ? "var(--warn)"
    : "var(--accent2)";

  // Meta text
  budgetPct.textContent = `${pct.toFixed(0)}%`;
  budgetLeft.textContent = over
    ? `⚠️ ${Math.abs(remaining)}min over budget`
    : `${remaining}min remaining`;
  budgetLeft.style.color = over ? "var(--danger)" : pct >= 80 ? "var(--warn)" : "var(--muted)";

  // Status dot color
  if (over) {
    statusDot.classList.add("danger");
    statusDot.classList.remove("warn");
  } else if (pct >= 80) {
    statusDot.classList.add("warn");
    statusDot.classList.remove("danger");
  }

  // Banner
  overBudgetBanner.classList.toggle("visible", over);
}

// ── Main fetch & render ───────────────────────────────────────────────────────

async function refresh() {
  refreshBtn.classList.add("spinning");

  try {
    // 1. Get sessions from background service worker
    const sessionRes = await chrome.runtime.sendMessage({ type: "GET_SESSIONS" });
    renderSessions(sessionRes?.sessions || []);

    // 2. Get today total from background (reads chrome.storage.local)
    const todayRes = await chrome.runtime.sendMessage({ type: "GET_TODAY_TOTAL" });
    const total  = todayRes?.total  ?? 0;
    const budget = todayRes?.budget ?? 120;
    renderBudget(total, budget);

    lastUpdated.textContent = `Updated ${formatTime(new Date())}`;
  } catch (err) {
    console.error("[Popup] Refresh error:", err);
    sessionsList.innerHTML = `<div class="empty"><div>⚠️ Could not reach extension background</div></div>`;
    lastUpdated.textContent = "Update failed";
  }

  setTimeout(() => refreshBtn.classList.remove("spinning"), 500);
}

// ── Button actions ────────────────────────────────────────────────────────────

openDashboard.addEventListener("click", async () => {
  const res = await chrome.storage.sync.get(["appUrl"]);
  const url = res.appUrl || STREAMLIT_FALLBACK;
  chrome.tabs.create({ url }); 
  window.close();
});

openTracker.addEventListener("click", async () => {
  try {
    // Force log all active sessions first
    await chrome.runtime.sendMessage({ type: "FORCE_LOG_ALL" });
    
    // Wait for POST to complete
    await new Promise(resolve => setTimeout(resolve, 800));
    
    // Get session data to pre-fill form
    const sessionRes = await chrome.runtime.sendMessage({ type: "GET_SESSIONS" });
    const sessions = sessionRes?.sessions || [];
    
    // Find the most active session
    const activeSession = sessions.find(s => s.isActive) || sessions[0];
    
    const res = await chrome.storage.sync.get(["appUrl"]);
    const base = res.appUrl || STREAMLIT_FALLBACK;
    
    if (activeSession) {
      // Pass session data via URL params
      const params = new URLSearchParams({
        tool: activeSession.platformName,
        duration: Math.round(activeSession.activeMs / 60000), // Convert to minutes
        messages: activeSession.messageCount
      });
      chrome.tabs.create({ url: `${base}/AI_Tracker?${params.toString()}` });
    } else {
      chrome.tabs.create({ url: `${base}/AI_Tracker` });
    }
  } catch (error) {
    console.error('[Popup] Force log error:', error);
    // Open page anyway even if force log fails
    const res = await chrome.storage.sync.get(["appUrl"]);
    const base = res.appUrl || STREAMLIT_FALLBACK;
    chrome.tabs.create({ url: `${base}/AI_Tracker` });
  }
  window.close();
});

refreshBtn.addEventListener("click", () => refresh());

// ── Auto-refresh every 5 seconds while popup is open ─────────────────────────
refresh();
const interval = setInterval(refresh, 5000);
window.addEventListener("unload", () => clearInterval(interval));
