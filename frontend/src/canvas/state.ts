import type { Graph, NodeResult } from "../api/client";
import type { CardNode } from "./FlowCard";

// Workflow JSON deliberately excludes React Flow's transient state. When the
// workflow changes, reconcile it into existing canvas nodes instead of throwing
// away measured dimensions, handle initialization and in-progress dragging.
export function reconcileNodes(
  current: CardNode[],
  graph: Graph,
  results: Record<string, NodeResult>,
  selected: string | undefined,
): CardNode[] {
  const existing = new Map(current.map((node) => [node.id, node]));
  const next = graph.nodes.map((node) => {
    const old = existing.get(node.id);
    const result = results[node.id];
    const isSelected = selected === node.id;
    const position = old?.dragging ? old.position : node.position;
    const sameData = old?.data.kind === node.type && old.data.config === node.data && old.data.result === result;
    const samePosition = old?.position.x === position.x && old.position.y === position.y;
    if (old && sameData && samePosition && old.selected === isSelected) return old;
    return {
      ...old,
      id: node.id,
      type: "card" as const,
      position: samePosition && old ? old.position : position,
      selected: isSelected,
      data: sameData && old ? old.data : { kind: node.type, config: node.data, result },
    };
  });
  return next.length === current.length && next.every((node, i) => node === current[i]) ? current : next;
}

export function withCanvasPositions(graph: Graph, nodes: Pick<CardNode, "id" | "position">[]): Graph {
  const positions = new Map(nodes.map((node) => [node.id, node.position]));
  return {
    ...graph,
    nodes: graph.nodes.map((node) => {
      const position = positions.get(node.id);
      return position && (position.x !== node.position.x || position.y !== node.position.y)
        ? { ...node, position: { x: position.x, y: position.y } }
        : node;
    }),
  };
}
