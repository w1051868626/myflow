import type { RunEvent } from "./client";

// Fetch supports POST streams; native EventSource only issues GET requests.
export async function* readEvents(body: ReadableStream<Uint8Array>) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "",
    id = "",
    data: string[] = [];
  try {
    while (true) {
      const chunk = await reader.read();
      buffer += chunk.done ? decoder.decode() : decoder.decode(chunk.value, { stream: true });
      let end: number;
      while ((end = buffer.indexOf("\n")) !== -1) {
        const line = buffer.slice(0, end).replace(/\r$/, "");
        buffer = buffer.slice(end + 1);
        if (!line) {
          if (data.length) yield { id, event: JSON.parse(data.join("\n")) as RunEvent };
          data = [];
        } else if (!line.startsWith(":")) {
          const colon = line.indexOf(":");
          const field = colon < 0 ? line : line.slice(0, colon);
          const value = colon < 0 ? "" : line.slice(colon + 1).replace(/^ /, "");
          if (field === "id" && !value.includes("\0")) id = value;
          if (field === "data") data.push(value);
        }
      }
      if (chunk.done) break;
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

export function subscribeRun(id: string, onEvent: (event: RunEvent) => void, onConnection: (message: string) => void) {
  const controller = new AbortController();
  const { signal } = controller;
  let cursor = 0;
  let retry: ReturnType<typeof setTimeout> | undefined;

  async function connect() {
    if (signal.aborted) return;
    try {
      const response = await fetch("/api/runs/events", {
        method: "POST",
        signal,
        headers: { Accept: "text/event-stream", "Content-Type": "application/json" },
        body: JSON.stringify({ id, after: cursor }),
      });
      if (!response.ok || !response.body) throw new Error(`事件流请求失败 (${response.status})`);
      onConnection("");
      for await (const message of readEvents(response.body)) {
        if (signal.aborted) return;
        onEvent(message.event);
        if (message.id) cursor = Number(message.id);
        if (message.event.type === "run_finished" || message.event.type === "stream_closed") {
          controller.abort();
          return;
        }
      }
    } catch {
      if (signal.aborted) return;
    }
    if (!signal.aborted) {
      onConnection("连接中断，正在自动重连…");
      retry = setTimeout(() => {
        void connect();
      }, 1000);
    }
  }
  void connect();
  return {
    close() {
      clearTimeout(retry);
      controller.abort();
    },
  };
}
