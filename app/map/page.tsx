"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Graph } from "@visx/network";
import { forceCollide, forceLink, forceSimulation, forceX, forceY, type SimulationNodeDatum } from "d3-force";
import { Guard } from "@/components/Guard";
import { useAgent } from "@/lib/ui/store";
import { PII_LABEL } from "@/lib/ui/format";
import type { Flow } from "@/lib/schema";

type Kind = "app" | "company" | "data";
interface N extends SimulationNodeDatum {
  id: string;
  kind: Kind;
  label: string;
  weight: number;
  x: number;
  y: number;
}
interface L {
  source: N;
  target: N;
  weight: number;
  crossApp: boolean;
}

const W = 1000;
const H = 620;
const COL: Record<Kind, number> = { app: 140, company: 500, data: 860 };
const COLOR: Record<Kind, string> = { app: "var(--accent)", company: "var(--danger)", data: "var(--hero)" };

function buildGraph(flows: Flow[], crossCompanies: Set<string>) {
  const nodes = new Map<string, N>();
  const links = new Map<string, { s: string; t: string; weight: number; crossApp: boolean }>();
  const node = (id: string, kind: Kind, label: string) => {
    const n = nodes.get(id) ?? { id, kind, label, weight: 0, x: COL[kind], y: H / 2 };
    n.weight++;
    nodes.set(id, n);
  };
  const link = (s: string, t: string, crossApp = false) => {
    const k = `${s}→${t}`;
    const l = links.get(k) ?? { s, t, weight: 0, crossApp };
    l.weight++;
    l.crossApp ||= crossApp;
    links.set(k, l);
  };
  for (const f of flows) {
    if (!f.tracker && !f.pii.length) continue; // map the data economy, not every CDN hit
    const co = f.company || f.host;
    node(`a:${f.app}`, "app", f.app);
    node(`c:${co}`, "company", co);
    const hasAdid = f.pii.some((p) => p.type === "adid");
    link(`a:${f.app}`, `c:${co}`, hasAdid && crossCompanies.has(co));
    for (const t of new Set(f.pii.map((p) => p.type))) {
      node(`d:${t}`, "data", PII_LABEL[t]);
      link(`c:${co}`, `d:${t}`);
    }
  }
  return { nodes: [...nodes.values()], links: [...links.values()] };
}

function layout(g: ReturnType<typeof buildGraph>): { nodes: N[]; links: L[] } {
  const nodes = g.nodes.map((n) => ({ ...n }));
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const simLinks = g.links.map((l) => ({ source: byId.get(l.s)!, target: byId.get(l.t)!, weight: l.weight, crossApp: l.crossApp }));
  // Deterministic layout: each column gets evenly spaced slots (heaviest in the middle),
  // then a short force pass lets links pull related nodes closer without overlaps.
  const slot = new Map<string, number>();
  for (const kind of ["app", "company", "data"] as Kind[]) {
    const col = nodes.filter((n) => n.kind === kind).sort((a, b) => b.weight - a.weight);
    const order = col.map((_, i) => (i % 2 ? Math.ceil(i / 2) : -Math.ceil(i / 2))); // 0,1,-1,2,-2…
    const step = Math.min(70, (H - 80) / Math.max(1, col.length));
    col.forEach((n, i) => slot.set(n.id, H / 2 + order[i] * step));
  }
  nodes.forEach((n) => (n.y = slot.get(n.id)!));
  forceSimulation(nodes)
    .force("link", forceLink(simLinks).strength(0.02))
    .force("x", forceX<N>((d) => COL[d.kind]).strength(1))
    .force("y", forceY<N>((d) => slot.get(d.id)!).strength(0.5))
    .force("collide", forceCollide<N>(30))
    .stop()
    .tick(200);
  nodes.forEach((n) => (n.y = Math.max(30, Math.min(H - 30, n.y))));
  return { nodes, links: simLinks };
}

export default function MapPage() {
  const flows = useAgent((s) => s.flows);
  const insights = useAgent((s) => s.insights);
  const setFilters = useAgent((s) => s.setFilters);
  const resetFilters = useAgent((s) => s.resetFilters);
  const router = useRouter();
  const [hover, setHover] = useState<string | null>(null);

  const crossCompanies = useMemo(
    () => new Set(Object.values(insights).filter((i) => i.kind === "cross_app").map((i) => String((i.data as { company?: string }).company))),
    [insights],
  );
  // Re-layout only when the graph's structure changes, not on every flow.
  const raw = useMemo(() => buildGraph(flows, crossCompanies), [flows, crossCompanies]);
  const structureKey = raw.nodes.map((n) => n.id).sort().join("|") + "#" + raw.links.map((l) => `${l.s}>${l.t}${l.crossApp ? "!" : ""}`).sort().join("|");
  // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed on structure on purpose
  const graph = useMemo(() => layout(raw), [structureKey]);

  const open = (n: N) => {
    resetFilters();
    if (n.kind === "app") setFilters({ app: n.label });
    else if (n.kind === "company") setFilters({ company: n.label });
    else setFilters({ piiType: n.id.slice(2) });
    router.push("/radar");
  };
  const related = (l: L) => !hover || l.source.id === hover || l.target.id === hover;

  return (
    <Guard>
      <div className="mx-auto max-w-6xl space-y-3 p-4">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div>
            <h1 className="text-lg font-semibold">Shadow Map</h1>
            <p className="text-sm text-muted">Which app feeds which company, and what it gets. Click a node to filter the Radar.</p>
          </div>
          <div className="flex gap-4 text-xs text-muted">
            {(["app", "company", "data"] as Kind[]).map((k) => (
              <span key={k} className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full" style={{ background: COLOR[k] }} />{k === "company" ? "Dementor (company)" : k === "data" ? "Data type" : "App"}</span>
            ))}
            <span className="flex items-center gap-1.5"><span className="h-0.5 w-5 bg-warning" />same ad ID across apps</span>
          </div>
        </div>
        {graph.nodes.length === 0 ? (
          <p className="rounded-xl border border-border bg-surface p-10 text-center text-sm text-muted" data-testid="map-empty">
            Nothing to map yet — the graph appears once trackers or personal data show up.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-border bg-surface">
            <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full min-w-[720px]" role="img" aria-label="Graph of apps, companies and data types" data-testid="shadow-map">
              <Graph<L, N>
                graph={graph}
                linkComponent={({ link }) => (
                  <line
                    x1={link.source.x} y1={link.source.y} x2={link.target.x} y2={link.target.y}
                    stroke={link.crossApp ? "var(--warning)" : "var(--border)"}
                    strokeWidth={Math.min(6, 1 + Math.log2(link.weight + 1)) + (link.crossApp ? 1 : 0)}
                    strokeOpacity={related(link) ? (link.crossApp ? 0.95 : 0.7) : 0.12}
                  />
                )}
                nodeComponent={({ node }) => {
                  const r = 8 + Math.min(16, Math.sqrt(node.weight) * 2.5);
                  return (
                    <g
                      role="button"
                      tabIndex={0}
                      aria-label={`${node.kind} ${node.label}`}
                      className="cursor-pointer"
                      onMouseEnter={() => setHover(node.id)}
                      onMouseLeave={() => setHover(null)}
                      onClick={() => open(node)}
                      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && open(node)}
                    >
                      <circle r={r} fill={`color-mix(in srgb, ${COLOR[node.kind]} 25%, var(--surface))`} stroke={COLOR[node.kind]} strokeWidth={hover === node.id ? 3 : 1.5} />
                      <text
                        x={node.kind === "app" ? -r - 6 : r + 6}
                        y={4}
                        textAnchor={node.kind === "app" ? "end" : "start"}
                        fill="var(--text)"
                        fontSize={12}
                      >
                        {node.label.length > 24 ? node.label.slice(0, 23) + "…" : node.label}
                      </text>
                    </g>
                  );
                }}
              />
            </svg>
          </div>
        )}
      </div>
    </Guard>
  );
}
