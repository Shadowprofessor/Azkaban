const field = (id) => document.getElementById(id);
let settings = {};

function config() {
  const port = field("port").valueAsNumber;
  const code = field("code").value.trim();
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error("Enter a valid dashboard port.");
  if (!code) throw new Error("Paste the pairing code from the GhostPrint dashboard.");
  return { port, code };
}

function showState() {
  field("toggle").textContent = settings.enabled ? "Pause recording" : "Start recording";
}

async function updateSettings(next) {
  settings = next;
  await chrome.storage.session.set({ settings });
  await chrome.storage.session.remove("previous");
  await chrome.action.setBadgeText({ text: settings.enabled ? "ON" : "" });
  showState();
}

field("toggle").addEventListener("click", async () => {
  try {
    if (settings.enabled) {
      await updateSettings({ ...settings, enabled: false });
      await chrome.permissions.remove({ permissions: ["tabs"] });
      field("message").textContent = "Recording paused.";
      return;
    }
    const next = config();
    // Request directly from the click handler so Chrome retains the user gesture.
    if (!(await chrome.permissions.request({ permissions: ["tabs"] }))) {
      field("message").textContent = "Browser permission was declined.";
      return;
    }
    await updateSettings({ ...next, enabled: true });
    chrome.runtime.sendMessage("capture").catch(() => {});
    field("message").textContent = "Recording is on. Check the dashboard for incoming sites.";
  } catch (error) {
    field("message").textContent = error.message;
  }
});

field("inspect").addEventListener("click", async () => {
  try {
    const next = config();
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.url || !/^https?:\/\//.test(tab.url)) throw new Error("Open a website before scanning for links.");
    const [result] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: inspectPage });
    const response = await fetch(`http://127.0.0.1:${next.port}/api/live/event`, {
      method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${next.code}` },
      body: JSON.stringify(result.result), signal: AbortSignal.timeout(2500)
    });
    if (!response.ok) throw new Error("Check the pairing code and open an HTTP or HTTPS website.");
    field("message").textContent = "Browser evidence is ready in GhostPrint. Check this website to compare it with the public policies.";
  } catch (error) {
    field("message").textContent = error.message;
  }
});

field("open").addEventListener("click", () => {
  const port = field("port").valueAsNumber;
  if (Number.isInteger(port) && port > 0 && port <= 65535) chrome.tabs.create({ url: `http://127.0.0.1:${port}/` });
});

async function updateMonitorButton() {
  const { networkWatch } = await chrome.storage.session.get("networkWatch");
  field("monitor").textContent = networkWatch?.expires > Date.now()
    ? "Stop live tab monitoring" : "Monitor this tab for 10 minutes";
}

field("monitor").addEventListener("click", async () => {
  const button = field("monitor");
  button.disabled = true;
  let sessionId;
  try {
    const { networkWatch } = await chrome.storage.session.get("networkWatch");
    if (networkWatch?.expires > Date.now()) {
      await chrome.storage.session.remove("networkWatch");
      field("message").textContent = "Live tab monitoring stopped.";
      return;
    }
    const next = config();
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const url = new URL(tab?.url || "about:blank");
    if (!["http:", "https:"].includes(url.protocol) || !/\.[a-z][a-z0-9-]*$/i.test(url.hostname)) {
      throw new Error("Open a website tab before starting live monitoring.");
    }
    sessionId = crypto.randomUUID();
    await chrome.storage.session.set({ networkWatch: {
      ...next, id: sessionId, tab: tab.id, origin: url.origin, expires: Date.now() + 10 * 60 * 1000
    } });
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["inspection.js", "monitor.js"] });
    const [result] = await chrome.scripting.executeScript({
      target: { tabId: tab.id }, func: (id, expected) => {
        if (location.href !== expected) return false;
        globalThis.startPrivacyMonitor(id);
        return true;
      }, args: [sessionId, url.href]
    });
    if (!result?.result) throw new Error("The page changed. Open the companion again to monitor the new page.");
    field("message").textContent = "Monitoring this tab. New observations appear in the paired dashboard.";
  } catch (error) {
    if (sessionId) await chrome.storage.session.remove("networkWatch");
    field("message").textContent = error.message;
  } finally {
    await updateMonitorButton();
    button.disabled = false;
  }
});

chrome.storage.session.get("settings").then((data) => {
  settings = data.settings ?? {};
  field("port").value = settings.port ?? 8765;
  field("code").value = settings.code ?? "";
  showState();
  field("toggle").disabled = false;
  field("inspect").disabled = false;
  updateMonitorButton().then(() => { field("monitor").disabled = false; });
});
