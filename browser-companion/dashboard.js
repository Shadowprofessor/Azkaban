window.addEventListener("message", async (event) => {
  const data = event.data;
  if (event.source !== window || event.origin !== location.origin || data?.type !== "ghostprint-open-picker" ||
      !document.getElementById("ghostprint-tab-picker") || !/^[a-f0-9-]{36}$/.test(data.request)) return;
  try {
    const result = await chrome.runtime.sendMessage({ type: "open-picker", request: data.request, target: data.target });
    if (!result?.opened) throw new Error();
    window.postMessage({ type: "ghostprint-picker-opened", request: data.request }, location.origin);
  } catch {
    window.postMessage({ type: "ghostprint-picker-unavailable", request: data.request }, location.origin);
  }
});

chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (sender.id !== chrome.runtime.id || message?.type !== "ghostprint-picker-result") return;
  window.postMessage(message, location.origin);
  respond({ delivered: true });
});
