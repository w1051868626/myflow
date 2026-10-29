"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Edge, ReactFlowInstance } from "@xyflow/react";
import { ArrowLeft, ArrowUpRight, Check, ChevronDown, Clock3, Command, FlaskConical, Layers3, LoaderCircle, Play, Plus, Save, Settings2, Square, Trash2, Workflow as WorkflowIcon, X } from "lucide-react";
import { ancestors, api, nodeKinds, outputFields, type Graph, type Kind, type Model, type NodeResult, type Registry, type Run, type Workflow } from "@/api/client";
import { subscribeRun } from "@/api/events";
import { icons, statusNames, titles, type CardNode } from "./FlowCard";
import Canvas from "./Canvas";
import Settings from "@/panels/Settings";

const kinds = nodeKinds;
const blank: Graph = { nodes: [
  { id: "start", type: "start", position: { x: 0, y: 80 }, data: { label: "创作主题", fields: "topic" } },
  { id: "end", type: "end", position: { x: 620, y: 80 }, data: { label: "创作完成" } },
], edges: [] };

function Output({ value }: { value: unknown }) {
  if (value && typeof value === "object" && "url" in value && typeof value.url === "string") {
    const url = value.url;
    if (!url.startsWith("/artifacts/") && !/^https?:\/\//.test(url)) return <p>无效的资源地址</p>;
    const kind = "kind" in value ? value.kind : "image";
    return <div className="image-output media-output">{kind === "audio" ? <audio controls preload="metadata" src={url} /> : kind === "video" ? <video controls preload="metadata" src={url} /> : <a href={url} target="_blank" rel="noreferrer"><img src={url} alt="工作流生成图片" /></a>}<a className="text-button" href={url} target="_blank" rel="noreferrer">打开资源 <ArrowUpRight size={12} /></a>{"demo" in value && <span className="demo-tag">演示图像</span>}{"temporary" in value && <p className="muted small">供应商临时链接，请及时保存。</p>}</div>;
  }
  return <pre className="output-text">{typeof value === "string" ? value : JSON.stringify(value, null, 2)}</pre>;
}

function Progress({ result }: { result: NodeResult }) {
  if (!result.task_id) return null;
  return <div className="node-progress">{result.status === "running" && <p>{result.progress}</p>}<small>任务 ID：<code>{result.task_id}</code></small><a className="text-button" href={`/models?task_id=${encodeURIComponent(result.task_id)}&api_version=${result.api_version || "v2"}`} target="_blank" rel="noreferrer">在试验台查询 <ArrowUpRight size={12} /></a></div>;
}

export default function Editor() {
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [workflow, setWorkflow] = useState<Workflow>();
  const [graph, setGraph] = useState<Graph>(blank);
  const [registry, setRegistry] = useState<Registry>();
  const [models, setModels] = useState<Model[]>([]);
  const [selected, setSelected] = useState<string>();
  const [results, setResults] = useState<Record<string, NodeResult>>({});
  const [run, setRun] = useState<Run>();
  const [history, setHistory] = useState<Run[]>([]);
  const [tab, setTab] = useState<"params" | "run" | "history">("params");
  const [inputs, setInputs] = useState<Record<string, string>>({ topic: "一杯咖啡里的慢生活" });
  const [showInputs, setShowInputs] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [showWorkflows, setShowWorkflows] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);
  const [replaying, setReplaying] = useState(false);
  const [connection, setConnection] = useState("");
  const source = useRef<ReturnType<typeof subscribeRun> | null>(null);
  const flow = useRef<ReactFlowInstance<CardNode, Edge> | null>(null);
  const parameterRefs = useRef<Record<string, HTMLTextAreaElement | null>>({});
  const [referenceField, setReferenceField] = useState<string>();
  const locked = busy || run?.status === "running" || replaying;
  const viewedGraph = replaying && run ? run.graph : graph;
  const picked = viewedGraph.nodes.find(n => n.id === selected);
  const start = graph.nodes.find(n => n.type === "start");
  const fields = (start?.data.fields || "topic").split(",").map(s => s.trim()).filter(Boolean);

  const loadHistory = useCallback(async (id: string) => { setHistory(await api<Run[]>("/workflows/runs/list", { id })); }, []);
  const load = useCallback((item: Workflow) => {
    source.current?.close(); setWorkflow(item); setGraph(item.graph); setDirty(false); setSelected(undefined); setRun(undefined); setResults({}); setReplaying(false); setConnection(""); setTab("params");
    loadHistory(item.id).catch(e => setMessage(e.message));
    setTimeout(() => flow.current?.fitView({ padding: 0.18 }), 100);
  }, [loadHistory]);

  useEffect(() => {
    Promise.all([api<Workflow[]>("/workflows/list"), api<Registry>("/nodes"), api<Model[]>("/models")]).then(([items, definitions, available]) => {
      setWorkflows(items); setRegistry(definitions); setModels(available); if (items[0]) load(items[0]);
    }).catch(e => setMessage(e.message)).finally(() => setLoading(false));
    return () => source.current?.close();
  }, [load]);
  useEffect(() => {
    const guard = (e: BeforeUnloadEvent) => { if (dirty) e.preventDefault(); };
    window.addEventListener("beforeunload", guard); return () => window.removeEventListener("beforeunload", guard);
  }, [dirty]);
  useEffect(() => {
    if (!run || run.status === "running") return;
    const timer = setTimeout(() => flow.current?.fitView({ padding: 0.18, duration: 250 }), 120);
    return () => clearTimeout(timer);
  }, [run]);

  const edit = useCallback((next: Graph) => { setGraph(next); setDirty(true); }, []);
  const selectNode = useCallback((id: string | undefined) => {
    setSelected(id);
    if (id) setTab("params");
  }, []);
  const initializeCanvas = useCallback((instance: ReactFlowInstance<CardNode, Edge>) => { flow.current = instance; }, []);
  function updateData(key: string, value: string) {
    if (!picked || locked) return;
    edit({ ...graph, nodes: graph.nodes.map(n => n.id === picked.id ? { ...n, data: { ...n.data, [key]: value } } : n) });
  }
  async function save() {
    if (!workflow) throw new Error("请先创建工作流");
    const saved = await api<Workflow>("/workflows/save", { id: workflow.id, name: workflow.name, graph, version: workflow.version });
    setWorkflow(saved); setWorkflows(items => items.map(w => w.id === saved.id ? saved : w)); setDirty(false); return saved;
  }
  async function saveClick() {
    setBusy(true); try { await save(); setMessage("工作流已保存"); } catch (e) { setMessage((e as Error).message); } finally { setBusy(false); }
  }
  async function create() {
    if (locked) return;
    if (dirty && !window.confirm("当前修改尚未保存，是否创建新的工作流？")) return;
    try {
      const item = await api<Workflow>("/workflows", { name: "未命名工作流", graph: blank });
      setWorkflows(items => [item, ...items]); load(item); setShowWorkflows(false);
    } catch (e) { setMessage((e as Error).message); }
  }
  async function removeWorkflow() {
    if (locked) return;
    if (!workflow || !window.confirm(`删除工作流「${workflow.name}」？`)) return;
    try {
      await api("/workflows/delete", { id: workflow.id });
      const items = workflows.filter(w => w.id !== workflow.id); setWorkflows(items);
      if (items[0]) load(items[0]); else { setWorkflow(undefined); setGraph(blank); setResults({}); setRun(undefined); setDirty(false); setHistory([]); setReplaying(false); }
    } catch (e) { setMessage((e as Error).message); }
  }

  function subscribe(item: Run) {
    source.current?.close(); setRun(item); setResults({}); setConnection("连接中…");
    const stream = subscribeRun(item.id, event => {
      const data = event.data;
      if (data.node_id) {
        const key = data.node_id;
        setResults(previous => {
          const old = previous[key] || { status: "waiting" };
          let result = old;
          if (event.type === "node_started") result = { status: "running" };
          if (event.type === "llm_token") result = { ...old, text: (old.text || "") + (data.text || "") };
          if (event.type === "node_progress") result = { ...old, progress: data.status, task_id: data.task_id, api_version: data.api_version };
          if (event.type === "node_finished") result = { ...old, status: "succeeded", output: data.result?.output, usage: data.result?.usage, inputs: data.inputs, elapsed_ms: data.elapsed_ms };
          if (event.type === "node_failed") result = { ...old, status: "failed", error: data.error, elapsed_ms: data.elapsed_ms };
          if (event.type === "node_cancelled") result = { ...old, status: "cancelled", elapsed_ms: data.elapsed_ms };
          if (event.type === "node_skipped" && old.status === "waiting") result = { status: "skipped" };
          return { ...previous, [key]: result };
        });
      }
      if (event.type === "run_finished" || event.type === "stream_closed") {
        stream.close(); setConnection("");
        api<Run>("/runs/get", { id: item.id }).then(finished => { setRun(finished); return loadHistory(item.workflow_id); }).catch(e => setMessage(e.message));
      }
    }, setConnection);
    source.current = stream;
  }
  async function execute() {
    setBusy(true); setShowInputs(false); setMessage("");
    try {
      const saved = await save();
      const values = Object.fromEntries(fields.map(key => [key, inputs[key] || ""]));
      const item = await api<Run>("/workflows/runs", { id: saved.id, inputs: values });
      setTab("run"); setReplaying(false); subscribe(item);
    } catch (e) { setMessage((e as Error).message); } finally { setBusy(false); }
  }
  async function stop() {
    try { if (run) await api("/runs/cancel", { id: run.id }); } catch (e) { setMessage((e as Error).message); }
  }
  function replay(item: Run) {
    setReplaying(true); setSelected(undefined); setTab("run"); subscribe(item);
    setTimeout(() => flow.current?.fitView({ padding: 0.18 }), 100);
  }
  function backToEdit() {
    source.current?.close(); setReplaying(false); setRun(undefined); setResults({}); setTab("params"); setConnection(""); setTimeout(() => flow.current?.fitView({ padding: 0.18 }), 100);
  }

  function add(kind: Kind, position?: { x: number; y: number }) {
    if (!registry || locked || !workflow) return;
    if ((kind === "start" || kind === "end") && graph.nodes.some(n => n.type === kind)) { setMessage(`只能有一个${titles[kind]}节点`); return; }
    const id = `${kind}_${crypto.randomUUID().slice(0, 8)}`;
    const data = Object.fromEntries(Object.entries(registry[kind].properties).map(([key, p]) => [key, p.default]));
    edit({ ...graph, nodes: [...graph.nodes, { id, type: kind, data: { ...data, label: titles[kind] }, position: position || { x: 280 + graph.nodes.length * 25, y: 260 } }] }); setSelected(id); setTab("params");
  }
  function insertReference(field: string, reference: string) {
    const element = parameterRefs.current[field]; const value = picked?.data[field] || "";
    const pos = element?.selectionStart ?? value.length;
    const before = value.slice(0, pos).replace(/\{+$/, "");
    const text = `${before}{{${reference}}}${value.slice(element?.selectionEnd ?? pos)}`;
    updateData(field, text); setReferenceField(undefined); element?.focus();
  }
  async function uploadResource(key: string, file?: File) {
    if (!picked || !file || locked) return;
    if (file.size > 20 * 1024 * 1024) { setMessage("文件不能超过 20 MB"); return; }
    const targetId = picked.id;
    setBusy(true);
    try {
      const encoded = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).split(",")[1]);
        reader.onerror = () => reject(new Error("读取文件失败"));
        reader.readAsDataURL(file);
      });
      const resource = await api<{ url: string }>("/artifacts/upload", { file_name: file.name, file_base64: encoded });
      setGraph(previous => ({ ...previous, nodes: previous.nodes.map(n => n.id === targetId ? { ...n, data: { ...n.data, [key]: resource.url } } : n) }));
      setDirty(true); setMessage("资源已上传，请保存工作流");
    } catch (e) { setMessage((e as Error).message); } finally { setBusy(false); }
  }
  function changeModel(id: string) {
    if (!picked || locked) return;
    const defaults: Record<string, string> = { model: id };
    if (picked.type === "video") {
      const h3 = id.startsWith("MiniMax-H3");
      defaults.duration = h3 ? "5" : "6";
      defaults.resolution = h3 || id.startsWith("MiniMax-Hailuo-") ? "768P" : "720P";
    }
    edit({ ...graph, nodes: graph.nodes.map(n => n.id === picked.id ? { ...n, data: { ...n.data, ...defaults } } : n) });
  }
  const variables = picked ? ancestors(picked.id, viewedGraph).flatMap(n => outputFields(n).map(key => `${n.id}.${key}`)) : [];

  return <main className="workspace">
    <nav className="rail"><a className="brand" href="/" aria-label="MyFlow"><WorkflowIcon size={24} /></a><button className="rail-button active" disabled={locked} title="工作流" onClick={() => setShowWorkflows(v => !v)}><Layers3 size={20} /></button><button className="rail-button" title="运行历史" onClick={() => setTab("history")}><Clock3 size={20} /></button><a className="rail-button" title="MiniMax 模型试验台" aria-label="MiniMax 模型试验台" href="/models" target="_blank" rel="noreferrer"><FlaskConical size={20} /></a><div className="rail-spacer" /><button className="rail-button" title="模型设置" onClick={() => setShowSettings(true)}><Settings2 size={20} /></button><span className="avatar">M</span></nav>
    <div className="main-area">
      <header className="topbar"><div className="breadcrumb">工作空间 <span>/</span><div className="workflow-menu"><button className="workflow-trigger" onClick={() => setShowWorkflows(v => !v)} disabled={locked}>{workflow?.name || "选择工作流"}<ChevronDown size={14} /></button>{showWorkflows && <div className="dropdown">{workflows.map(w => <button key={w.id} disabled={locked} onClick={() => { if (dirty && !window.confirm("放弃尚未保存的修改？")) return; load(w); setShowWorkflows(false); }}>{w.name}{workflow?.id === w.id && <Check size={14} />}</button>)}<button onClick={create}><Plus size={14} />新建工作流</button>{workflow && <button className="danger-text" onClick={removeWorkflow}><Trash2 size={14} />删除当前工作流</button>}</div>}</div><span className="version">v{workflow?.version || 1}</span></div><div className="topbar-right"><span className={`save-state ${dirty ? "unsaved" : ""}`}>{dirty ? "有未保存的修改" : "所有更改已保存"}</span><button className="button" disabled={locked || !workflow} onClick={saveClick}><Save size={15} />保存</button><button className="button primary" disabled={locked || !workflow} onClick={() => setShowInputs(true)}><Play size={14} fill="currentColor" />运行</button></div></header>
      <div className="editor-heading"><div><span className="eyebrow">THE CREATIVE WORKSPACE</span><h1>让灵感，流动起来<span className="title-dot">.</span></h1><p>连接模型与想法，构建你的 AI 创作流程。</p></div><div className="heading-meta"><span className="live-dot" />{run?.status === "running" ? "正在创作" : "画布已就绪"}<span className="meta-separator" />{graph.nodes.length} 个节点</div></div>
      <div className="editor-body">
        <section className="canvas-section" aria-label="工作流画布">
          <div className="canvas-toolbar"><div className="canvas-label"><WorkflowIcon size={15} /><span>{replaying ? "运行快照" : "工作流编辑器"}</span>{replaying && <button className="text-button" onClick={backToEdit}><ArrowLeft size={13} />返回编辑</button>}</div><span className="small muted">拖动节点 · 连线编排 · 点击配置</span></div>
          <div className="canvas-wrap" onDragOver={e => { e.preventDefault(); e.dataTransfer.dropEffect = "move"; }} onDrop={e => { e.preventDefault(); const kind = e.dataTransfer.getData("application/myflow") as Kind; if (kinds.includes(kind) && flow.current) add(kind, flow.current.screenToFlowPosition({ x: e.clientX, y: e.clientY })); }}>
            <Canvas graph={viewedGraph} results={results} selected={selected} locked={locked} running={run?.status === "running"} onChange={edit} onSelect={selectNode} onReady={initializeCanvas} />
            {loading && <div className="canvas-loading"><LoaderCircle className="spin" size={24} />正在打开工作空间…</div>}
            {!loading && !workflow && <div className="canvas-loading"><p>创建你的第一个工作流</p><button className="button primary" onClick={create}><Plus size={15} />新建工作流</button></div>}
          </div>
          <div className="node-library"><div className="library-label"><Plus size={15} /><span>添加节点</span></div>{kinds.map(kind => { const Icon = icons[kind]; return <button key={kind} draggable={!locked} disabled={locked || !workflow} onDragStart={e => e.dataTransfer.setData("application/myflow", kind)} onClick={() => add(kind)}><span className={`node-icon ${kind}`}><Icon size={15} /></span>{titles[kind]}</button>; })}</div>
          <div className="canvas-footer"><span><Command size={12} /> Ctrl / ⌘ + 滚轮缩放</span><span>由 MyFlow 连接每一次灵感 <ArrowUpRight size={12} /></span></div>
        </section>
        <aside className="inspector"><div className="inspector-tabs"><button className={tab === "params" ? "active" : ""} onClick={() => setTab("params")}>节点配置</button><button className={tab === "run" ? "active" : ""} onClick={() => setTab("run")}>运行结果{run?.status === "running" && <i className="live-dot" />}</button><button className={tab === "history" ? "active" : ""} onClick={() => setTab("history")}>历史</button></div>
          <div className="inspector-scroll">
            {tab === "params" && (picked && registry ? <>
              <span className="eyebrow">NODE CONFIGURATION</span><div className="node-heading"><span className={`node-icon large ${picked.type}`}>{(() => { const Icon = icons[picked.type]; return <Icon size={23} />; })()}</span><div><h2>{titles[picked.type]}</h2><code>{picked.id}</code></div></div><p className="muted">{registry[picked.type].description}</p>
              <fieldset disabled={locked}><label>节点名称<input value={picked.data.label || ""} onChange={e => updateData("label", e.target.value)} /></label>
              {Object.entries(registry[picked.type].properties).map(([key, property]) => <label key={key}>{property.title}
                {property.format?.endsWith("-model") ? <select value={picked.data[key] || property.default} onChange={e => changeModel(e.target.value)}>{models.filter(m => m.kind === property.format?.replace("-model", "")).map(m => <option key={m.id} value={m.id}>{m.name}</option>)}</select>
                : property.enum ? <select value={picked.data[key] || property.default} onChange={e => updateData(key, e.target.value)}>{property.enum.map(v => <option key={v}>{v}</option>)}</select>
                : (property.format === "textarea" || property.format?.endsWith("-file")) ? <><textarea ref={element => { parameterRefs.current[key] = element; }} value={picked.data[key] ?? property.default} aria-label={property.title} rows={property.format?.endsWith("-file") ? 2 : key === "system" ? 3 : 6} onChange={e => { updateData(key, e.target.value); if (e.target.value.slice(0, e.target.selectionStart).endsWith("{")) setReferenceField(key); }} /><button className="reference-trigger" onClick={() => setReferenceField(referenceField === key ? undefined : key)}>＋ 插入上游变量</button>{property.format?.endsWith("-file") && <div className="resource-upload"><input type="file" aria-label={`上传${property.title}`} accept={property.format === "image-file" ? "image/png,image/jpeg,image/webp" : "audio/*"} onChange={e => { const file = e.target.files?.[0]; e.target.value = ""; void uploadResource(key, file); }} /><small className="muted">上传文件或插入上游 .url 变量，最大 20 MB</small></div>}{referenceField === key && <div className="reference-list">{variables.length ? variables.map(v => <button key={v} onClick={() => insertReference(key, v)}><code>{`{{${v}}}`}</code></button>) : <p className="muted small">连接上游节点后可引用变量。</p>}</div>}</>
                : <input value={picked.data[key] || ""} placeholder={property.default} onChange={e => updateData(key, e.target.value)} />}
              </label>)}
              </fieldset>
              {picked.type === "start" && <div className="tip">用逗号分隔字段名，例如 topic,style。字段名以英文字母开头。</div>}
              {picked.type === "end" && <div className="tip">自动收集直接上游的文字、图片、音频和视频，作为工作流的最终输出。</div>}
              {results[picked.id] && <div className="node-detail"><h3>节点运行详情 · {statusNames[results[picked.id].status]}</h3>{results[picked.id].error && <p className="danger-text">{results[picked.id].error}</p>}<Progress result={results[picked.id]} /><Output value={results[picked.id].output ?? results[picked.id].text ?? "等待输出"} /><details><summary>输入 / 用量</summary><pre>{JSON.stringify({ inputs: results[picked.id].inputs, usage: results[picked.id].usage, elapsed_ms: results[picked.id].elapsed_ms }, null, 2)}</pre></details></div>}
              <button className="delete-node" disabled={locked} onClick={() => { edit({ nodes: graph.nodes.filter(n => n.id !== picked.id), edges: graph.edges.filter(e => e.source !== picked.id && e.target !== picked.id) }); setSelected(undefined); }}><Trash2 size={14} />删除节点</button>
            </> : <div className="empty-panel"><span className="empty-illustration"><WorkflowIcon size={32} strokeWidth={1.3} /></span><h2>从一个想法开始</h2><p>点击画布中的节点，<br />配置模型、提示词和变量。</p><div className="tip">试试直接运行示例工作流。演示模式无需 API Key。</div>{workflow && <label className="workflow-name">工作流名称<input disabled={locked} value={workflow.name} onChange={e => { setWorkflow({ ...workflow, name: e.target.value }); setDirty(true); }} /></label>}</div>)}
            {tab === "run" && (run ? <><div className="run-heading"><span className={`status-pill ${run.status}`}>{run.status === "running" && <LoaderCircle size={12} className="spin" />}{statusNames[run.status] || run.status}</span><span className="muted small">版本 {run.workflow_version}</span></div><p className="muted small">{new Date(run.created_at).toLocaleString("zh-CN")}</p>{connection && <div className="tip">{connection}</div>}{run.error && <div className="notice error">{run.error}</div>}{run.status === "running" && <button className="button full" onClick={stop}><Square size={13} />停止运行</button>}
              {Object.entries(run.outputs || {}).map(([key, value]) => <section className="result-block" key={key}><h3>{viewedGraph.nodes.find(n => n.id === key)?.data.label || key}</h3><Output value={value} /></section>)}
              {!Object.keys(run.outputs || {}).length && Object.entries(results).filter(([, r]) => r.text || r.output !== undefined || r.task_id).map(([key, result]) => <section className="result-block" key={key}><h3>{viewedGraph.nodes.find(n => n.id === key)?.data.label || key}</h3><Progress result={result} /><Output value={result.output ?? result.text ?? "等待输出"} /></section>)}
              <details className="run-inputs"><summary>本次运行输入</summary><pre>{JSON.stringify(run.inputs, null, 2)}</pre></details>
            </> : <div className="empty-panel"><Play size={30} strokeWidth={1.3} /><h2>等待下一次创作</h2><p>点击右上角「运行」，<br />在这里查看文字、图片、音频和视频。</p></div>)}
            {tab === "history" && <><span className="eyebrow">RECENT RUNS · 最近 50 次</span><h2>创作的每一步</h2><p className="muted small">点击记录回放当时的画布与节点结果。</p>{!history.length && <div className="tip">运行工作流后，记录会出现在这里。</div>}{history.map(item => <button disabled={busy || run?.status === "running"} key={item.id} className="history-item" onClick={() => replay(item)}><div><span className={`status-pill ${item.status}`}>{statusNames[item.status] || item.status}</span><span className="muted small">v{item.workflow_version}</span></div><strong>{Object.values(item.inputs).join(" · ").slice(0, 50)}</strong><span className="muted small">{new Date(item.created_at).toLocaleString("zh-CN")}</span></button>)}</>}
          </div>
          <div className="inspector-footer"><span className="live-dot" />本地创作空间 <button className="text-button" onClick={() => setShowSettings(true)}>模型设置 <ArrowUpRight size={12} /></button></div>
        </aside>
      </div>
    </div>
    {message && <div className="toast" role="status">{message}<button onClick={() => setMessage("")} aria-label="关闭提示"><X size={15} /></button></div>}
    {showSettings && <Settings close={() => setShowSettings(false)} />}
    {showInputs && <div className="modal-backdrop" onClick={() => setShowInputs(false)}><form className="modal" onClick={e => e.stopPropagation()} onSubmit={e => { e.preventDefault(); execute(); }}><div className="panel-heading"><div><span className="eyebrow">LET’S MAKE SOMETHING</span><h2>这次，想创作什么？</h2></div><button type="button" className="icon-button" onClick={() => setShowInputs(false)} aria-label="关闭"><X size={18} /></button></div><p className="muted">填写开始节点的输入，让想法沿着画布流动。</p>{fields.map(key => <label key={key}>{key}<textarea required rows={3} value={inputs[key] || ""} onChange={e => setInputs({ ...inputs, [key]: e.target.value })} /></label>)}<button className="button primary full" disabled={busy || !fields.length}><Play size={14} />开始运行</button></form></div>}
  </main>;
}
