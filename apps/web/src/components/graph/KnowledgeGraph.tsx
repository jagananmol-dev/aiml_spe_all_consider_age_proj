"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FileText, Loader, RefreshCw, Search, X } from "lucide-react";
import {
  fitView,
  layoutNatural,
  neighbourhood,
  nodeRadius,
  type GraphEdge,
  type GraphNode,
  type Point,
} from "@/lib/graphLayout";

/**
 * Knowledge Graph view.
 *
 * Loads the tenant's whole graph once, lays it out with a force simulation
 * (linked entities pull together, everything else pushes apart, and every
 * node keeps the room its label needs) and lets the user search, focus a
 * node's neighbourhood, drag nodes, zoom and pan. Document nodes (each
 * uploaded file and the entities it mentions) can be shown or hidden.
 */

/** Entity type labels, colours and roles come from the tenant's graph schema. */
interface TypeInfo {
  label: string;
  color: string | null;
  role: string | null;
}

// Colours for types the schema gives none (e.g. a tenant's own types)
const FALLBACK_COLORS = [
  "#0f766e",
  "#a16207",
  "#be185d",
  "#4338ca",
  "#15803d",
  "#9a3412",
  "#475569",
];

function fallbackColor(type: string): string {
  let hash = 0;
  for (const ch of type) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return FALLBACK_COLORS[hash % FALLBACK_COLORS.length];
}

function titleCase(type: string): string {
  return type
    .toLowerCase()
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

const WIDTH = 1000;
const HEIGHT = 640;

interface View {
  x: number;
  y: number;
  k: number;
}

export function KnowledgeGraph() {
  const [graph, setGraph] = useState<{ nodes: GraphNode[]; edges: GraphEdge[] }>({
    nodes: [],
    edges: [],
  });
  const [types, setTypes] = useState<Record<string, TypeInfo>>({});
  const [showDocuments, setShowDocuments] = useState(true);
  const [layoutSize, setLayoutSize] = useState({ width: 0, height: 0 });
  const [positions, setPositions] = useState<Record<string, Point>>({});
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [view, setView] = useState<View>({ x: 0, y: 0, k: 1 });
  const svgRef = useRef<SVGSVGElement>(null);
  const drag = useRef<{
    kind: "pan" | "node";
    id?: string;
    x: number;
    y: number;
    moved: boolean;
  } | null>(null);

  const load = useCallback(async () => {
    setStatus("loading");
    setError("");
    try {
      const res = await fetch("/api/graph/overview", { cache: "no-store" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not load the knowledge graph");
      setGraph({ nodes: data.nodes, edges: data.edges });
      setTypes(data.types ?? {});
      setSelected(null);
      setStatus("ready");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the knowledge graph");
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const styleOf = useCallback(
    (type: string) => ({
      color: types[type]?.color ?? fallbackColor(type),
      label: types[type]?.label ?? titleCase(type),
    }),
    [types]
  );
  const isSubject = useCallback(
    (type?: string) => !!type && types[type]?.role === "subject",
    [types]
  );
  const isDocument = useCallback((type: string) => types[type]?.role === "document", [types]);
  const documentCount = useMemo(
    () => graph.nodes.filter((n) => isDocument(n.type)).length,
    [graph, isDocument]
  );

  // The visible graph: optionally without document nodes (degrees recounted)
  const { nodes, edges } = useMemo(() => {
    if (showDocuments) return graph;
    const hidden = new Set(graph.nodes.filter((n) => isDocument(n.type)).map((n) => n.id));
    const kept = graph.edges.filter((e) => !hidden.has(e.source) && !hidden.has(e.target));
    const degree: Record<string, number> = {};
    for (const e of kept) {
      degree[e.source] = (degree[e.source] ?? 0) + 1;
      degree[e.target] = (degree[e.target] ?? 0) + 1;
    }
    return {
      nodes: graph.nodes
        .filter((n) => !hidden.has(n.id) && degree[n.id])
        .map((n) => ({ ...n, degree: degree[n.id] })),
      edges: kept,
    };
  }, [graph, showDocuments, isDocument]);

  // Lay out at natural scale (nothing overlaps), then zoom to fit
  useEffect(() => {
    const layout = layoutNatural(nodes, edges, (t) => types[t]?.role === "subject");
    setPositions(layout.positions);
    setLayoutSize({ width: layout.width, height: layout.height });
    setView(fitView(layout, WIDTH, HEIGHT));
  }, [nodes, edges, types]);

  const radius = useCallback(
    (n: GraphNode | undefined) => nodeRadius(n, isSubject(n?.type)),
    [isSubject]
  );

  const byId = useMemo(() => Object.fromEntries(nodes.map((n) => [n.id, n])), [nodes]);
  const focus = useMemo(
    () => (selected ? neighbourhood(selected, edges, 1) : null),
    [selected, edges]
  );
  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? nodes.filter((n) => n.label.toLowerCase().includes(q)) : [];
  }, [query, nodes]);
  const matchIds = useMemo(() => new Set(matches.map((n) => n.id)), [matches]);
  const typeCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const n of nodes) counts[n.type] = (counts[n.type] ?? 0) + 1;
    return counts;
  }, [nodes]);
  const selectedEdges = useMemo(
    () => (selected ? edges.filter((e) => e.source === selected || e.target === selected) : []),
    [selected, edges]
  );

  // ── Pointer interaction ───────────────────────────
  const toGraph = (clientX: number, clientY: number): Point => {
    const rect = svgRef.current!.getBoundingClientRect();
    const sx = ((clientX - rect.left) / rect.width) * WIDTH;
    const sy = ((clientY - rect.top) / rect.height) * HEIGHT;
    return { x: (sx - view.x) / view.k, y: (sy - view.y) / view.k };
  };

  const onPointerDown = (e: React.PointerEvent, id?: string) => {
    e.stopPropagation();
    (e.target as Element).setPointerCapture?.(e.pointerId);
    drag.current = { kind: id ? "node" : "pan", id, x: e.clientX, y: e.clientY, moved: false };
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    if (Math.abs(e.clientX - d.x) + Math.abs(e.clientY - d.y) > 3) d.moved = true;
    if (d.kind === "node" && d.id) {
      const p = toGraph(e.clientX, e.clientY);
      setPositions((prev) => ({ ...prev, [d.id!]: p }));
    } else {
      const rect = svgRef.current!.getBoundingClientRect();
      const dx = ((e.clientX - d.x) / rect.width) * WIDTH;
      const dy = ((e.clientY - d.y) / rect.height) * HEIGHT;
      d.x = e.clientX;
      d.y = e.clientY;
      setView((v) => ({ ...v, x: v.x + dx, y: v.y + dy }));
    }
  };

  const onPointerUp = () => {
    const d = drag.current;
    drag.current = null;
    if (d && !d.moved) setSelected(d.kind === "node" ? (d.id ?? null) : null);
  };

  const onWheel = (e: React.WheelEvent) => {
    const rect = svgRef.current!.getBoundingClientRect();
    const sx = ((e.clientX - rect.left) / rect.width) * WIDTH;
    const sy = ((e.clientY - rect.top) / rect.height) * HEIGHT;
    setView((v) => {
      const k = Math.min(4, Math.max(0.08, v.k * (e.deltaY < 0 ? 1.15 : 1 / 1.15)));
      return { k, x: sx - ((sx - v.x) * k) / v.k, y: sy - ((sy - v.y) * k) / v.k };
    });
  };

  const focusNode = (id: string) => {
    setSelected(id);
    const p = positions[id];
    if (p) setView({ k: 1.6, x: WIDTH / 2 - p.x * 1.6, y: HEIGHT / 2 - p.y * 1.6 });
  };

  const dimmed = (id: string) => (focus ? !focus.has(id) : matchIds.size > 0 && !matchIds.has(id));

  // ── Render ────────────────────────────────────────
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 300px", gap: "1rem" }}>
      <div>
        <div
          style={{ display: "flex", gap: "0.5rem", marginBottom: "0.75rem", alignItems: "center" }}
        >
          <div style={{ position: "relative", flex: 1, maxWidth: 420 }}>
            <Search
              size={14}
              style={{ position: "absolute", left: 10, top: 11, color: "#737373" }}
            />
            <input
              type="search"
              placeholder="Search entities (e.g. HD-K04, endotoxin, vancomycin)"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && matches[0]) focusNode(matches[0].id);
              }}
              style={{
                width: "100%",
                padding: "0.55rem 0.8rem 0.55rem 2rem",
                border: "1px solid #d4d4d4",
                borderRadius: 4,
                fontSize: "0.85rem",
                background: "#fafafa",
              }}
            />
          </div>
          {query && (
            <span style={{ fontSize: "0.75rem", color: "#737373" }}>
              {matches.length} match{matches.length === 1 ? "" : "es"} · Enter to focus
            </span>
          )}
          <button type="button" onClick={load} style={toolButton} title="Reload graph">
            <RefreshCw size={13} /> Refresh
          </button>
          <button
            type="button"
            onClick={() => {
              setSelected(null);
              setQuery("");
              setView(fitView(layoutSize, WIDTH, HEIGHT));
            }}
            style={toolButton}
          >
            Fit
          </button>
          {documentCount > 0 && (
            <label style={{ ...toolButton, cursor: "pointer" }}>
              <input
                type="checkbox"
                checked={showDocuments}
                onChange={(e) => setShowDocuments(e.target.checked)}
              />
              Documents ({documentCount})
            </label>
          )}
        </div>

        <div
          style={{
            border: "1px solid #e5e5e5",
            borderRadius: 6,
            background: "#ffffff",
            position: "relative",
            overflow: "hidden",
          }}
        >
          {status === "loading" && (
            <div style={centered}>
              <Loader size={16} className="animate-spin" /> Loading knowledge graph…
            </div>
          )}
          {status === "error" && <div style={{ ...centered, color: "#991b1b" }}>{error}</div>}
          {status === "ready" && nodes.length === 0 && (
            <div style={centered}>
              No graph yet. Upload documents and it will build as they are processed.
            </div>
          )}
          {status === "ready" && nodes.length > 0 && (
            <svg
              ref={svgRef}
              viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
              style={{
                width: "100%",
                height: 560,
                display: "block",
                cursor: "grab",
                touchAction: "none",
              }}
              onPointerDown={(e) => onPointerDown(e)}
              onPointerMove={onPointerMove}
              onPointerUp={onPointerUp}
              onWheel={onWheel}
              role="img"
              aria-label="Knowledge graph"
            >
              <defs>
                <marker
                  id="kg-arrow"
                  viewBox="0 0 10 10"
                  refX="10"
                  refY="5"
                  markerWidth="6"
                  markerHeight="6"
                  orient="auto"
                >
                  <path d="M0,0 L10,5 L0,10 z" fill="#a3a3a3" />
                </marker>
              </defs>
              <g transform={`translate(${view.x},${view.y}) scale(${view.k})`}>
                {edges.map((e, i) => {
                  const a = positions[e.source];
                  const b = positions[e.target];
                  if (!a || !b) return null;
                  const active = selected && (e.source === selected || e.target === selected);
                  const faded = dimmed(e.source) || dimmed(e.target);
                  const len = Math.hypot(b.x - a.x, b.y - a.y) || 1;
                  const r = radius(byId[e.target]);
                  const ex = b.x - ((b.x - a.x) / len) * (r + 2);
                  const ey = b.y - ((b.y - a.y) / len) * (r + 2);
                  return (
                    <g key={i} opacity={faded ? 0.08 : 1}>
                      <line
                        x1={a.x}
                        y1={a.y}
                        x2={ex}
                        y2={ey}
                        stroke={active ? "#111827" : "#d4d4d4"}
                        strokeWidth={active ? 1.6 : 1}
                        markerEnd="url(#kg-arrow)"
                      />
                      {active && (
                        <text
                          x={(a.x + b.x) / 2}
                          y={(a.y + b.y) / 2 - 4}
                          fontSize={9}
                          textAnchor="middle"
                          fill="#525252"
                          style={{ pointerEvents: "none" }}
                        >
                          {e.relationship.replace(/_/g, " ").toLowerCase()}
                        </text>
                      )}
                    </g>
                  );
                })}
                {nodes.map((n) => {
                  const p = positions[n.id];
                  if (!p) return null;
                  const s = styleOf(n.type);
                  const isSelected = n.id === selected;
                  const isMatch = matchIds.has(n.id);
                  // Zoomed far out, only labels that matter stay (no clutter)
                  const showLabel =
                    view.k >= 0.6 ||
                    isSelected ||
                    isMatch ||
                    isSubject(n.type) ||
                    (focus?.has(n.id) ?? false) ||
                    n.degree >= 6;
                  return (
                    <g
                      key={n.id}
                      transform={`translate(${p.x},${p.y})`}
                      opacity={dimmed(n.id) ? 0.12 : 1}
                      style={{ cursor: "pointer" }}
                      onPointerDown={(e) => onPointerDown(e, n.id)}
                    >
                      <circle
                        r={radius(n)}
                        fill={s.color}
                        stroke={isSelected || isMatch ? "#facc15" : "#ffffff"}
                        strokeWidth={isSelected || isMatch ? 3 : 1.5}
                      />
                      {showLabel && (
                        <text
                          y={radius(n) + 11}
                          fontSize={isSubject(n.type) ? 11 : 9}
                          fontWeight={isSubject(n.type) ? 700 : 500}
                          textAnchor="middle"
                          fill="#111827"
                          style={{
                            pointerEvents: "none",
                            paintOrder: "stroke",
                            stroke: "#ffffff",
                            strokeWidth: 3,
                          }}
                        >
                          {n.label}
                        </text>
                      )}
                      <title>{`${n.label} — ${styleOf(n.type).label}`}</title>
                    </g>
                  );
                })}
              </g>
            </svg>
          )}
          <div
            style={{
              position: "absolute",
              bottom: 8,
              left: 10,
              fontSize: "0.7rem",
              color: "#a3a3a3",
            }}
          >
            Drag to move · scroll to zoom · click a node to focus
          </div>
        </div>
      </div>

      <aside
        style={{
          border: "1px solid #e5e5e5",
          borderRadius: 6,
          padding: "1rem",
          background: "#fafafa",
          fontSize: "0.8rem",
        }}
      >
        {selected && byId[selected] ? (
          <>
            <div
              style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}
            >
              <div>
                <div
                  style={{
                    fontSize: "0.7rem",
                    color: styleOf(byId[selected].type).color,
                    fontWeight: 700,
                  }}
                >
                  {styleOf(byId[selected].type).label.toUpperCase()}
                </div>
                <div style={{ fontSize: "1rem", fontWeight: 800 }}>{byId[selected].label}</div>
              </div>
              <button
                type="button"
                onClick={() => setSelected(null)}
                style={{ ...toolButton, padding: "0.2rem" }}
                aria-label="Close"
              >
                <X size={14} />
              </button>
            </div>
            <div style={{ marginTop: "0.75rem", color: "#737373" }}>
              {selectedEdges.length} relationship(s)
            </div>
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: "0.6rem",
                marginTop: "0.5rem",
              }}
            >
              {selectedEdges.map((e, i) => {
                const other = byId[e.source === selected ? e.target : e.source];
                return (
                  <div key={i} style={{ borderTop: "1px solid #e5e5e5", paddingTop: "0.5rem" }}>
                    <div>
                      <strong>{byId[e.source]?.label}</strong>{" "}
                      <span style={{ color: "#737373" }}>
                        {e.relationship.replace(/_/g, " ").toLowerCase()}
                      </span>{" "}
                      <button type="button" onClick={() => focusNode(other.id)} style={linkButton}>
                        {byId[e.target]?.label}
                      </button>
                    </div>
                    {e.documents.map((d) => (
                      <div
                        key={d}
                        style={{
                          display: "flex",
                          gap: 4,
                          alignItems: "center",
                          color: "#737373",
                          fontSize: "0.7rem",
                          marginTop: 2,
                        }}
                      >
                        <FileText size={10} /> {d}
                      </div>
                    ))}
                  </div>
                );
              })}
            </div>
          </>
        ) : (
          <>
            <div style={{ fontWeight: 800, fontSize: "0.95rem" }}>Graph summary</div>
            <div style={{ color: "#737373", margin: "0.25rem 0 0.75rem" }}>
              {nodes.length} entities · {edges.length} relationships
            </div>
            {Object.entries(typeCounts)
              .sort((a, b) => b[1] - a[1])
              .map(([type, count]) => (
                <div
                  key={type}
                  style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}
                >
                  <span
                    style={{
                      width: 10,
                      height: 10,
                      borderRadius: "50%",
                      background: styleOf(type).color,
                    }}
                  />
                  <span style={{ flex: 1 }}>{styleOf(type).label}</span>
                  <span style={{ color: "#737373" }}>{count}</span>
                </div>
              ))}
            <div style={{ marginTop: "1rem", fontWeight: 700 }}>Most connected</div>
            {[...nodes]
              .sort((a, b) => b.degree - a.degree)
              .slice(0, 6)
              .map((n) => (
                <button
                  key={n.id}
                  type="button"
                  onClick={() => focusNode(n.id)}
                  style={{ ...linkButton, display: "block", marginTop: 4 }}
                >
                  {n.label} ({n.degree})
                </button>
              ))}
          </>
        )}
      </aside>
    </div>
  );
}

const toolButton: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 4,
  padding: "0.45rem 0.7rem",
  border: "1px solid #d4d4d4",
  borderRadius: 4,
  background: "#ffffff",
  fontSize: "0.75rem",
  cursor: "pointer",
};
const linkButton: React.CSSProperties = {
  background: "none",
  border: "none",
  padding: 0,
  color: "#111827",
  textDecoration: "underline",
  cursor: "pointer",
  fontSize: "0.8rem",
  textAlign: "left",
};
const centered: React.CSSProperties = {
  height: 560,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  gap: 8,
  color: "#737373",
};
