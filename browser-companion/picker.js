const params = new URLSearchParams(location.search);
const dashboardTab = Number(params.get("tab"));
const dashboardDocument = params.get("document");
const auditRequest = params.get("request");
let targetSite = params.get("target")?.replace(/^www\./, "");
const listButton = document.getElementById("list-tabs");
const showAllButton = document.getElementById("show-all-tabs");
const cancelButton = document.getElementById("cancel-picker");
const pickerStatus = document.getElementById("picker-status");
const tabList = document.getElementById("open-tabs");
let alreadyListed = false;
let finished = false;
let listedTabs = [];

function notifyDashboard(result) {
  return chrome.tabs.sendMessage(dashboardTab, { type: "ghostprint-picker-result", request: auditRequest, ...result },
    { documentId: dashboardDocument });
}

function webTab(address) {
  if (!URL.canParse(address)) return null;
  const url = new URL(address);
  return ["http:", "https:"].includes(url.protocol) && /^[a-z0-9.-]{1,253}$/i.test(url.hostname) &&
    !/^\d+(\.\d+)+$/.test(url.hostname) ? url : null;
}

function displayTabs(tabs) {
  tabList.replaceChildren();
  for (const tab of tabs) {
    if (tab.id === dashboardTab || tab.url?.startsWith(chrome.runtime.getURL(""))) continue;
    const url = webTab(tab.url);
    if (targetSite && url?.hostname.replace(/^www\./, "") !== targetSite) continue;
    const item = document.createElement("li");
    const button = document.createElement("button");
    const title = document.createElement("strong");
    const subtitle = document.createElement("span");
    title.textContent = tab.title || "Untitled tab";
    subtitle.textContent = url ? url.hostname : "This page cannot be audited";
    button.append(title, subtitle);
    button.disabled = !url;
    if (url) button.addEventListener("click", () => auditTab(tab, url));
    item.append(button);
    tabList.append(item);
  }
  const absent = targetSite ? `Open ${targetSite} in this browser, then choose Refresh tabs.` :
    "Open an HTTP or HTTPS website in this browser, then choose Refresh tabs.";
  pickerStatus.textContent = tabList.querySelector("button:enabled") ? "Select a tab to start the audit." : absent;
}

async function loadTabList() {
  listedTabs = await chrome.tabs.query({});
  displayTabs(listedTabs);
  listButton.textContent = "Refresh tabs";
  showAllButton.hidden = !targetSite;
}

showAllButton.addEventListener("click", () => {
  targetSite = undefined;
  showAllButton.hidden = true;
  displayTabs(listedTabs);
});

listButton.addEventListener("click", async () => {
  listButton.disabled = true;
  try {
    // Optional permissions must be requested from the button's click gesture.
    if (!(await chrome.permissions.request({ permissions: ["tabs"] }))) {
      pickerStatus.textContent = "Tab access was declined. Allow access to list tabs or check a website by address.";
      return;
    }
    try {
      await loadTabList();
    } finally {
      const { settings } = await chrome.storage.session.get("settings");
      if (!alreadyListed && !settings?.enabled) await chrome.permissions.remove({ permissions: ["tabs"] });
    }
  } catch {
    pickerStatus.textContent = "Could not list browser tabs. Try again.";
  } finally {
    listButton.disabled = false;
  }
});

async function auditTab(tab, url) {
  const buttons = [...document.querySelectorAll("button:enabled")];
  buttons.forEach((button) => { button.disabled = true; });
  pickerStatus.textContent = `Checking ${url.hostname}…`;
  const permission = { origins: [`${url.protocol}//${url.hostname}/*`] };
  try {
    // Request only this website from this click, then read only the selected tab.
    const existing = chrome.permissions.contains(permission);
    const requested = chrome.permissions.request(permission);
    const [alreadyGranted, granted] = await Promise.all([existing, requested]);
    if (!granted) {
      pickerStatus.textContent = "Page access was declined. Choose a tab again to continue.";
      return;
    }
    let snapshot;
    try {
      const [capture] = await chrome.scripting.executeScript({
        target: { tabId: tab.id }, func: inspectPage, args: [tab.url]
      });
      snapshot = capture?.result;
    } finally {
      if (!alreadyGranted) await chrome.permissions.remove(permission);
    }
    if (!snapshot || snapshot.site !== url.hostname) {
      pickerStatus.textContent = "The selected tab changed. Refresh the list and select it again.";
      return;
    }
    await notifyDashboard({ snapshot });
    finished = true;
    const target = await chrome.tabs.get(dashboardTab);
    await chrome.tabs.update(dashboardTab, { active: true });
    await chrome.windows.update(target.windowId, { focused: true });
    window.close();
  } catch {
    pickerStatus.textContent = "Could not read this tab or return to GhostPrint. Check that both tabs are still open.";
  } finally {
    buttons.forEach((button) => { button.disabled = false; });
  }
}

cancelButton.addEventListener("click", async () => {
  try { await notifyDashboard({ canceled: true }); } catch { /* Dashboard was closed. */ }
  finished = true;
  window.close();
});
window.addEventListener("pagehide", () => {
  if (!finished) notifyDashboard({ canceled: true }).catch(() => {});
});

chrome.permissions.contains({ permissions: ["tabs"] }).then(async (granted) => {
  alreadyListed = granted;
  if (!Number.isInteger(dashboardTab) || dashboardTab <= 0 || !dashboardDocument || !auditRequest) return;
  if (granted) await loadTabList();
  listButton.disabled = false;
}).catch(() => {
  listButton.disabled = false;
  pickerStatus.textContent = "Could not list browser tabs. Try again.";
});
