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

async function inspectPage() {
  const pattern = /^\/(?:[a-z]{2}(?:-[a-z]{2})?\/)?(?:legal\/|policies\/)?(?:privacy(?:[-_]policy|[-_]notice)?|data[-_]deletion|delete[-_]account|cookie[-_]policy|cookies|terms(?:[-_]of[-_](?:use|service)|[-_]and[-_]conditions)?|user[-_]agreement)(?:\.html?)?\/?$/i;
  const links = new Set();
  for (const anchor of document.querySelectorAll("a[href]")) {
    if (!URL.canParse(anchor.href, location.href)) continue;
    const url = new URL(anchor.href, location.href);
    if (url.origin === location.origin && pattern.test(url.pathname)) {
      links.add(url.origin + url.pathname);
      if (links.size >= 8) break;
    }
  }
  const names = ["camera", "microphone", "geolocation", "notifications"];
  const permissions = {};
  if (navigator.permissions) {
    await Promise.all(names.map(async (name) => {
      try {
        permissions[name] = (await navigator.permissions.query({ name })).state;
      } catch {
        // The browser may omit a permission type from its Permissions API.
      }
    }));
  }
  const categories = {
    email: "email", emailaddress: "email", useremail: "email",
    tel: "phone", phone: "phone", phonenumber: "phone", mobilephone: "phone",
    fullname: "name", firstname: "name", lastname: "name", givenname: "name", familyname: "name",
    streetaddress: "address", shippingaddress: "address", billingaddress: "address",
    ccnumber: "payment", cardnumber: "payment", creditcardnumber: "payment",
    password: "credentials", currentpassword: "credentials", newpassword: "credentials", sessiontoken: "credentials",
    deviceid: "identifiers", advertisingid: "identifiers", mobileadvertisingid: "identifiers",
    ipaddress: "ip", clientip: "ip", searchquery: "activity", searchterm: "activity",
    gpslatitude: "location", gpslongitude: "location", latitude: "location", longitude: "location"
  };
  const categoryFor = (key) => {
    const normalized = key.toLowerCase().replace(/[^a-z0-9]/g, "");
    return Object.hasOwn(categories, normalized) ? categories[normalized] : undefined;
  };
  const forms = new Set();
  for (const control of [...document.querySelectorAll("input,textarea,select")].slice(0, 500)) {
    if (control.type === "hidden" || !control.getClientRects().length) continue;
    for (const label of [control.type || "", control.name || "", ...(control.autocomplete?.split(/\s+/) ?? [])]) {
      const category = categoryFor(label);
      if (category) forms.add(category);
    }
  }
  const hosts = new Set();
  const seen = new Map();
  const entries = performance.getEntriesByType("navigation").concat(performance.getEntriesByType("resource")).slice(0, 500);
  for (const entry of entries) {
    if (!URL.canParse(entry.name)) continue;
    const url = new URL(entry.name);
    if (!["https:", "http:"].includes(url.protocol) || !/\.[a-z][a-z0-9-]*$/i.test(url.hostname)) continue;
    if (url.hostname !== location.hostname && hosts.size < 20) hosts.add(url.hostname);
    const matched = new Set();
    for (const key of url.searchParams.keys()) {
      const category = categoryFor(key);
      if (category && url.searchParams.get(key)?.trim()) matched.add(category);
      if (matched.size >= 10) break;
    }
    for (const category of matched) {
      const key = `${url.hostname}:${category}`;
      const found = seen.get(key);
      if (found) found.count++;
      else if (seen.size < 24) seen.set(key, { host: url.hostname, category, count: 1 });
    }
  }
  const storageCount = (type) => {
    try { return window[type].length; } catch { return null; }
  };
  return {
    site: location.hostname,
    links: [...links],
    permissions,
    observation: {
      forms: [...forms], requests: [...seen.values()], hosts: [...hosts],
      storage: { local: storageCount("localStorage"), session: storageCount("sessionStorage") }
    }
  };
}

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

chrome.storage.session.get("settings").then((data) => {
  settings = data.settings ?? {};
  field("port").value = settings.port ?? 8765;
  field("code").value = settings.code ?? "";
  showState();
  field("toggle").disabled = false;
  field("inspect").disabled = false;
});
