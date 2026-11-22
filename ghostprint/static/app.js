const labels = {
  location: "Location", contacts: "Contacts", connections: "Connections",
  messages: "Messages", security: "Network & sessions", activity: "Activity", interests: "Interests",
  sharing: "Off-platform activity", shopping: "Purchases", work: "Employment", education: "Education",
  permissions: "Permissions", identity: "Identity", financial: "Financial"
};
const byId = (id) => document.getElementById(id);

function node(tag, value, parent) {
  const element = document.createElement(tag);
  if (value !== undefined) element.textContent = value;
  if (parent) parent.append(element);
  return element;
}

function linkTo(title, url, target) {
  const link = node("a", title, target);
  link.href = url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
}

function showEvidence(evidence, target) {
  const list = node("ul", undefined, target);
  for (const item of evidence) node("li", `${item.source} · ${item.fact}`, list);
}

function showFixSteps(fix, target) {
  const steps = node("ol", undefined, target);
  for (const step of fix.steps) node("li", step, steps);
  if (fix.url) linkTo("Open platform instructions", fix.url, target);
}

function showReview(analysis, target, source = "the file", coverageLink = true) {
  node("h3", "Findings and fixes", target);
  node("p", analysis.answer, target);
  if (!analysis.claims.length && coverageLink) {
    node("a", "Check import coverage", target).href = "#import-coverage";
  }
  for (const [index, finding] of analysis.claims.entries()) {
    const card = node("article", undefined, target);
    card.className = "finding-card";
    node("h4", `Priority ${index + 1} · ${finding.fix.title}`, card);
    const meta = node("p", undefined, card);
    const severity = node("strong", `${finding.risk.level} risk · ${finding.score}/100`, meta);
    severity.className = "finding-risk";
    node("span", finding.reported ? " · Reported concern" : ` · Evidence found in ${source}`, meta);
    node("p", finding.claim, card);
    node("p", finding.risk.why, card);
    node("h5", "How to fix it", card);
    showFixSteps(finding.fix, card);
    const evidence = node("details", undefined, card);
    node("summary", `Evidence · ${finding.confidence.level} confidence`, evidence);
    node("p", finding.confidence.basis, evidence);
    showEvidence(finding.evidence, evidence);
  }
  if (analysis.insights?.length) {
    const panel = node("details", undefined, target);
    node("summary", "Additional activity and interest signals", panel);
    const list = node("ul", undefined, panel);
    for (const insight of analysis.insights) {
      const item = node("li", `${insight.claim} · ${insight.confidence.level} confidence`, list);
      showEvidence(insight.evidence, item);
    }
  }
  for (const limitation of analysis.limitations) node("p", limitation, target);
}

function showAnalysis(analysis, target) {
  const headline = node("p", analysis.answer, target);
  headline.className = "analysis-answer";
  if (analysis.profile.length) {
    node("h4", "Estimated profile", target);
    const fields = node("ul", "", target);
    for (const item of analysis.profile) {
      node("li", `${item.field} · ${item.value} · ${item.confidence} confidence`, fields);
    }
  }

  node("h4", "Evidence", target);
  if (!analysis.claims.length) node("p", "No matching records in the available evidence.", target);
  for (const claim of analysis.claims) {
    const figure = node("article", "", target);
    node("h5", claim.claim, figure);
    showEvidence(claim.evidence, figure);
    node("p", `Confidence · ${claim.confidence.level} · ${claim.confidence.basis}`, figure);
    node("p", `Risk · ${claim.risk.level} · ${claim.score}/100 · ${claim.risk.why}`, figure);
    node("p", `Recommendation · ${claim.recommendation}`, figure);
  }
  node("h4", "Confidence", target);
  node("p", `${analysis.confidence.level} · ${analysis.confidence.basis}`, target);
  node("h4", "Privacy Risk", target);
  node("p", `${analysis.risk.level} · ${analysis.risk.why}`, target);
  node("h4", "Recommended Action", target);
  if (!analysis.actions.length) node("p", "Import relevant records or narrow your question.", target);
  for (const [number, action] of analysis.actions.entries()) {
    const item = node("article", "", target);
    node("h5", `Priority ${number + 1} · ${action.title}`, item);
    node("p", action.reason, item);
    node("p", `Impact · ${action.impact} · Difficulty · ${action.difficulty}`, item);
    showFixSteps(action, item);
  }
  if (analysis.limitations.length) {
    node("h4", "Limits of the evidence", target);
    const list = node("ul", "", target);
    for (const limitation of analysis.limitations) node("li", limitation, list);
  }
}

function showMap(report, platforms) {
  const table = node("table", undefined, byId("map"));
  const header = node("tr", undefined, node("thead", undefined, table));
  for (const title of ["Platform", ...Object.values(labels)]) {
    node("th", title, header).scope = "col";
  }
  const rows = node("tbody", undefined, table);
  for (const platform of platforms) {
    const row = node("tr", undefined, rows);
    node("th", platform, row).scope = "row";
    for (const category of Object.keys(labels)) {
      const finding = report.findings.find((item) => item.platform === platform && item.category === category);
      const cell = node("td", finding ? undefined : "—", row);
      if (finding) {
        const button = node("button", finding.count.toLocaleString(), cell);
        button.className = "map-cell";
        button.setAttribute("aria-label", `${platform} ${labels[category]}: ${finding.count} records`);
        button.addEventListener("click", () => {
          byId("platform-details").open = true;
          byId("filter").value = platform;
          showActions(report);
          const action = byId(`action-${platform}-${category}`);
          action.open = true;
          action.scrollIntoView({ block: "center" });
          action.querySelector("summary").focus({ preventScroll: true });
        });
      }
    }
  }
}

function showActions(report) {
  const filter = byId("filter").value;
  const list = byId("actions");
  list.replaceChildren();
  for (const item of report.findings) {
    if (filter && item.platform !== filter) continue;
    const details = node("details", undefined, list);
    details.id = `action-${item.platform}-${item.category}`;
    const summary = node("summary", undefined, details);
    const score = node("span", `Priority ${item.priority}/100`, summary);
    score.className = "score";
    node("span", item.guide?.title ?? `Review ${item.platform} ${labels[item.category]}`, summary);
    node("p", `${item.platform} · ${labels[item.category]} · ${item.count.toLocaleString()} records`, details);
    node("p", item.reason, details);
    for (const signal of item.signals) node("p", signal, details);
    if (item.guide) {
      node("p", item.guide.summary, details);
      const steps = node("ol", undefined, details);
      for (const step of item.guide.steps) node("li", step, steps);
      const link = node("a", "Open platform guidance", details);
      link.href = item.guide.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
    } else {
      node("p", "No supported action guide for this category.", details);
    }
    const sources = node("ul", undefined, details);
    sources.setAttribute("aria-label", "Evidence files");
    for (const file of item.sources) node("li", file, sources);
  }
  if (!list.children.length) node("p", "No action items for this audit.", list);
  else list.firstElementChild.open = true;
}

function showPatterns(report) {
  const charts = byId("charts");
  for (const [platform, counts] of Object.entries(report.activity_utc)) {
    const article = node("article", undefined, charts);
    node("h3", `${platform} activity by hour`, article);
    const peak = Math.max(...counts);
    const peaks = counts.flatMap((count, hour) => count === peak ? [`${String(hour).padStart(2, "0")}:00`] : []);
    node("p", `Peak hours in UTC · ${peaks.join(", ")} · ${peak} records per peak hour`, article);
    const canvas = node("canvas", counts.join(", "), article);
    canvas.width = 336;
    canvas.height = 68;
    canvas.setAttribute("role", "img");
    canvas.setAttribute("aria-label", `Records per UTC hour from 00 to 23: ${counts.join(", ")}`);
    const context = canvas.getContext("2d");
    context.fillStyle = "#8fefb1";
    counts.forEach((count, hour) => {
      const height = count ? Math.max(2, 66 * count / peak) : 1;
      context.fillRect(hour * 14, canvas.height - height, 10, height);
    });
    const axis = node("div", undefined, article);
    axis.className = "axis";
    for (const hour of ["00:00", "12:00", "23:00 UTC"]) node("span", hour, axis);
  }
  if (report.interest_signals.length) {
    const article = node("article", undefined, charts);
    node("h3", "Spotify · inferred interests", article);
    node("p", "Repeated artists in the export suggest listening preferences.", article);
    const list = node("ul", undefined, article);
    for (const item of report.interest_signals) node("li", `${item.artist} · ${item.plays} plays`, list);
  }
  byId("patterns").hidden = !charts.children.length;
}

function showCoverage(report) {
  for (const entry of report.coverage) {
    const row = node("article", undefined, byId("coverage"));
    node("h3", `Export ${entry.export} · ${entry.kind}`, row);
    node("p", [
      `${entry.parsed_files} parsed`, `${entry.unrecognized_files} unrecognized`,
      `${entry.empty_or_unsupported_files} empty or unsupported`, `${entry.unreadable_files} unreadable`,
      `${entry.limited_files} over size limits`
    ].join(" · "), row);
    if (entry.file_limit_reached) node("p", "Scan stopped at the per-export file limit.", row);
    for (const note of entry.notes ?? []) node("p", note, row);
  }
}

function showImportInventory(report, target) {
  const inventory = node("details", undefined, target);
  node("summary", "Data examined in this import", inventory);
  const counts = new Map();
  for (const row of report.analyst_sources ?? []) {
    const label = `${row.platform} · ${row.kind}`;
    counts.set(label, (counts.get(label) ?? 0) + row.count);
  }
  if (counts.size) {
    const list = node("ul", undefined, inventory);
    for (const [label, count] of counts) node("li", `${label} · ${count.toLocaleString()} records`, list);
    node("p", "A record can contribute to more than one category.", inventory);
  } else {
    node("p", "No supported data categories were recognized in the files.", inventory);
  }
  const link = node("a", "See parsed, unrecognized, and unreadable files", inventory);
  link.href = "#import-coverage";
}

function showModelDemo(demo) {
  if (!demo) return;
  byId("model-demo").hidden = false;
  const target = byId("model-response");
  node("p", demo.question, target);
  if (demo.error) {
    node("p", `Model bridge unavailable. ${demo.error}`, target);
    return;
  }
  if (!demo.guides.length) {
    node("p", "The model returned no matching guides.", target);
    return;
  }
  const list = node("ol", undefined, target);
  for (const guide of demo.guides) {
    const link = node("a", guide.title, node("li", undefined, list));
    link.href = guide.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
  }
}

let currentReport;

function renderReport(report) {
  currentReport = report;
  for (const pane of ["map", "charts", "coverage", "model-response", "review-result"]) {
    byId(pane).replaceChildren();
  }
  for (const section of document.querySelectorAll("[data-archive-section]")) section.hidden = !!report.live_only;
  byId("model-demo").hidden = true;
  byId("platform-details").open = false;
  byId("automatic-review").hidden = !report.review;
  if (report.review) {
    const score = report.review.score;
    const meter = byId("risk-meter");
    meter.hidden = score == null;
    meter.value = score ?? 0;
    byId("risk-score").textContent = score == null ? "Insufficient evidence" :
      `${score}/100 · ${report.review.risk.level}`;
    showReview(report.review, byId("review-result"));
    showImportInventory(report, byId("review-result"));
  }
  if (report.live_only) {
    byId("status").textContent = "Live browsing session · processed on this laptop";
    return;
  }
  const platforms = [...new Set(report.findings.map((item) => item.platform))].sort();
  byId("status").textContent = report.synthetic
    ? "Synthetic demo · processed on this laptop"
    : `${platforms.length} platforms found across ${report.coverage.length} local exports`;
  if (platforms.length) showMap(report, platforms);
  else node("p", "No supported records were found. Check import coverage below.", byId("map"));
  byId("filter").replaceChildren(new Option("All platforms", ""));
  for (const platform of platforms) {
    node("option", platform, byId("filter")).value = platform;
  }
  showActions(report);
  showPatterns(report);
  showModelDemo(report.model_demo);
  showCoverage(report);
  byId("download").hidden = false;
}

byId("filter").addEventListener("change", () => showActions(currentReport));
byId("download").addEventListener("click", () => {
  const url = URL.createObjectURL(new Blob([JSON.stringify(currentReport, null, 2)], { type: "application/json" }));
  const link = node("a");
  link.href = url;
  link.download = "ghostprint-report.json";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

byId("import-files").addEventListener("change", async (event) => {
  const picker = event.currentTarget;
  const files = [...picker.files];
  if (!files.length) return;
  const status = byId("import-status");
  const platform = byId("import-platform");
  if (files.length > 8 || files.reduce((total, file) => total + file.size, 0) > 512 * 1024 * 1024) {
    status.textContent = "Choose up to eight files with a combined size of 512 MiB or less.";
    picker.value = "";
    return;
  }
  picker.disabled = true;
  platform.disabled = true;
  status.textContent = "Reading selected files and scoring the evidence locally…";
  try {
    const manifest = new TextEncoder().encode(JSON.stringify({
      files: files.map((file) => ({ name: file.name, size: file.size })),
      platform: platform.value || null
    }));
    const length = new DataView(new ArrayBuffer(4));
    length.setUint32(0, manifest.byteLength);
    const body = new Blob([length, manifest, ...files], { type: "application/octet-stream" });
    const response = await fetch("/api/import", { method: "POST", body });
    const report = await response.json();
    if (!response.ok) throw new Error(report.error || "GhostPrint could not import those files.");
    renderReport(report);
    document.dispatchEvent(new Event("ghostprint:report-changed"));
    status.textContent = report.review.score == null ? "Import complete. No supported records were found." : "Analysis complete.";
    byId("review-heading").focus();
  } catch (error) {
    status.textContent = error instanceof TypeError ? "Could not reach GhostPrint. Check that the local dashboard is running." : error.message;
  } finally {
    picker.value = "";
    picker.disabled = false;
    platform.disabled = false;
  }
});

async function load() {
  const response = await fetch("/api/report");
  if (!response.ok) throw new Error("Report unavailable");
  const report = await response.json();
  if (!currentReport) renderReport(report);
}

load().catch(() => {
  byId("status").textContent = "Could not load the local audit. Check that GhostPrint is still running.";
});
