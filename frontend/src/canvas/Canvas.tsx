"use client";

import { memo, useCallback, useEffect } from "react";
import {
  ReactFlow, Background, Controls, MiniMap, addEdge,
  useNodesState, useEdgesState,
  type Connection, type Edge, type NodeChange, type ReactFlowInstance,
} from "@xyflow/react";
import { ancestors, type Graph, type NodeResult } from "@/api/client";
import FlowCard, { type CardNode } from "./FlowCard";
import { reconcileNodes, withCanvasPositions } from "./state";

const nodeTypes = { card: FlowCard };
const fitViewOptions = { padding: 0.18 };
const deleteKeys = ["Backspace", "Delete"];
const miniMapColor = (node: CardNode) => node.data.kind === "image" ? "#e7d8b6" : "#b8d7bd";

type Props = {
  graph: Graph;
  results: Record<string, NodeResult>;
  selected?: string;
  locked: boolean;
  running: boolean;
  onChange: (graph: Graph) => void;
  onSelect: (id: string | undefined) => void;
  onReady: (instance: ReactFlowInstance<CardNode, Edge>) => void;
};

function Canvas({ graph, results, selected, locked, running, onChange, onSelect, onReady }: Props) {
  // Drag frames and measurement updates stay local to the canvas. The editor
  // receives workflow coordinates only once the gesture has finished.
  const [nodes, setNodes, applyChanges] = useNodesState<CardNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  useEffect(() => {
    setNodes(current => reconcileNodes(current, graph, results, selected));
  }, [graph, results, selected, setNodes]);

  useEffect(() => {
    setEdges(current => {
      const existing = new Map(current.map(edge => [edge.id, edge]));
      return graph.edges.map(edge => ({
        ...edge,
        selected: existing.get(edge.id)?.selected,
        type: "smoothstep",
        animated: running && results[edge.target]?.status === "running",
        style: { stroke: results[edge.source]?.status === "succeeded" ? "#61946b" : "#c8cfc8", strokeWidth: 1.6 },
      }));
    });
  }, [graph.edges, results, running, setEdges]);

  const valid = useCallback((connection: Connection | Edge) => {
    const a = graph.nodes.find(node => node.id === connection.source);
    const b = graph.nodes.find(node => node.id === connection.target);
    if (!a || !b || a.id === b.id || a.type === "end" || b.type === "start" || (a.type === "image" && b.type !== "end")) return false;
    if (graph.edges.some(edge => edge.source === a.id && edge.target === b.id)) return false;
    return !ancestors(a.id, graph).some(node => node.id === b.id);
  }, [graph]);

  const connect = useCallback((connection: Connection) => {
    if (!locked) onChange({ ...graph, edges: addEdge(connection, graph.edges) });
  }, [graph, locked, onChange]);

  const onNodesChange = useCallback((changes: NodeChange<CardNode>[]) => {
    applyChanges(changes);
    if (locked) return;
    // Use final coordinates from the change event, not a render's stale nodes.
    // Keyboard nudges also use this path without a drag-stop callback.
    const positions = changes.flatMap(change =>
      change.type === "position" && !change.dragging && change.position
        ? [{ id: change.id, position: change.position }]
        : []
    );
    if (positions.length) onChange(withCanvasPositions(graph, positions));
  }, [applyChanges, graph, locked, onChange]);

  const remove = useCallback(({ nodes: removedNodes, edges: removedEdges }: { nodes: CardNode[]; edges: Edge[] }) => {
    if (locked) return;
    const nodeIds = new Set(removedNodes.map(node => node.id));
    const edgeIds = new Set(removedEdges.map(edge => edge.id));
    onChange({
      nodes: graph.nodes.filter(node => !nodeIds.has(node.id)),
      edges: graph.edges.filter(edge => !edgeIds.has(edge.id) && !nodeIds.has(edge.source) && !nodeIds.has(edge.target)),
    });
    if (selected && nodeIds.has(selected)) onSelect(undefined);
  }, [graph, locked, onChange, onSelect, selected]);

  const selectNode = useCallback((_: unknown, node: CardNode) => onSelect(node.id), [onSelect]);
  const deselect = useCallback(() => onSelect(undefined), [onSelect]);

  return <ReactFlow<CardNode, Edge>
    nodes={nodes} edges={edges} nodeTypes={nodeTypes}
    onInit={onReady} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
    onConnect={connect} isValidConnection={valid} onDelete={remove}
    onNodeClick={selectNode} onNodeDragStart={selectNode}
    onPaneClick={deselect} nodesDraggable={!locked} nodesConnectable={!locked}
    deleteKeyCode={locked ? null : deleteKeys}
    fitView fitViewOptions={fitViewOptions} minZoom={0.35} maxZoom={1.5}
  >
    <Background gap={22} size={1} color="#c8d1c7" />
    <Controls showInteractive={false} />
    <MiniMap pannable zoomable nodeColor={miniMapColor} />
  </ReactFlow>;
}

export default memo(Canvas);
