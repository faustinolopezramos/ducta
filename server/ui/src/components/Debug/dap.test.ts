import { describe, expect, it } from "vitest";
import { DapClient, type DapSocket } from "./dap";

function fake() {
  const sent: any[] = [];
  const socket: DapSocket = { readyState: 1, send: (d) => sent.push(JSON.parse(d)), close: () => socket.onclose?.({}), onmessage: null, onclose: null, onopen: null };
  const push = (m: object) => socket.onmessage?.({ data: JSON.stringify(m) });
  return { socket, sent, push };
}

describe("DapClient", () => {
  it("matches responses by request_seq and rejects failures", async () => {
    const f = fake();
    const c = new DapClient(f.socket);
    const ok = c.request("threads");
    const bad = c.request("evaluate", { expression: "x" });
    f.push({ type: "response", request_seq: f.sent[0].seq, success: true, command: "threads", body: { threads: [] } });
    f.push({ type: "response", request_seq: f.sent[1].seq, success: false, command: "evaluate", message: "name 'x' is not defined" });
    await expect(ok).resolves.toEqual({ threads: [] });
    await expect(bad).rejects.toThrow("not defined");
  });

  it("delivers events", () => {
    const f = fake();
    const c = new DapClient(f.socket);
    const got: any[] = [];
    c.on("stopped", (b) => got.push(b));
    f.push({ type: "event", event: "stopped", body: { reason: "breakpoint", threadId: 5 } });
    expect(got).toEqual([{ reason: "breakpoint", threadId: 5 }]);
  });
});
