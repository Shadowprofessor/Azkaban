const websiteForm = byId("website-form");
const websiteStatus = byId("website-status");
const websiteResults = byId("website-results");
const checkWebsite = byId("check-website");

const browserDataLabels = {
  email: "Email addresses", phone: "Phone numbers", name: "Names", address: "Postal addresses",
  payment: "Payment details", credentials: "Account credentials", identifiers: "Device or advertising identifiers",
  ip: "IP addresses", activity: "Browsing or search activity", location: "Location data"
};
const statementActions = {
  collect: "Collection", store: "Storage or retention", share: "Sharing", sell: "Sale", use: "Use"
};
const statementStances = {
  disclosed: "Disclosed", denied: "Denied", qualified: "Read the scope and exceptions",
  qualified_denial: "Denial with qualifications"
};

function showQuote(statement, target) {
  const quote = node("blockquote", statement.quote, target);
  quote.className = "policy-quote";
  linkTo(statement.document, statement.source, target);
}

function summarizeStatements(statements) {
  const summaries = [];
  for (const [action, items] of Map.groupBy(statements, (item) => item.action)) {
    const stances = new Set(items.map((item) => item.stance));
    const position = stances.size > 1 ? "scope varies" :
      stances.has("denied") ? "denied" :
      stances.has("qualified_denial") ? "qualified denial" :
      stances.has("qualified") ? "disclosed with conditions" : "disclosed";
    summaries.push(`${statementActions[action]} ${position}`);
  }
  return summaries.join(", ");
}

function showWebsite(result) {
  if (result.risks.length) {
    node("h3", "Potential exposure to check", websiteResults);
    for (const risk of result.risks) {
      const card = node("article", undefined, websiteResults);
      card.className = "policy-alert";
      node("h4", risk.title, card);
      node("p", risk.detail, card);
      node("p", risk.action, card);
    }
  }
  node("h3", "Policy comparison", websiteResults);
  if (!result.observation) {
    node("p", "No browser snapshot is available for this hostname. The results below describe the public documents.", websiteResults);
  } else if (!result.comparisons.length) {
    node("p", "The snapshot had no comparable fields or storage observations.", websiteResults);
  } else {
    for (const comparison of result.comparisons) {
      const card = node("article", undefined, websiteResults);
      if (comparison.status === "Possible mismatch") card.className = "policy-alert";
      node("h4", `${comparison.status} · ${comparison.data}`, card);
      node("p", comparison.evidence, card);
      node("p", comparison.note, card);
      for (const statement of comparison.statements) showQuote(statement, card);
    }
  }
  node("p", "These comparisons cover the available text and this snapshot. A mismatch needs investigation and does not prove a leak. A match does not establish compliance, consent, or server retention.", websiteResults);

  node("h3", "What the website says about your data", websiteResults);
  if (!result.statements.length) node("p", "No clear data statements could be extracted from the pages read.", websiteResults);
  const grouped = Map.groupBy(result.statements, (item) => item.data);
  for (const [data, statements] of grouped) {
    const summary = node("details", undefined, websiteResults);
    node("summary", `${data} · ${summarizeStatements(statements)}`, summary);
    for (const statement of statements) {
      node("p", `${statementActions[statement.action]} · ${statementStances[statement.stance]}`, summary);
      showQuote(statement, summary);
    }
  }
  if (result.retention.length) {
    const details = node("details", undefined, websiteResults);
    node("summary", "How long the site says it keeps data", details);
    for (const row of result.retention) showQuote(row, details);
  }
  if (result.observation) {
    const details = node("details", undefined, websiteResults);
    node("summary", "Browser evidence captured on this laptop", details);
    const snapshot = result.observation;
    node("p", `Captured ${new Date(snapshot.seen).toLocaleString()}`, details);
    if (snapshot.forms.length) node("p", `Visible form categories · ${snapshot.forms.map((key) => browserDataLabels[key]).join(", ")}`, details);
    const granted = Object.entries(snapshot.permissions).filter(([, state]) => state === "granted").map(([name]) => name);
    if (granted.length) node("p", `Granted browser permissions · ${granted.join(", ")}. These permissions alone do not show use.`, details);
    const { local, session } = snapshot.storage;
    node("p", `Browser storage entries · Local ${local ?? "unavailable"}, session ${session ?? "unavailable"}`, details);
    if (snapshot.hosts.length) {
      node("p", "Other hostnames in resource URLs", details);
      const hosts = node("ul", undefined, details);
      for (const host of snapshot.hosts) node("li", host, hosts);
    }
  }
  node("h3", "Documents checked", websiteResults);
  const documents = node("ul", undefined, websiteResults);
  for (const item of result.documents) {
    const row = node("li", `${item.kind} · ${item.status}`, documents);
    if (item.url) {
      row.append(" · ");
      linkTo("Open original", item.url, row);
    } else {
      row.append(` · ${item.detail}`);
    }
  }
}

websiteForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  checkWebsite.disabled = true;
  websiteResults.replaceChildren();
  websiteStatus.textContent = "Reading public policies and checking available evidence…";
  try {
    const response = await fetch("/api/site/check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        website: byId("policy-website").value.trim(),
        privacy_url: byId("policy-privacy").value.trim() || null,
        terms_url: byId("policy-terms").value.trim() || null
      })
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Could not check the site.");
    websiteStatus.textContent = `Check complete for ${result.site}`;
    showWebsite(result);
  } catch (error) {
    websiteStatus.textContent = error instanceof TypeError ? "Could not reach the local GhostPrint dashboard." : error.message;
  } finally {
    checkWebsite.disabled = false;
  }
});
