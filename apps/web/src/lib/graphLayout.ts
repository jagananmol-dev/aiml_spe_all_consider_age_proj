/**
 * VEDA AI — Knowledge graph layout
 *
 * Deterministic force-directed layout for the Knowledge Graph view:
 * - each connected component (a machine with its alarms, fixes and readings)
 *   gets its own area, larger components nearer the middle
 * - inside a component, linked nodes pull together (springs) and all nodes
 *   push apart (repulsion), so relationships read as clusters, not a ring
 * - the result is scaled to fit the drawing area
 *
 * No randomness: the same graph always gets the same picture.
 */

export interface GraphNode {
  id: string;
  label: string;
  type: string;
  degree: number;
}

export interface GraphEdge {
  source: string;
  target: string;
  relationship: string;
  confidence: number;
  documents: string[];
}

export interface Point {
  x: number;
  y: number;
}

/** Connected components, largest first. */
export function components(nodes: GraphNode[], edges: GraphEdge[]): string[][] {
  const adjacency = new Map<string, string[]>(nodes.map((n) => [n.id, []]));
  for (const e of edges) {
    adjacency.get(e.source)?.push(e.target);
    adjacency.get(e.target)?.push(e.source);
  }
  const seen = new Set<string>();
  const result: string[][] = [];
  for (const n of nodes) {
    if (seen.has(n.id)) continue;
    const group: string[] = [];
    const stack = [n.id];
    seen.add(n.id);
    while (stack.length) {
      const id = stack.pop()!;
      group.push(id);
      for (const next of adjacency.get(id) ?? []) {
        if (!seen.has(next)) {
          seen.add(next);
          stack.push(next);
        }
      }
    }
    result.push(group);
  }
  return result.sort((a, b) => b.length - a.length || a[0].localeCompare(b[0]));
}

/** Ids within `hops` links of `id`, including `id`. */
export function neighbourhood(id: string, edges: GraphEdge[], hops = 1): Set<string> {
  const found = new Set([id]);
  let frontier = [id];
  for (let h = 0; h < hops; h++) {
    const next: string[] = [];
    for (const e of edges) {
      for (const [from, to] of [
        [e.source, e.target],
        [e.target, e.source],
      ]) {
        if (frontier.includes(from) && !found.has(to)) {
          found.add(to);
          next.push(to);
        }
      }
    }
    frontier = next;
  }
  return found;
}

function layoutComponent(ids: string[], edges: GraphEdge[]): Record<string, Point> {
  const n = ids.length;
  const index = new Map(ids.map((id, i) => [id, i]));
  const pos = ids.map((_, i) => {
    const angle = (2 * Math.PI * i) / n;
    const r = 20 + 6 * Math.sqrt(n);
    return { x: r * Math.cos(angle), y: r * Math.sin(angle) };
  });
  const links = edges
    .filter((e) => index.has(e.source) && index.has(e.target))
    .map((e) => [index.get(e.source)!, index.get(e.target)!] as const);

  const ideal = 70;
  const iterations = n > 300 ? 120 : 300;
  for (let it = 0; it < iterations; it++) {
    const cooling = 1 - it / iterations;
    const force = pos.map(() => ({ x: 0, y: 0 }));
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const dx = pos[i].x - pos[j].x;
        const dy = pos[i].y - pos[j].y;
        const d2 = Math.max(dx * dx + dy * dy, 1);
        const push = (ideal * ideal) / d2;
        force[i].x += dx * push * 0.05;
        force[i].y += dy * push * 0.05;
        force[j].x -= dx * push * 0.05;
        force[j].y -= dy * push * 0.05;
      }
    }
    for (const [a, b] of links) {
      const dx = pos[b].x - pos[a].x;
      const dy = pos[b].y - pos[a].y;
      const d = Math.max(Math.hypot(dx, dy), 1);
      const pull = ((d - ideal) / d) * 0.1;
      force[a].x += dx * pull;
      force[a].y += dy * pull;
      force[b].x -= dx * pull;
      force[b].y -= dy * pull;
    }
    for (let i = 0; i < n; i++) {
      force[i].x -= pos[i].x * 0.01; // gentle gravity to the component centre
      force[i].y -= pos[i].y * 0.01;
      const step = Math.hypot(force[i].x, force[i].y);
      const max = 12 * cooling + 0.5;
      const scale = step > max ? max / step : 1;
      pos[i].x += force[i].x * scale;
      pos[i].y += force[i].y * scale;
    }
  }
  return Object.fromEntries(ids.map((id, i) => [id, pos[i]]));
}

/** Positions for every node, fitted inside width × height with a margin. */
export function layoutGraph(
  nodes: GraphNode[],
  edges: GraphEdge[],
  width: number,
  height: number,
  margin = 50
): Record<string, Point> {
  if (nodes.length === 0) return {};
  const groups = components(nodes, edges).map((ids) => {
    const local = layoutComponent(ids, edges);
    const xs = ids.map((id) => local[id].x);
    const ys = ids.map((id) => local[id].y);
    const box = { minX: Math.min(...xs), minY: Math.min(...ys), w: 0, h: 0 };
    box.w = Math.max(...xs) - box.minX;
    box.h = Math.max(...ys) - box.minY;
    return { ids, local, box };
  });

  // Shelf-pack the components left to right, wrapping rows to the aspect ratio
  const gap = 90;
  const totalArea = groups.reduce((s, g) => s + (g.box.w + gap) * (g.box.h + gap), 0);
  const rowWidth = Math.max(Math.sqrt(totalArea * (width / height)), groups[0].box.w + gap);
  const placed: Record<string, Point> = {};
  let x = 0;
  let y = 0;
  let rowHeight = 0;
  for (const g of groups) {
    if (x > 0 && x + g.box.w > rowWidth) {
      x = 0;
      y += rowHeight + gap;
      rowHeight = 0;
    }
    for (const id of g.ids) {
      placed[id] = { x: x + g.local[id].x - g.box.minX, y: y + g.local[id].y - g.box.minY };
    }
    x += g.box.w + gap;
    rowHeight = Math.max(rowHeight, g.box.h);
  }

  // Fit to the drawing area
  const all = Object.values(placed);
  const minX = Math.min(...all.map((p) => p.x));
  const minY = Math.min(...all.map((p) => p.y));
  const spanX = Math.max(...all.map((p) => p.x)) - minX || 1;
  const spanY = Math.max(...all.map((p) => p.y)) - minY || 1;
  const scale = Math.min((width - 2 * margin) / spanX, (height - 2 * margin) / spanY, 1.6);
  const offsetX = (width - spanX * scale) / 2;
  const offsetY = (height - spanY * scale) / 2;
  for (const id of Object.keys(placed)) {
    placed[id] = { x: offsetX + (placed[id].x - minX) * scale, y: offsetY + (placed[id].y - minY) * scale };
  }
  return placed;
}
