export type Kind = "start" | "llm" | "image" | "speech" | "music" | "video" | "asr" | "template" | "end";
export type FlowNode = { id: string; type: Kind; position: { x: number; y: number }; data: Record<string, string> };
export type Graph = { nodes: FlowNode[]; edges: { id: string; source: string; target: string }[] };
export type Workflow = { id: string; name: string; graph: Graph; version: number; updated_at: string };
export type Model = {
  id: string;
  name: string;
  kind: "text" | "image" | "speech" | "music" | "video" | "asr";
  provider: string;
};
export type Property = { type: string; title: string; default: string; format?: string; enum?: string[] };
export type Definition = {
  title: string;
  description: string;
  output_type: string;
  properties: Record<string, Property>;
};
export type Registry = Record<Kind, Definition>;
export type Run = {
  id: string;
  workflow_id: string;
  workflow_version: number;
  graph: Graph;
  inputs: Record<string, string>;
  status: string;
  outputs: Record<string, unknown>;
  error: string | null;
  created_at: string;
  finished_at: string | null;
};
export type RunEvent = {
  type: string;
  data: {
    node_id?: string;
    text?: string;
    result?: { output: unknown; usage?: unknown };
    inputs?: unknown;
    elapsed_ms?: number;
    error?: string;
    status?: string;
    task_id?: string;
    api_version?: string;
    outputs?: Record<string, unknown>;
  };
  created_at?: string;
};
export type NodeResult = {
  status: string;
  text?: string;
  output?: unknown;
  usage?: unknown;
  inputs?: unknown;
  elapsed_ms?: number;
  error?: string;
  progress?: string;
  task_id?: string;
  api_version?: string;
};

export const mediaKinds: Kind[] = ["image", "speech", "music", "video"];
export const mediaTargets: Partial<Record<Kind, Kind[]>> = {
  image: ["video", "end"],
  speech: ["asr", "music", "end"],
  music: ["asr", "music", "end"],
  video: ["end"],
};
export const nodeKinds: Kind[] = ["start", "llm", "image", "speech", "music", "video", "asr", "template", "end"];

export function outputFields(node: FlowNode): string[] {
  return node.type === "start"
    ? [
        ...(node.data.fields || "topic")
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        "output",
      ]
    : mediaKinds.includes(node.type)
      ? ["url"]
      : ["output"];
}

export async function api<T>(path: string, payload: unknown = {}): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : `请求失败 (${response.status})`);
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}

export function ancestors(id: string, graph: Graph): FlowNode[] {
  const seen = new Set<string>();
  const visit = (key: string) => {
    graph.edges
      .filter((e) => e.target === key)
      .forEach((e) => {
        if (!seen.has(e.source)) {
          seen.add(e.source);
          visit(e.source);
        }
      });
  };
  visit(id);
  seen.delete(id);
  return graph.nodes.filter((n) => seen.has(n.id));
}
