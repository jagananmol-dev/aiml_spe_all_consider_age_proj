/**
 * VEDA AI — Knowledge graph layout tests
 */

import {
  components,
  fitView,
  layoutGraph,
  layoutNatural,
  neighbourhood,
  nodeBox,
  type GraphEdge,
  type GraphNode,
} from "@/lib/graphLayout";

const node = (id: string, type = "EQUIPMENT_TAG"): GraphNode => ({
  id,
  label: id,
  type,
  degree: 1,
});
const edge = (source: string, target: string): GraphEdge => ({
  source,
  target,
  relationship: "FAILED_WITH",
  confidence: 0.9,
  documents: ["doc.pdf"],
});

const NODES = ["a", "b", "c", "x", "y"].map((id) => node(id));
const EDGES = [edge("a", "b"), edge("b", "c"), edge("x", "y")];

describe("components", () => {
  it("groups connected nodes, largest first", () => {
    expect(components(NODES, EDGES)).toEqual([
      expect.arrayContaining(["a", "b", "c"]),
      expect.arrayContaining(["x", "y"]),
    ]);
  });
});

describe("neighbourhood", () => {
  it("follows links in both directions up to the hop limit", () => {
    expect([...neighbourhood("b", EDGES, 1)].sort()).toEqual(["a", "b", "c"]);
    expect([...neighbourhood("a", EDGES, 1)].sort()).toEqual(["a", "b"]);
    expect([...neighbourhood("a", EDGES, 2)].sort()).toEqual(["a", "b", "c"]);
  });
});

describe("layoutGraph", () => {
  const pos = layoutGraph(NODES, EDGES, 1000, 600);
  const dist = (p: string, q: string) => Math.hypot(pos[p].x - pos[q].x, pos[p].y - pos[q].y);

  it("places every node inside the drawing area", () => {
    for (const n of NODES) {
      expect(pos[n.id].x).toBeGreaterThanOrEqual(0);
      expect(pos[n.id].x).toBeLessThanOrEqual(1000);
      expect(pos[n.id].y).toBeGreaterThanOrEqual(0);
      expect(pos[n.id].y).toBeLessThanOrEqual(600);
    }
  });

  it("keeps linked nodes closer than unlinked ones", () => {
    expect(dist("a", "b")).toBeLessThan(dist("a", "x"));
    expect(dist("x", "y")).toBeLessThan(dist("c", "x"));
  });

  it("does not stack nodes on top of each other", () => {
    const ids = NODES.map((n) => n.id);
    for (let i = 0; i < ids.length; i++)
      for (let j = i + 1; j < ids.length; j++) expect(dist(ids[i], ids[j])).toBeGreaterThan(10);
  });

  it("is deterministic", () => {
    expect(layoutGraph(NODES, EDGES, 1000, 600)).toEqual(pos);
  });

  it("handles an empty graph", () => {
    expect(layoutGraph([], [], 1000, 600)).toEqual({});
  });
});

describe("layoutNatural", () => {
  // A hub (like a document) linked to 40 entities with long labels
  const hub: GraphNode = {
    id: "hub",
    label: "Q3_2026_Board_Pack.docx",
    type: "DOCUMENT",
    degree: 40,
  };
  const leaves: GraphNode[] = Array.from({ length: 40 }, (_, i) => ({
    id: `n${i}`,
    label: `catheter-related bloodstream infection ${i}`,
    type: "CONDITION",
    degree: 1,
  }));
  const nodes = [hub, ...leaves];
  const edges = leaves.map((n) => edge("hub", n.id));
  const layout = layoutNatural(nodes, edges);

  it("gives every node room for its circle and label (no overlaps)", () => {
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = layout.positions[nodes[i].id];
        const b = layout.positions[nodes[j].id];
        const boxA = nodeBox(nodes[i]);
        const boxB = nodeBox(nodes[j]);
        const overlapX = (boxA.w + boxB.w) / 2 - Math.abs(a.x - b.x);
        const overlapY = (boxA.h + boxB.h) / 2 - Math.abs(a.y - b.y);
        expect(overlapX <= 0.5 || overlapY <= 0.5).toBe(true);
      }
    }
  });

  it("fits the view by zooming, not by squeezing positions", () => {
    const view = fitView(layout, 1000, 640);
    expect(layout.width * view.k).toBeLessThanOrEqual(1000.5);
    expect(layout.height * view.k).toBeLessThanOrEqual(640.5);
  });
});
