"use client";

import { useEffect, useState } from "react";
import { ArrowLeft, ExternalLink, FlaskConical, LoaderCircle, Play, RefreshCw, Settings2, X } from "lucide-react";
import { api, type Model } from "@/api/client";
import Settings from "./Settings";

type Preset = Model & { payload: Record<string, unknown>; docs: string; reference?: string; api_version?: "v1" | "v2" };
type Media = { kind: string; url: string; temporary?: boolean };
type Result = { result: Record<string, unknown>; media: Media[]; api_version?: "v1" | "v2" };
type Attempt = { model: string; kind: Model["kind"]; at: string; status: string; error?: string; response?: Result; api_version: "v1" | "v2" };
const kinds = { text: "文本", image: "图片", speech: "语音合成", music: "音乐", video: "视频", asr: "语音识别" };

function Preview({ response }: { response: Result }) {
  const choices = response.result.choices as { message?: { content?: string }; finish_reason?: string }[] | undefined;
  const text = choices?.[0]?.message?.content?.replace(/<think>[\s\S]*?<\/think>/g, "").trim();
  return <div className="lab-preview">{text && <p className="lab-text-result">{text}</p>}{choices?.[0]?.finish_reason === "length" && <p className="notice">输出触及 Token 上限，可调大 max_completion_tokens 后重新试用。</p>}{response.media.map((media, index) => {
    if (!media.url.startsWith("/artifacts/") && !/^https?:\/\//.test(media.url)) return null;
    return <figure key={index}>{media.kind === "image" ? <img src={media.url} alt="模型试用图片" />
      : media.kind === "video" ? <video controls preload="metadata" src={media.url} />
      : <audio controls preload="metadata" src={media.url} />}
      <figcaption><a href={media.url} target="_blank" rel="noreferrer">打开资源 <ExternalLink size={12} /></a>{media.temporary && <span>临时链接，请及时保存</span>}</figcaption></figure>;
  })}<details open={!response.media.length && !text}><summary>响应 JSON</summary><pre>{JSON.stringify(response.result, null, 2)}</pre></details></div>;
}

export default function ModelLab() {
  const [catalog, setCatalog] = useState<Preset[]>([]);
  const [kind, setKind] = useState<keyof typeof kinds>("text");
  const [model, setModel] = useState("");
  const [payload, setPayload] = useState("");
  const [file, setFile] = useState<File>();
  const [attempts, setAttempts] = useState<Attempt[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [settings, setSettings] = useState(false);
  const [discovered, setDiscovered] = useState("");
  const [taskId, setTaskId] = useState("");
  const [version, setVersion] = useState<"v1" | "v2">("v2");
  const picked = catalog.find(item => item.id === model);
  function select(item: Preset) {
    setModel(item.id); setPayload(JSON.stringify(item.payload, null, 2)); setFile(undefined); setError("");
  }
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("task_id")) { setTaskId(params.get("task_id") || ""); setVersion(params.get("api_version") === "v1" ? "v1" : "v2"); setKind("video"); }
    api<Preset[]>("/minimax/catalog").then(items => {
      setCatalog(items);
      const first = items.find(item => item.kind === (params.get("task_id") ? "video" : "text"));
      if (first) select(first);
    }).catch(e => setError(e.message));
  }, []);

  async function run() {
    setError("");
    let body: Record<string, unknown>;
    try {
      body = JSON.parse(payload);
      if (!body || Array.isArray(body) || typeof body !== "object") throw new Error("payload 必须是 JSON 对象");
    } catch (e) { setError(`JSON 格式错误：${(e as Error).message}`); return; }
    if (file && file.size > 20 * 1024 * 1024) { setError("音频文件不能超过 20 MB"); return; }
    setBusy(true);
    const attempt: Attempt = { model, kind, at: new Date().toLocaleString("zh-CN"), status: "已返回", api_version: picked?.api_version || "v1" };
    try {
      let file_base64: string | undefined;
      if (file) file_base64 = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).split(",")[1]);
        reader.onerror = () => reject(new Error("读取音频失败"));
        reader.readAsDataURL(file);
      });
      attempt.response = await api<Result>("/minimax/trial", { model, payload: body, file_base64, file_name: file?.name });
      const task = attempt.response.result.task_id;
      if (typeof task === "string" || typeof task === "number") {
        setTaskId(String(task)); setVersion(attempt.api_version); attempt.status = "任务已提交，待查询";
      }
    } catch (e) { attempt.status = "调用失败"; attempt.error = (e as Error).message; }
    finally { setAttempts(items => [attempt, ...items].slice(0, 50)); setBusy(false); }
  }
  async function query(id = taskId, api_version = version) {
    if (!id) { setError("请填写任务 ID"); return; }
    setBusy(true); setError("");
    try {
      const response = await api<Result>("/minimax/video/query", { task_id: id, api_version });
      setAttempts(items => [{ model: `视频任务 ${id}`, kind: "video" as const, at: new Date().toLocaleString("zh-CN"), status: "查询结果", response, api_version }, ...items].slice(0, 50));
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function discover() {
    setBusy(true); setError("");
    try {
      const result = await api<{ data?: { id: string }[] }>("/minimax/discover");
      setDiscovered((result.data || []).map(item => item.id).join("\n") || "接口未返回模型列表");
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function loadChecks() {
    setError("");
    try {
      const report = await api<{ checked_at?: string; models: { model: string; kind: Model["kind"]; status: string; detail?: string; media?: Media[]; api_version?: "v1" | "v2"; task_id?: string; text?: string }[] }>("/minimax/checks");
      if (!report.models.length) { setError("本机还没有批量实测记录，可先试用当前模型。"); return; }
      const labels: Record<string, string> = { succeeded: "实测成功", failed: "实测失败", submitted: "任务待完成", needs_input: "需要输入", empty_output: "返回空文本" };
      setAttempts(report.models.map(row => ({ model: row.model, kind: row.kind, at: report.checked_at ? new Date(report.checked_at).toLocaleString("zh-CN") : "",
        status: labels[row.status] || row.status, error: row.detail, api_version: row.api_version || "v1",
        response: { result: row.text ? { choices: [{ message: { content: row.text } }] } : { ...row }, media: row.media || [] },
      })));
    } catch (e) { setError((e as Error).message); }
  }
  return <main className="model-lab">
    <header className="lab-header"><a href="/" className="text-button"><ArrowLeft size={16} />工作流</a><div><span className="eyebrow">MODEL PLAYGROUND</span><h1><FlaskConical size={26} />MiniMax 模型试验台</h1></div><button className="button" onClick={() => setSettings(true)}><Settings2 size={15} />连接设置</button></header>
    <p className="muted">按能力切换模型，使用相同输入比较结果。每次点击仅调用当前模型，费用和可用权限以供应商账户为准。</p>
    <nav className="lab-tabs" aria-label="模型能力">{Object.entries(kinds).map(([id, title]) => <button key={id} disabled={busy} className={kind === id ? "active" : ""} onClick={() => { setKind(id as keyof typeof kinds); const first = catalog.find(item => item.kind === id); if (first) select(first); }}>{title}<span>{catalog.filter(item => item.kind === id).length}</span></button>)}</nav>
    <div className="lab-columns"><section className="lab-config">
      <label>模型<select value={model} disabled={busy} onChange={e => { const item = catalog.find(m => m.id === e.target.value); if (item) select(item); }}>{catalog.filter(item => item.kind === kind).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      {picked?.reference && <p className="notice">{picked.reference === "file" ? "请上传待识别的音频。" : picked.reference === "audio" ? "此模型需要参考音频，请在 payload 填写 audio_url 或 audio_base64。" : "此模型需要参考图片，请在 payload 中填写图片的公网 URL 或 Base64。"}</p>}
      <div className="lab-actions"><strong>JSON payload</strong><button disabled={busy || !picked} className="text-button" onClick={() => picked && setPayload(JSON.stringify(picked.payload, null, 2))}><RefreshCw size={13} />重置示例</button>{picked && <a href={picked.docs} target="_blank" rel="noreferrer" className="text-button">参数文档 <ExternalLink size={12} /></a>}</div>
      <textarea className="lab-json" aria-label="JSON payload" spellCheck={false} value={payload} disabled={busy} onChange={e => setPayload(e.target.value)} />
      {kind === "asr" && <label>音频文件（最大 20 MB）<input key={model} type="file" accept="audio/*" disabled={busy} onChange={e => setFile(e.target.files?.[0])} /></label>}
      <button className="button primary full" disabled={busy || !model} onClick={run}>{busy ? <LoaderCircle size={16} className="spin" /> : <Play size={15} />}试用当前模型</button>
      {error && <p className="notice error" role="alert">{error}</p>}
      <details className="lab-helper"><summary>查询视频任务</summary><label>任务 ID<input value={taskId} onChange={e => setTaskId(e.target.value)} /></label><label>接口版本<select value={version} onChange={e => setVersion(e.target.value as "v1" | "v2")}><option value="v2">H3 · v2</option><option value="v1">Hailuo / T2V / S2V · v1</option></select></label><button className="button" disabled={busy || !taskId} onClick={() => query()}>查询状态与视频</button></details>
      <details className="lab-helper"><summary>查询账户模型列表</summary><p className="muted small">从官方模型接口读取当前密钥可见的模型；完整试验目录包含历史型号，能否调用以实际返回为准。</p><button className="button" disabled={busy} onClick={discover}>查询账户模型</button>{discovered && <pre>{discovered}</pre>}</details>
    </section><section className="lab-results" aria-label="试用结果"><div className="lab-actions"><h2>试用记录</h2><button className="text-button" disabled={busy} onClick={loadChecks}>载入批量实测</button><button className="text-button" disabled={busy} onClick={() => setAttempts([])}><X size={13} />清空</button></div>{!attempts.some(item => item.kind === kind) && <div className="lab-empty"><FlaskConical size={34} /><p>选择模型后，点击“试用当前模型”。</p><span className="muted small">文本与图片也可在工作流节点中切换，音视频结果在这里预览。</span></div>}
      {attempts.filter(item => item.kind === kind).map((attempt, index) => <article className="lab-attempt" key={`${attempt.at}-${index}`}><div className="lab-actions"><strong>{attempt.model}</strong><span className={attempt.error ? "danger-text" : "muted"}>{attempt.status}</span></div><span className="muted small">{attempt.at}</span>{attempt.error && <p className="notice error">{attempt.error}</p>}{attempt.response && <Preview response={attempt.response} />}{attempt.response?.result.task_id !== undefined && <button className="button" disabled={busy} onClick={() => query(String(attempt.response?.result.task_id), attempt.api_version)}>查询此任务</button>}</article>)}
    </section></div>{settings && <Settings close={() => setSettings(false)} />}
  </main>;
}
