import type { Graph } from "../api/client";

export const HISTORY_LIMIT = 100;

export type GraphHistory = { past: Graph[]; present: Graph; future: Graph[] };
export type HistoryAction = { type: "commit" | "reset"; graph: Graph } | { type: "undo" | "redo" };
export type GraphUpdate = Graph | ((previous: Graph) => Graph);

export function createHistory(graph: Graph): GraphHistory {
  return { past: [], present: graph, future: [] };
}

// Graph updates are immutable; snapshots contain configuration and positions only.
export function updateHistory(state: GraphHistory, action: HistoryAction): GraphHistory {
  switch (action.type) {
    case "reset":
      return createHistory(action.graph);
    case "commit":
      if (JSON.stringify(state.present) === JSON.stringify(action.graph)) return state;
      return {
        past: [...state.past, state.present].slice(-HISTORY_LIMIT),
        present: action.graph,
        future: [],
      };
    case "undo": {
      const previous = state.past.at(-1);
      if (!previous) return state;
      return { past: state.past.slice(0, -1), present: previous, future: [state.present, ...state.future] };
    }
    case "redo": {
      const next = state.future[0];
      if (!next) return state;
      return { past: [...state.past, state.present], present: next, future: state.future.slice(1) };
    }
  }
}

type HistoryKey = Pick<
  KeyboardEvent,
  "key" | "ctrlKey" | "metaKey" | "shiftKey" | "altKey" | "isComposing" | "defaultPrevented" | "preventDefault"
>;
type HistoryKeyControls = {
  disabled: boolean;
  editingText: boolean;
  undo: () => boolean;
  redo: () => boolean;
};

function shortcutDirection(event: HistoryKey): "undo" | "redo" | undefined {
  if (!(event.ctrlKey || event.metaKey) || event.altKey) return;
  const key = event.key.toLowerCase();
  if (key === "z") return event.shiftKey ? "redo" : "undo";
  if (key === "y" && event.ctrlKey && !event.shiftKey) return "redo";
}

export function handleHistoryKey(event: HistoryKey, controls: HistoryKeyControls): void {
  if (controls.disabled || controls.editingText || event.isComposing || event.defaultPrevented) return;
  const direction = shortcutDirection(event);
  if (direction && controls[direction]()) event.preventDefault();
}
