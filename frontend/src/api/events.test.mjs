import assert from "node:assert/strict";
import { test } from "node:test";
import { api } from "./client.ts";
import { readEvents, subscribeRun } from "./events.ts";

function body(text, splitBytes = false) {
  const bytes = new TextEncoder().encode(text);
  return new ReadableStream({
    start(controller) {
      if (splitBytes) for (const byte of bytes) controller.enqueue(Uint8Array.of(byte));
      else controller.enqueue(bytes);
      controller.close();
    },
  });
}

test("POST payloads and empty delete responses use the shared API client", async t => {
  const requests = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    requests.push({ url, ...options });
    return new Response(null, { status: 204 });
  });
  assert.equal(await api("/workflows/delete", { id: "workflow-1" }), undefined);
  assert.equal(requests[0].method, "POST");
  assert.equal(requests[0].url, "/api/workflows/delete");
  assert.deepEqual(JSON.parse(requests[0].body), { id: "workflow-1" });
});

test("SSE handles byte-split UTF-8, CRLF, multiline data, and heartbeats", async () => {
  const text = ': heartbeat\r\nid: 12\r\ndata: {"type":"llm_token",\r\ndata: "data":{"text":"你好🌱"}}\r\n\r\n'
    + 'id: 13\ndata: {"type":"run_finished","data":{"status":"succeeded"}}\n\n';
  const messages = [];
  for await (const message of readEvents(body(text, true))) messages.push(message);
  assert.equal(messages.length, 2);
  assert.equal(messages[0].id, "12");
  assert.equal(messages[0].event.data.text, "你好🌱");
  assert.equal(messages[1].event.type, "run_finished");
});

test("disconnect resumes via POST id/after payload, then terminal event stops retries", { timeout: 5000 }, async t => {
  const requests = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    requests.push({ url, ...options });
    const text = requests.length === 1
      ? 'id: 42\ndata: {"type":"llm_token","data":{"text":"a"}}\n\n'
      : 'id: 43\ndata: {"type":"run_finished","data":{"status":"succeeded"}}\n\n';
    return new Response(body(text), { headers: { "Content-Type": "text/event-stream" } });
  });
  const received = [];
  let subscription;
  try {
    await new Promise(resolve => {
      subscription = subscribeRun("run-1", event => {
        received.push(event.type);
        if (event.type === "run_finished") resolve();
      }, () => {});
    });
    assert.deepEqual(received, ["llm_token", "run_finished"]);
    assert.equal(requests.length, 2);
    assert.equal(requests[0].url, "/api/runs/events");
    assert.equal(requests[0].method, "POST");
    assert.deepEqual(JSON.parse(requests[0].body), { id: "run-1", after: 0 });
    assert.deepEqual(JSON.parse(requests[1].body), { id: "run-1", after: 42 });
    assert.equal(requests[1].signal.aborted, true);
  } finally { subscription?.close(); }
});

test("closing a subscription aborts its in-flight request without reconnecting", async t => {
  let signal;
  t.mock.method(globalThis, "fetch", (_url, options) => {
    signal = options.signal;
    return new Promise((_resolve, reject) => signal.addEventListener("abort", () => reject(signal.reason), { once: true }));
  });
  const subscription = subscribeRun("run-1", () => assert.fail("closed stream received an event"), () => {});
  subscription.close();
  assert.equal(signal.aborted, true);
});

test("SSE-002 stream_closed ends the subscription without reconnecting", { timeout: 5000 }, async t => {
  const requests = [];
  t.mock.method(globalThis, "fetch", async (_url, options) => {
    requests.push(options);
    return new Response(body('data: {"type":"stream_closed","data":{"status":"succeeded"}}\n\n'));
  });
  const received = [];
  let subscription;
  try {
    await new Promise(resolve => {
      subscription = subscribeRun("completed-run", event => {
        received.push(event.type);
        resolve();
      }, () => {});
    });
    assert.deepEqual(received, ["stream_closed"]);
    assert.equal(requests[0].signal.aborted, true);
    // Wait beyond the existing one-second reconnect interval to catch a retry.
    await new Promise(resolve => setTimeout(resolve, 1100));
    assert.equal(requests.length, 1);
  } finally { subscription?.close(); }
});
