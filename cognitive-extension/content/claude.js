// content/claude.js
(function () {
  let lastMessageCount = 0;
  let isContextValid = true;

  function checkContext() {
    try {
      return chrome.runtime && chrome.runtime.id !== undefined;
    } catch {
      return false;
    }
  }

  // ── Multi-strategy message selector ──────────────────────
  // Covers: official claude.ai + Chatly wrappers + generic chat UIs
  function getMessageCount() {
    const strategies = [
      // 1. Official claude.ai (most specific)
      () => document.querySelectorAll('[data-testid="human-turn"]').length,

      // 2. Common Claude wrapper pattern
      () => document.querySelectorAll('.human-turn').length,

      // 3. Generic user message classes used by Chatly-style wrappers
      () => document.querySelectorAll('[class*="user-message"]:not([class*="assistant"])').length,

      // 4. Role-based attribute (some wrappers copy ChatGPT's pattern)
      () => document.querySelectorAll('[data-message-author-role="user"]').length,

      // 5. Paragraph inside user bubble — last resort broad match
      () => document.querySelectorAll('[class*="human"] p, [class*="user-turn"] p').length,
    ];

    for (const strategy of strategies) {
      try {
        const count = strategy();
        if (count > 0) return count;
      } catch (_) {}
    }
    return 0;
  }

  function countMessages() {
    if (!isContextValid) return;

    try {
      const count = getMessageCount();

      if (count > lastMessageCount) {
        const newCount = count - lastMessageCount;
        lastMessageCount = count;

        console.log(`[Cognitive] 🧠 Claude: detected ${newCount} new message(s), total: ${count}`);

        for (let i = 0; i < newCount; i++) {
          if (!checkContext()) {
            isContextValid = false;
            observer.disconnect();
            return;
          }

          chrome.runtime.sendMessage({
            type: "MESSAGE_SENT",
            platform: "Claude"
          }).catch((error) => {
            console.log('[Cognitive] Send error:', error?.message);
            if (error?.message?.includes('Extension context invalidated')) {
              isContextValid = false;
              observer.disconnect();
            }
          });
        }
      }
    } catch (e) {
      isContextValid = false;
      observer.disconnect();
      console.log('[Cognitive] Claude content script error:', e.message);
    }
  }

  // ── Observer ──────────────────────────────────────────────
  const observer = new MutationObserver(() => {
    if (!isContextValid) {
      observer.disconnect();
      return;
    }
    try {
      countMessages();
    } catch (error) {
      isContextValid = false;
      observer.disconnect();
    }
  });

  // ── Start ─────────────────────────────────────────────────
  if (checkContext()) {
    observer.observe(document.body, {
      childList: true,
      subtree: true
    });

    // Initial check (for already-loaded conversations)
    setTimeout(countMessages, 1000);

    console.log('[Cognitive] ✅ Claude/Chatly content script loaded on:', window.location.hostname);
  } else {
    console.log('[Cognitive] ⚠️ Cannot start — extension context invalid');
  }
})();
