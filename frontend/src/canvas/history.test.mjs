import assert from "node:assert/strict";
import { test } from "node:test";
import { createHistory, updateHistory, handleHistoryKey, HISTORY_LIMIT } from "./history.ts";
import { reconcileNodes, withCanvasPositions } from "./state.ts";

const graph = {
  nodes: [
    { id: "start", type: "start", position: { x: 0, y: 80 }, data: { fields: "topic" } },
    { id: "end", type: "end", position: { x: 600, y: 80 }, data: {} },
  ],
  edges: [],
};
const commit = (state, next) => updateHistory(state, { type: "commit", graph: next });

test("EDIT-001 node, edge and configuration edits undo and redo without mutating snapshots", () => {
  const original = structuredClone(graph);
  const added = {
    ...graph,
    nodes: [
      ...graph.nodes,
      {
        id: "text",
        type: "template",
        position: { x: 200, y: 80 },
        data: { template: "hello" },
      },
    ],
  };
  const connected = { ...added, edges: [{ id: "a", source: "start", target: "text" }] };
  const configured = {
    ...connected,
    nodes: connected.nodes.map((n) =>
      n.id === "text" ? { ...n, data: { template: "updated", audio_url: "/artifacts/reference.mp3" } } : n,
    ),
  };
  const deleted = { ...graph };
  let state = createHistory(graph);
  for (const next of [added, connected, configured, deleted]) state = commit(state, next);
  for (const expected of [configured, connected, added, graph]) {
    state = updateHistory(state, { type: "undo" });
    assert.deepEqual(state.present, expected);
  }
  for (const expected of [added, connected, configured, deleted]) {
    state = updateHistory(state, { type: "redo" });
    assert.deepEqual(state.present, expected);
  }
  assert.deepEqual(graph, original);
});

test("EDIT-001 a completed drag is one step and undo retains measured node dimensions", () => {
  let canvas = reconcileNodes([], graph, {}, undefined).map((n) => ({
    ...n,
    measured: { width: 226, height: 150 },
  }));
  const moved = withCanvasPositions(graph, [{ id: "start", position: { x: 250, y: 120 } }]);
  let state = commit(createHistory(graph), moved);
  canvas = reconcileNodes(canvas, state.present, {}, undefined);
  state = updateHistory(state, { type: "undo" });
  canvas = reconcileNodes(canvas, state.present, {}, undefined);
  assert.deepEqual(canvas[0].position, graph.nodes[0].position);
  assert.deepEqual(canvas[0].measured, { width: 226, height: 150 });
  assert.equal(state.past.length, 0);
});

test("EDIT-001 duplicate updates are ignored, new edits clear redo and reset clears both stacks", () => {
  const moved = withCanvasPositions(graph, [{ id: "start", position: { x: 20, y: 10 } }]);
  let state = commit(createHistory(graph), moved);
  assert.equal(commit(state, structuredClone(moved)), state);
  state = updateHistory(state, { type: "undo" });
  assert.equal(commit(state, structuredClone(graph)), state);
  state = commit(state, { ...graph, edges: [{ id: "direct", source: "start", target: "end" }] });
  assert.equal(state.future.length, 0);
  state = updateHistory(state, { type: "reset", graph: moved });
  assert.deepEqual(state, { past: [], present: moved, future: [] });
  assert.equal(updateHistory(state, { type: "undo" }), state);
  assert.equal(updateHistory(state, { type: "redo" }), state);
});

test("EDIT-001 edit history is bounded to the most recent 100 graph changes", () => {
  let state = createHistory(graph);
  for (let i = 1; i <= HISTORY_LIMIT + 5; i++) {
    state = commit(state, withCanvasPositions(graph, [{ id: "start", position: { x: i, y: 80 } }]));
  }
  assert.equal(state.past.length, 100);
  for (let i = 0; i < 100; i++) state = updateHistory(state, { type: "undo" });
  assert.equal(state.present.nodes[0].position.x, 5);
});

function key(overrides = {}) {
  return {
    key: "z",
    ctrlKey: true,
    metaKey: false,
    shiftKey: false,
    altKey: false,
    isComposing: false,
    defaultPrevented: false,
    preventDefault() {
      this.defaultPrevented = true;
    },
    ...overrides,
  };
}

test("EDIT-001 keyboard shortcuts apply graph undo/redo and prevent browser handling only on success", () => {
  for (const [keys, direction] of [
    [{}, "undo"],
    [{ ctrlKey: false, metaKey: true }, "undo"],
    [{ key: "Z", shiftKey: true }, "redo"],
    [{ key: "y" }, "redo"],
  ]) {
    const calls = [];
    const event = key(keys);
    handleHistoryKey(event, {
      disabled: false,
      editingText: false,
      undo: () => {
        calls.push("undo");
        return true;
      },
      redo: () => {
        calls.push("redo");
        return true;
      },
    });
    assert.deepEqual(calls, [direction]);
    assert.equal(event.defaultPrevented, true);
  }
  const event = key();
  handleHistoryKey(event, { disabled: false, editingText: false, undo: () => false, redo: () => false });
  assert.equal(event.defaultPrevented, false);
});

test("EDIT-001 locked graphs, text editing, IME and unrelated keys do not change edit history", () => {
  for (const [keys, options] of [
    [{}, { disabled: true }],
    [{}, { editingText: true }],
    [{ isComposing: true }, {}],
    [{ defaultPrevented: true }, {}],
    [{ altKey: true }, {}],
    [{ ctrlKey: false }, {}],
    [{ key: "x" }, {}],
  ]) {
    const event = key(keys);
    const before = event.defaultPrevented;
    const unexpected = () => assert.fail("graph history changed while shortcut should be ignored");
    handleHistoryKey(event, { disabled: false, editingText: false, undo: unexpected, redo: unexpected, ...options });
    assert.equal(event.defaultPrevented, before);
  }
});
