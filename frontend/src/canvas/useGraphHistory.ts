"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Graph } from "../api/client";
import { createHistory, handleHistoryKey, updateHistory, type GraphUpdate, type HistoryAction } from "./history";

export type GraphHistoryControls = {
  graph: Graph;
  commit: (update: GraphUpdate) => void;
  reset: (graph: Graph) => void;
  undo: () => Graph | undefined;
  redo: () => Graph | undefined;
  canUndo: boolean;
  canRedo: boolean;
};

export function useGraphHistory(initial: Graph): GraphHistoryControls {
  const [state, setState] = useState(() => createHistory(initial));
  const current = useRef(state);
  // Ref updates make consecutive keyboard events see the latest snapshot,
  // including events arriving before React has committed the next render.
  const apply = useCallback((action: HistoryAction): Graph | undefined => {
    const next = updateHistory(current.current, action);
    if (next === current.current) return;
    current.current = next;
    setState(next);
    return next.present;
  }, []);
  const commit = useCallback(
    (update: GraphUpdate): void => {
      const graph = typeof update === "function" ? update(current.current.present) : update;
      apply({ type: "commit", graph });
    },
    [apply],
  );
  const reset = useCallback(
    (graph: Graph): void => {
      apply({ type: "reset", graph });
    },
    [apply],
  );
  const undo = useCallback((): Graph | undefined => apply({ type: "undo" }), [apply]);
  const redo = useCallback((): Graph | undefined => apply({ type: "redo" }), [apply]);
  return {
    graph: state.present,
    commit,
    reset,
    undo,
    redo,
    canUndo: state.past.length > 0,
    canRedo: state.future.length > 0,
  };
}

type ShortcutControls = { undo: () => boolean; redo: () => boolean };

export function useHistoryShortcuts(controls: ShortcutControls, disabled: boolean): void {
  const { undo, redo } = controls;
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent): void => {
      const editingText = event
        .composedPath()
        .some(
          (target) =>
            target instanceof HTMLElement &&
            (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)),
        );
      handleHistoryKey(event, { disabled, editingText, undo, redo });
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [disabled, undo, redo]);
}
