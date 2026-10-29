import assert from "node:assert/strict";
import { test } from "node:test";
import { applyNodeChanges } from "@xyflow/react";
import { reconcileNodes, withCanvasPositions } from "./state.ts";

const graph = {
  nodes: [
    { id: "start", type: "start", position: { x: 0, y: 80 }, data: { fields: "topic" } },
    { id: "end", type: "end", position: { x: 600, y: 80 }, data: {} },
  ],
  edges: [{ id: "start-end", source: "start", target: "end" }],
};

function measuredNodes() {
  return applyNodeChanges(
    graph.nodes.map((node) => ({
      id: node.id,
      type: "dimensions",
      dimensions: { width: 226, height: 150 },
    })),
    reconcileNodes([], graph, {}, undefined),
  );
}

test("dragging and editor updates preserve measured dimensions for every node", () => {
  let nodes = measuredNodes();
  const untouched = nodes[1];
  for (let frame = 1; frame <= 30; frame++) {
    nodes = applyNodeChanges(
      [{ id: "start", type: "position", position: { x: frame * 2, y: 80 }, dragging: true }],
      nodes,
    );
    // Selecting a node / opening its inspector must not restore saved coordinates.
    nodes = reconcileNodes(nodes, graph, {}, "start");
    assert.equal(nodes[0].position.x, frame * 2);
    assert.equal(nodes[0].dragging, true);
    assert.deepEqual(nodes[0].measured, { width: 226, height: 150 });
    assert.equal(nodes[1], untouched);
  }
});

test("a drag only persists coordinates; canvas-only state never reaches the API", () => {
  let nodes = measuredNodes();
  nodes = applyNodeChanges([{ id: "start", type: "position", position: { x: 120, y: 160 }, dragging: false }], nodes);
  const saved = withCanvasPositions(graph, nodes);
  assert.deepEqual(saved.nodes[0].position, { x: 120, y: 160 });
  assert.equal(saved.nodes[1], graph.nodes[1]);
  assert.equal(saved.edges, graph.edges);
  assert.equal("measured" in saved.nodes[0], false);
  assert.equal("dragging" in saved.nodes[0], false);
  assert.deepEqual(graph.nodes[0].position, { x: 0, y: 80 });
  assert.deepEqual(reconcileNodes(nodes, saved, {}, undefined)[0].measured, nodes[0].measured);
});

test("stream output updates only the changed node and retains dimensions", () => {
  const nodes = measuredNodes();
  const result = { status: "succeeded", output: "Hello" };
  const next = reconcileNodes(nodes, graph, { start: result }, undefined);
  assert.equal(next[1], nodes[1]);
  assert.equal(next[0].measured, nodes[0].measured);
  assert.equal(next[0].data.result, result);
  assert.equal(reconcileNodes(next, graph, { start: result }, undefined), next);
});

test("snapshot positions and removals synchronize without inheriting stale nodes", () => {
  const nodes = measuredNodes();
  const snapshot = { ...graph, nodes: [{ ...graph.nodes[0], position: { x: 300, y: 240 } }] };
  const next = reconcileNodes(nodes, snapshot, {}, undefined);
  assert.equal(next.length, 1);
  assert.deepEqual(next[0].position, { x: 300, y: 240 });
  assert.equal(next[0].measured, nodes[0].measured);
});
