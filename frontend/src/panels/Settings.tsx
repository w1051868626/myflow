"use client";

import { useEffect, useState } from "react";
import { X, ShieldCheck, ExternalLink } from "lucide-react";
import { api } from "@/api/client";

export default function Settings({ close }: { close: () => void }) {
  const [url, setUrl] = useState("");
  const [key, setKey] = useState("");
  const [configured, setConfigured] = useState(false);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { api<{ base_url: string; configured: boolean }>("/provider").then(p => { setUrl(p.base_url); setConfigured(p.configured); }).catch(e => setMessage(e.message)); }, []);
  async function save() {
    setBusy(true);
    try {
      const p = await api<{ configured: boolean }>("/provider", { method: "PUT", body: JSON.stringify({ base_url: url, api_key: key }) });
      setConfigured(p.configured); setKey(""); setMessage("设置已保存");
    } catch (e) { setMessage((e as Error).message); } finally { setBusy(false); }
  }
  return <div className="modal-backdrop" onClick={close}><section className="modal" role="dialog" aria-modal="true" aria-label="模型设置" onClick={e => e.stopPropagation()}>
    <div className="panel-heading"><div><span className="eyebrow">CONNECTIONS</span><h2>连接你的模型</h2></div><button className="icon-button" onClick={close} aria-label="关闭"><X size={18} /></button></div>
    <p className="muted">支持 OpenAI 兼容的文本与图像生成接口。演示模型无需配置。</p>
    <label>Base URL<input value={url} onChange={e => setUrl(e.target.value)} placeholder="https://api.openai.com/v1" /></label>
    <label>API Key <span className="muted">{configured ? "已配置 · 留空保留" : "尚未配置"}</span><input type="password" autoComplete="off" value={key} onChange={e => setKey(e.target.value)} placeholder="sk-…" /></label>
    <div className="safe-note"><ShieldCheck size={17} /><span>密钥在后端加密存储，保存后不会返回浏览器。</span></div>
    <p className="muted small">模型列表由后端 models.yaml 管理。不同供应商的图像接口参数可能不同，请使用兼容 /images/generations 的服务。</p>
    <a className="docs-link" href="https://platform.openai.com/api-keys" target="_blank" rel="noreferrer">管理 OpenAI 密钥 <ExternalLink size={13} /></a>
    {message && <div className="notice" role="status">{message}</div>}
    <button className="button primary full" disabled={busy || !url} onClick={save}>{busy ? "保存中…" : "保存连接"}</button>
  </section></div>;
}
