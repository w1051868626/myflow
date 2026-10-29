"use client";

import { useEffect, useState } from "react";
import { X, ShieldCheck, ExternalLink } from "lucide-react";
import { api } from "@/api/client";

const providers = {
  deepseek: { name: "DeepSeek · 文本", url: "https://api.deepseek.com", keys: "https://platform.deepseek.com/api_keys" },
  minimax: { name: "MiniMax · 多模态", url: "https://api.minimax.cn/v1", keys: "https://platform.minimax.cn/user-center/basic-information/interface-key" },
  minimax_text: { name: "MiniMax · 文本专用（可选）", url: "https://api.minimax.cn/v1", keys: "https://platform.minimax.cn/user-center/basic-information/interface-key" },
};
type ProviderId = keyof typeof providers;

export default function Settings({ close }: { close: () => void }) {
  const [provider, setProvider] = useState<ProviderId>("deepseek");
  const [url, setUrl] = useState("");
  const [key, setKey] = useState("");
  const [configured, setConfigured] = useState(false);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let active = true;
    setLoading(true); setKey(""); setMessage(""); setUrl(providers[provider].url); setConfigured(false);
    api<{ base_url: string; configured: boolean }>("/provider/get", { provider })
      .then(p => { if (active) { setUrl(p.base_url); setConfigured(p.configured); } })
      .catch(e => { if (active) setMessage(e.message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [provider]);
  async function save() {
    setBusy(true);
    try {
      const p = await api<{ configured: boolean }>("/provider/save", { provider, base_url: url, api_key: key });
      setConfigured(p.configured); setKey(""); setMessage("设置已保存");
    } catch (e) { setMessage((e as Error).message); } finally { setBusy(false); }
  }
  return <div className="modal-backdrop" onClick={close}><section className="modal" role="dialog" aria-modal="true" aria-label="模型设置" onClick={e => e.stopPropagation()}>
    <div className="panel-heading"><div><span className="eyebrow">CONNECTIONS</span><h2>连接你的模型</h2></div><button className="icon-button" onClick={close} aria-label="关闭"><X size={18} /></button></div>
    <p className="muted">DeepSeek 与 MiniMax 分别保存连接。MiniMax 多模态使用按量 API Key；如文本模型需要 M Plan 密钥，请填写独立的文本专用连接。</p>
    <label>模型服务<select value={provider} disabled={busy} onChange={e => setProvider(e.target.value as ProviderId)}>{Object.entries(providers).map(([id, item]) => <option key={id} value={id}>{item.name}</option>)}</select></label>
    <label>Base URL<input value={url} disabled={loading || busy} onChange={e => setUrl(e.target.value)} placeholder={providers[provider].url} /></label>
    <label>API Key <span className="muted">{configured ? "已配置 · 留空保留" : "尚未配置"}</span><input type="password" disabled={loading || busy} autoComplete="off" value={key} onChange={e => setKey(e.target.value)} placeholder="填写此服务的 API Key" /></label>
    <div className="safe-note"><ShieldCheck size={17} /><span>密钥在后端加密存储，保存后不会返回浏览器。</span></div>
    <p className="muted small">文本专用连接未配置时复用 MiniMax 多模态连接。文本、图片可在工作流切换；语音、音乐和视频可前往模型试验台体验。</p>
    <a className="docs-link" href="/models" target="_blank" rel="noreferrer">打开 MiniMax 模型试验台 <ExternalLink size={13} /></a>
    <a className="docs-link" href={providers[provider].keys} target="_blank" rel="noreferrer">管理 {provider === "deepseek" ? "DeepSeek" : "MiniMax"} 密钥 <ExternalLink size={13} /></a>
    {message && <div className="notice" role="status">{message}</div>}
    <button className="button primary full" disabled={loading || busy || !url} onClick={save}>{busy ? "保存中…" : "保存连接"}</button>
  </section></div>;
}
