globalThis.startPrivacyMonitor = (sessionId) => {
  const deadline = Date.now() + 10 * 60 * 1000;
  let lastSnapshot;
  let timer;
  let stopped = false;
  const resources = performance.getEntriesByType("resource").slice(-499);
  const observer = new PerformanceObserver((entries) => {
    resources.push(...entries.getEntries().slice(-499));
    if (resources.length > 499) resources.splice(0, resources.length - 499);
  });
  observer.observe({ type: "resource" });

  function stop() {
    stopped = true;
    clearTimeout(timer);
    observer.disconnect();
    chrome.runtime.sendMessage({ type: "stop-live-watch", sessionId }).catch(() => {});
  }

  async function sample() {
    if (stopped || Date.now() >= deadline) {
      stop();
      return;
    }
    try {
      const snapshot = await inspectPage(undefined, resources);
      const current = JSON.stringify(snapshot);
      const response = await chrome.runtime.sendMessage({
        type: "live-watch", sessionId, snapshot: current === lastSnapshot ? null : snapshot
      });
      if (!response?.active) {
        stop();
        return;
      }
      lastSnapshot = current;
    } catch {
      stop();
      return;
    }
    if (!stopped) timer = setTimeout(sample, 5000);
  }

  window.addEventListener("pagehide", stop, { once: true });
  sample();
};
