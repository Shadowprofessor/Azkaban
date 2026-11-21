const labels = {
  location: "Location", contacts: "Contacts", connections: "Connections",
  messages: "Messages", security: "Network & sessions", activity: "Activity", interests: "Interests",
  sharing: "Off-platform activity", shopping: "Purchases", work: "Employment", education: "Education"
};
const byId = (id) => document.getElementById(id);

function node(tag, value, parent) {
  const element = document.createElement(tag);
  if (value !== undefined) element.textContent = value;
  if (parent) parent.append(element);
  return element;
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
    const score = node("span", `${item.priority}/100`, summary);
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
  }
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

async function load() {
  const response = await fetch("/api/report");
  if (!response.ok) throw new Error("Report unavailable");
  const report = await response.json();
  if (report.live_only) {
    byId("status").textContent = "Live browsing session · processed on this laptop";
    for (const section of document.querySelectorAll("[data-archive-section]")) section.hidden = true;
    return;
  }
  const platforms = [...new Set(report.findings.map((item) => item.platform))].sort();
  byId("status").textContent = report.synthetic
    ? "Synthetic demo · processed on this laptop"
    : `${platforms.length} platforms found across ${report.coverage.length} local exports`;
  if (platforms.length) showMap(report, platforms);
  else node("p", "No supported records were found. Check import coverage below.", byId("map"));
  for (const platform of platforms) {
    node("option", platform, byId("filter")).value = platform;
  }
  byId("filter").addEventListener("change", () => showActions(report));
  showActions(report);
  showPatterns(report);
  showModelDemo(report.model_demo);
  showCoverage(report);
  const download = byId("download");
  download.hidden = false;
  download.addEventListener("click", () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: "application/json" }));
    const link = node("a");
    link.href = url;
    link.download = "ghostprint-report.json";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
}

load().catch(() => {
  byId("status").textContent = "Could not load the local audit. Check that GhostPrint is still running.";
});
