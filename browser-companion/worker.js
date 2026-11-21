function siteOf(address) {
  try {
    const url = new URL(address);
    const host = url.hostname;
    return ["https:", "http:"].includes(url.protocol) && host.includes(".") &&
      !/^\d+\.\d+\.\d+\.\d+$/.test(host) ? host : "";
  } catch {
    return "";
  }
}

async function send(settings, body) {
  if (!settings.code) throw new Error("Pair this extension with GhostPrint first.");
  let response;
  try {
    response = await fetch(`http://127.0.0.1:${settings.port}/api/live/event`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Authorization": `Bearer ${settings.code}` },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(2500)
    });
  } catch {
    throw new Error("Start the GhostPrint dashboard on the selected port.");
  }
  if (!response.ok) throw new Error(response.status === 401 ? "Copy the current pairing code from GhostPrint." :
    "GhostPrint could not record the website.");
}

let active = false;
let needsCapture = false;
function capture() {
  needsCapture = true;
  if (!active) drain();
}

async function drain() {
  active = true;
  try {
    while (needsCapture) {
      needsCapture = false;
      await captureForeground();
    }
  } catch {
    const { settings } = await chrome.storage.session.get("settings");
    if (settings?.enabled) await chrome.action.setBadgeText({ text: "!" });
  } finally {
    active = false;
    if (needsCapture) drain();
  }
}

async function captureForeground() {
  const stored = await chrome.storage.session.get(["settings", "previous"]);
  if (!stored.settings?.enabled) return;
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  if (!tab || !(await chrome.windows.get(tab.windowId)).focused) return;
  const site = siteOf(tab.url);
  if (!site) {
    await chrome.storage.session.remove("previous");
    return;
  }
  const key = `${tab.id}:${site}`;
  if (stored.previous === key) return;
  const current = (await chrome.storage.session.get("settings")).settings;
  if (!current?.enabled || current.code !== stored.settings.code || current.port !== stored.settings.port) return;
  await send(current, { site });
  const latest = (await chrome.storage.session.get("settings")).settings;
  if (latest?.enabled && latest.code === current.code && latest.port === current.port) {
    await chrome.storage.session.set({ previous: key });
    await chrome.action.setBadgeText({ text: "ON" });
  }
}

chrome.tabs.onActivated.addListener(capture);
chrome.tabs.onUpdated.addListener((id, change, tab) => {
  if (tab.active && (change.url || change.status === "complete")) capture();
});
chrome.windows.onFocusChanged.addListener((id) => {
  if (id !== chrome.windows.WINDOW_ID_NONE) capture();
});
chrome.permissions.onRemoved.addListener(async ({ permissions }) => {
  if (permissions?.includes("tabs")) {
    const { settings } = await chrome.storage.session.get("settings");
    if (settings) await chrome.storage.session.set({ settings: { ...settings, enabled: false } });
    await chrome.action.setBadgeText({ text: "" });
  }
});
chrome.runtime.onMessage.addListener((message) => {
  if (message === "capture") capture();
});
