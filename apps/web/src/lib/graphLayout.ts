/**
 * VEDA AI — Knowledge graph layout
 *
 * Deterministic force-directed layout for the Knowledge Graph view:
 * - each connected component (a machine with its alarms, fixes and readings)
 *   gets its own area, larger components nearer the middle
 * - inside a component, linked nodes pull together (springs) and all nodes
 *   push apart (repulsion), so relationships read as clusters, not a ring
 * - every node keeps the room its circle and label need (collision pass),
 *   and the view zooms to fit instead of squeezing the picture
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

/** Circle radius of a node: subjects (assets) and well-linked nodes are larger. */
export function nodeRadius(n: GraphNode | undefined, subject = false): number {
  if (!n) return 6;
  return Math.min(16, (subject ? 8 : 5) + n.degree * 0.8);
}

/** Space a node needs on the canvas: its circle plus the label drawn under it. */
export function nodeBox(n: GraphNode, subject = false): { w: number; h: number } {
  const r = nodeRadius(n, subject);
  const charWidth = subject ? 6.4 : 5.4;
  return { w: Math.max(2 * r, n.label.length * charWidth + 8), h: 2 * r + 16 };
}

interface Box {
  w: number;
  h: number;
}

/**
 * Push apart nodes whose boxes (circle + label) overlap, along the axis
 * that needs the smaller move. Deterministic: ties move by index order.
 */
function resolveCollisions(pos: Point[], boxes: Box[], passes = 80, pad = 6): void {
  const n = pos.length;
  for (let pass = 0; pass < passes; pass++) {
    let moved = false;
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const dx = pos[j].x - pos[i].x;
        const dy = pos[j].y - pos[i].y;
        const ox = (boxes[i].w + boxes[j].w) / 2 + pad - Math.abs(dx);
        const oy = (boxes[i].h + boxes[j].h) / 2 + pad - Math.abs(dy);
        if (ox <= 0 || oy <= 0) continue;
        moved = true;
        if (ox < oy) {
          const s = (dx > 0 || (dx === 0 && i < j) ? 1 : -1) * (ox / 2);
          pos[i].x -= s;
          pos[j].x += s;
        } else {
          const s = (dy > 0 || (dy === 0 && i < j) ? 1 : -1) * (oy / 2);
          pos[i].y -= s;
          pos[j].y += s;
        }
      }
    }
    if (!moved) break;
  }
}

function layoutComponent(
  ids: string[],
  edges: GraphEdge[],
  boxes: Map<string, Box>
): Record<string, Point> {
  const n = ids.length;
  const index = new Map(ids.map((id, i) => [id, i]));
  const size = ids.map((id) => boxes.get(id) ?? { w: 20, h: 20 });
  const pos = ids.map((_, i) => {
    const angle = (2 * Math.PI * i) / n;
    const r = 30 + 14 * Math.sqrt(n);
    return { x: r * Math.cos(angle), y: r * Math.sin(angle) };
  });
  const links = edges
    .filter((e) => index.has(e.source) && index.has(e.target))
    .map((e) => [index.get(e.source)!, index.get(e.target)!] as const);

  // Springs are as long as the two labels need, plus breathing room
  const ideal = (a: number, b: number) => 50 + (size[a].w + size[b].w) / 4;
  const repel = 90;
  const iterations = n > 300 ? 150 : 300;
  for (let it = 0; it < iterations; it++) {
    const cooling = 1 - it / iterations;
    const force = pos.map(() => ({ x: 0, y: 0 }));
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const dx = pos[i].x - pos[j].x;
        const dy = pos[i].y - pos[j].y;
        const d2 = Math.max(dx * dx + dy * dy, 1);
        const push = (repel * repel) / d2;
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
      const pull = ((d - ideal(a, b)) / d) * 0.1;
      force[a].x += dx * pull;
      force[a].y += dy * pull;
      force[b].x -= dx * pull;
      force[b].y -= dy * pull;
    }
    for (let i = 0; i < n; i++) {
      force[i].x -= pos[i].x * 0.01; // gentle gravity to the component centre
      force[i].y -= pos[i].y * 0.01;
      const step = Math.hypot(force[i].x, force[i].y);
      const max = 14 * cooling + 0.5;
      const scale = step > max ? max / step : 1;
      pos[i].x += force[i].x * scale;
      pos[i].y += force[i].y * scale;
    }
  }
  resolveCollisions(pos, size);
  return Object.fromEntries(ids.map((id, i) => [id, pos[i]]));
}

export interface NaturalLayout {
  positions: Record<string, Point>;
  width: number;
  height: number;
}

/**
 * Positions at natural scale: every node keeps the room its circle and label
 * need, so nothing overlaps; the view zooms to fit instead of squeezing.
 * Coordinates start at (margin, margin).
 */
export function layoutNatural(
  nodes: GraphNode[],
  edges: GraphEdge[],
  isSubject: (type: string) => boolean = () => false,
  margin = 40
): NaturalLayout {
  if (nodes.length === 0) return { positions: {}, width: 0, height: 0 };
  const boxes = new Map(nodes.map((n) => [n.id, nodeBox(n, isSubject(n.type))]));
  const groups = components(nodes, edges).map((ids) => {
    const local = layoutComponent(ids, edges, boxes);
    const half = (id: string) => boxes.get(id)!;
    const minX = Math.min(...ids.map((id) => local[id].x - half(id).w / 2));
    const maxX = Math.max(...ids.map((id) => local[id].x + half(id).w / 2));
    const minY = Math.min(...ids.map((id) => local[id].y - half(id).h / 2));
    const maxY = Math.max(...ids.map((id) => local[id].y + half(id).h / 2));
    return { ids, local, box: { minX, minY, w: maxX - minX, h: maxY - minY } };
  });

  // Shelf-pack the components left to right, rows wrapping at a 16:10 shape
  const gap = 60;
  const totalArea = groups.reduce((s, g) => s + (g.box.w + gap) * (g.box.h + gap), 0);
  const rowWidth = Math.max(Math.sqrt(totalArea * 1.6), groups[0].box.w + gap);
  const positions: Record<string, Point> = {};
  let x = 0;
  let y = 0;
  let rowHeight = 0;
  let width = 0;
  for (const g of groups) {
    if (x > 0 && x + g.box.w > rowWidth) {
      x = 0;
      y += rowHeight + gap;
      rowHeight = 0;
    }
    for (const id of g.ids) {
      positions[id] = {
        x: margin + x + g.local[id].x - g.box.minX,
        y: margin + y + g.local[id].y - g.box.minY,
      };
    }
    x += g.box.w + gap;
    width = Math.max(width, x - gap);
    rowHeight = Math.max(rowHeight, g.box.h);
  }
  return { positions, width: width + 2 * margin, height: y + rowHeight + 2 * margin };
}

/** The zoom and pan that show a whole layout inside a width × height frame. */
export function fitView(
  layout: { width: number; height: number },
  width: number,
  height: number
): { x: number; y: number; k: number } {
  if (!layout.width || !layout.height) return { x: 0, y: 0, k: 1 };
  const k = Math.min(width / layout.width, height / layout.height, 1.5);
  return { k, x: (width - layout.width * k) / 2, y: (height - layout.height * k) / 2 };
}

/** Positions for every node, fitted inside width × height (natural layout, scaled). */
export function layoutGraph(
  nodes: GraphNode[],
  edges: GraphEdge[],
  width: number,
  height: number
): Record<string, Point> {
  const layout = layoutNatural(nodes, edges);
  const view = fitView(layout, width, height);
  return Object.fromEntries(
    Object.entries(layout.positions).map(([id, p]) => [
      id,
      { x: view.x + p.x * view.k, y: view.y + p.y * view.k },
    ])
  );
}
