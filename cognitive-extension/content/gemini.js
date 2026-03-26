// content/gemini.js
(function () {
  let lastCount = 0;

  function countMessages() {
    try {
      const msgs = document.querySelectorAll("user-query");
      if (msgs.length > lastCount) {
        const diff = msgs.length - lastCount;
        lastCount = msgs.length;
        for (let i = 0; i < diff; i++) {
          chrome.runtime.sendMessage({ type: "MESSAGE_SENT", platform: "Gemini" })
            .catch(() => observer.disconnect());
        }
      }
    } catch (_) {
      observer.disconnect();
    }
  }

  const observer = new MutationObserver(() => {
    try { countMessages(); } catch (_) { observer.disconnect(); }
  });

  observer.observe(document.body, { childList: true, subtree: true });
  countMessages();
})();
