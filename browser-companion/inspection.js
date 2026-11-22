async function inspectPage(expectedUrl, liveResources) {
  if (expectedUrl && location.href !== expectedUrl) return null;
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
  const entries = performance.getEntriesByType("navigation").slice(0, 1)
    .concat((liveResources ?? performance.getEntriesByType("resource")).slice(-499));
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
  if (expectedUrl && location.href !== expectedUrl) return null;
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
