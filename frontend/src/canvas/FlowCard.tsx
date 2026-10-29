"use client";

import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import {
  ArrowUpRight,
  AudioLines,
  Check,
  Circle,
  Image,
  LoaderCircle,
  Mic,
  Music,
  Sparkles,
  Text,
  Video,
  X,
  Play,
} from "lucide-react";
import type { Kind, NodeResult } from "@/api/client";
import { memo } from "react";

export const icons = {
  start: Play,
  llm: Sparkles,
  image: Image,
  speech: AudioLines,
  music: Music,
  video: Video,
  asr: Mic,
  template: Text,
  end: ArrowUpRight,
};
export const titles = {
  start: "开始",
  llm: "文本生成",
  image: "图像生成",
  speech: "语音合成",
  music: "音乐生成",
  video: "视频生成",
  asr: "语音识别",
  template: "模板拼接",
  end: "输出",
};
export const statusNames: Record<string, string> = {
  running: "运行中",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消",
  interrupted: "已中断",
  skipped: "已跳过",
};
export type CardNode = Node<{ kind: Kind; config: Record<string, string>; result?: NodeResult }, "card">;

function FlowCard({ id, data, selected }: NodeProps<CardNode>) {
  const { kind, config, result } = data;
  const Icon = icons[kind];
  const state = result?.status;
  const preview = result?.text || (typeof result?.output === "string" ? result.output : "");
  return (
    <div className={`flow-card ${selected ? "selected" : ""} ${state || ""}`}>
      {kind !== "start" && <Handle type="target" position={Position.Left} />}
      <div className="card-top">
        <span className={`node-icon ${kind}`}>
          <Icon size={17} />
        </span>
        <span className="card-kind">{titles[kind]}</span>
        <span className="card-state">
          {state === "running" ? (
            <LoaderCircle size={14} className="spin" />
          ) : state === "succeeded" ? (
            <Check size={14} />
          ) : state === "failed" ? (
            <X size={14} />
          ) : (
            <Circle size={8} />
          )}
        </span>
      </div>
      <strong>{config.label || titles[kind]}</strong>
      <p className="card-description">
        {kind === "start"
          ? `输入 · ${config.fields || "topic"}`
          : config.model || (kind === "template" ? "整理与组合文本" : "收集创作结果")}
      </p>
      {preview && <div className="card-preview">{preview.slice(-140)}</div>}
      {result?.progress && state === "running" && <div className="card-preview">{result.progress}</div>}
      {result?.error && <div className="card-error">{result.error}</div>}
      <div className="card-bottom">
        <code>{id}</code>
        <span>{result?.elapsed_ms !== undefined ? `${(result.elapsed_ms / 1000).toFixed(2)}s` : ""}</span>
      </div>
      {kind !== "end" && <Handle type="source" position={Position.Right} />}
    </div>
  );
}

export default memo(
  FlowCard,
  (previous, next) => previous.id === next.id && previous.data === next.data && previous.selected === next.selected,
);
