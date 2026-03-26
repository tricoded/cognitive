// background.js — Service Worker
// Handles: tab tracking, idle detection, session logging, nudge notifications

import { COGNITIVE_CONFIG } from "./config.js";

let activeSessions = {};


function getPlatform(url) {
  try {
    const hostname = new URL(url).hostname.replace("www.", "");
    for (const [key, val] of Object.entries(COGNITIVE_CONFIG.PLATFORMS)) {
      if (hostname.includes(key)) return { hostname, ...val };
    }
  } catch (_) {}
  return null;
}

async function getApiBase() {
  return new Promise((resolve) => {
    chrome.storage.sync.get(["apiBase"], (res) => {
      resolve(res.apiBase || COGNITIVE_CONFIG.API_BASE_DEFAULT);
    });
  });
}

async function getDailyBudgetMins() {
  return new Promise((resolve) => {
    chrome.storage.sync.get(["dailyBudgetMins"], (res) => {
      resolve(res.dailyBudgetMins || 120);
    });
  });
}

async function getTodayTotalMins() {
  return new Promise((resolve) => {
    chrome.storage.local.get(["todayDate", "todayTotalMins"], (res) => {
      const today = new Date().toISOString().slice(0, 10);
      if (res.todayDate !== today) {
        chrome.storage.local.set({ todayDate: today, todayTotalMins: 0 });
        resolve(0);
      } else {
        resolve(res.todayTotalMins || 0);
      }
    });
  });
}

async function addTodayMins(mins) {
  const current = await getTodayTotalMins();
  const newTotal = current + mins;
  const today = new Date().toISOString().slice(0, 10);
  chrome.storage.local.set({ todayDate: today, todayTotalMins: newTotal });
  return newTotal;
}

function qualityFromCount(messageCount) {
  return messageCount >= 3 ? "active" : "passive";
}

// ── POST session to backend ───────────────────────────────────────────────────

async function logSession(session) {
  const durationMins = Math.round(session.activeMs / 60000);
  if (durationMins < 1) return;

  const apiBase = await getApiBase();
  const payload = {
    tool_name:     session.platformName,
    category:      session.category,
    duration_mins: durationMins,
    quality:       qualityFromCount(session.messageCount),
    notes:         `Auto-tracked · ${session.messageCount} message(s)`,
  };

  try {
    const res = await fetch(`${apiBase}/ai-usage/`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify(payload),
    });
    if (!res.ok) {
      console.warn("[Cognitive] Failed to log session:", res.status, await res.text());
    } else {
      console.log("[Cognitive] ✅ Logged:", payload);
    }
  } catch (err) {
    console.error("[Cognitive] Network error logging session:", err);
    chrome.storage.local.get(["failedSessions"], (r) => {
      const failed = r.failedSessions || [];
      failed.push({ ...payload, failedAt: Date.now() });
      chrome.storage.local.set({ failedSessions: failed });
    });
  }

  const newTotal = await addTodayMins(durationMins);
  await checkNudge(newTotal);
}


async function checkNudge(totalMins) {
  const today = new Date().toISOString().slice(0, 10);
  const result = await new Promise(r =>
    chrome.storage.local.get(["nudgeFiredDate"], r)
  );
  if (result.nudgeFiredDate === today) return;

  if (totalMins >= COGNITIVE_CONFIG.NUDGE_THRESHOLD_MINS) {
    chrome.notifications.create("cognitive_nudge", {
    type: "basic",
    iconUrl: "icons/icon128.png",
    title: "AI Usage Check-In",
    message: `You've spent ${totalMins} minutes on AI tools today. Take a moment to reflect — is this working for you?`,
    buttons: [{ title: "Open Dashboard" }, { title: "Dismiss" }],
    priority: 2,
  });
    chrome.storage.local.set({ nudgeFiredDate: today });
  }
}

chrome.notifications.onButtonClicked.addListener((notifId, btnIdx) => {
  if (notifId === "cognitive_nudge" && btnIdx === 0) {
    chrome.storage.sync.get(["appUrl"], (res) => {
      const url = res.appUrl || "http://localhost:8501";
      chrome.tabs.create({ url });
    });
  }
});


async function retryFailedSessions() {
  chrome.storage.local.get(["failedSessions"], async (r) => {
    const failed = r.failedSessions || [];
    if (failed.length === 0) return;

    const apiBase  = await getApiBase();
    const retrying = [...failed];
    const stillFailed = [];

    for (const payload of retrying) {
      try {
        const res = await fetch(`${apiBase}/ai-usage/`, {
          method:  "POST",
          headers: { "Content-Type": "application/json" },
          body:    JSON.stringify(payload),
        });
        if (!res.ok) stillFailed.push(payload);
        else console.log("[Cognitive] ♻️ Retry succeeded:", payload.tool_name);
      } catch (_) {
        stillFailed.push(payload);
      }
    }
    chrome.storage.local.set({ failedSessions: stillFailed });
  });
}

// ── Tab event listeners ───────────────────────────────────────────────────────

chrome.tabs.onActivated.addListener(async ({ tabId }) => {
  for (const [id, session] of Object.entries(activeSessions)) {
    if (parseInt(id) !== tabId && session.lastTick) {
      session.lastTick = null;
    }
  }

  const tab = await chrome.tabs.get(tabId).catch(() => null);
  if (!tab?.url) return;

  const platform = getPlatform(tab.url);
  if (!platform) return;

  if (!activeSessions[tabId]) {
    activeSessions[tabId] = {
      tabId,
      hostname:     platform.hostname,
      platformName: platform.name,
      category:     platform.category,
      startTime:    Date.now(),
      activeMs:     0,
      lastTick:     Date.now(),
      messageCount: 0,
      idleSince:    null,
      logged:       false,
    };
  } else {
    activeSessions[tabId].lastTick = Date.now();
  }
});

chrome.tabs.onRemoved.addListener((tabId) => {
  const session = activeSessions[tabId];
  if (session) {
    logSession(session);
    delete activeSessions[tabId];
  }
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.url) {
    const session  = activeSessions[tabId];
    const platform = getPlatform(changeInfo.url);

    if (session && !platform) {
      logSession(session);
      delete activeSessions[tabId];
    } else if (!session && platform) {
      activeSessions[tabId] = {
        tabId,
        hostname:     platform.hostname,
        platformName: platform.name,
        category:     platform.category,
        startTime:    Date.now(),
        activeMs:     0,
        lastTick:     Date.now(),
        messageCount: 0,
        idleSince:    null,
        logged:       false,
      };
    }
  }
});

// ── Tick ──────────────────────────────────────────────────────────────────────

chrome.alarms.create("tick", { periodInMinutes: 0.5 });

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name !== "tick") return;

  const now      = Date.now();
  const idleSecs = COGNITIVE_CONFIG.IDLE_THRESHOLD_SECS * 1000;

  chrome.idle.queryState(COGNITIVE_CONFIG.IDLE_THRESHOLD_SECS, (state) => {
    for (const [tabId, session] of Object.entries(activeSessions)) {
      if (!session.lastTick) continue;

      const elapsed = now - session.lastTick;

      if (state === "idle" || state === "locked") {
        if (!session.idleSince) session.idleSince = now;
      } else {
        if (session.idleSince) {
          const idleDuration = now - session.idleSince;
          if (idleDuration > idleSecs) {
            session.lastTick  = now;
            session.idleSince = null;
            continue;
          }
          session.idleSince = null;
        }
        session.activeMs += elapsed;
        session.lastTick  = now;

        if (session.activeMs >= 30 * 60 * 1000) {
          logSession({ ...session });
          session.activeMs  = 0;
          session.startTime = now;
        }
      }
    }
  });

  retryFailedSessions();
});

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {

  if (msg.type === "MESSAGE_SENT") {
    const tabId = sender.tab?.id;
    if (tabId && activeSessions[tabId]) {
      activeSessions[tabId].messageCount += 1;
      console.log(`[Cognitive] 💬 Message count for tab ${tabId}: ${activeSessions[tabId].messageCount}`);
    }
    sendResponse({ ok: true });
    return true;
  }

  if (msg.type === "GET_SESSIONS") {
    const sessions = Object.values(activeSessions).map(s => ({
      tabId:        s.tabId,
      platformName: s.platformName,
      category:     s.category,
      activeMs:     s.activeMs,
      messageCount: s.messageCount,
      startTime:    s.startTime,
      isActive:     s.lastTick !== null,
    }));
    sendResponse({ sessions });
    return true;
  }

  if (msg.type === "GET_TODAY_TOTAL") {
    getTodayTotalMins().then(total => {
      getDailyBudgetMins().then(budget => {
        sendResponse({ total, budget });
      });
    });
    return true; // ← REQUIRED for async sendResponse
  }

  if (msg.type === "FORCE_LOG_ALL") {
    const promises = Object.values(activeSessions).map(s => logSession({ ...s }));
    Promise.all(promises).then(() => sendResponse({ ok: true }));
    return true;
  }
});
