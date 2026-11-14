import { describe, expect, it } from "vitest";
import { JsonRpcConnection, type Socket } from "./jsonrpc";

function fakeSocket() {
  const sent: any[] = [];
  const socket: Socket = {
    readyState: 0,
    send: (d) => sent.push(JSON.parse(d)),
    close: () => socket.onclose?.({}),
    onmessage: null,
    onclose: null,
    onopen: null,
  };
  const open = () => {
    (socket as any).readyState = 1;
    socket.onopen?.({});
  };
  const reply = (m: object) => socket.onmessage?.({ data: JSON.stringify({ jsonrpc: "2.0", ...m }) });
  return { socket, sent, open, reply };
}

describe("JsonRpcConnection", () => {
  it("queues until open, then matches responses to requests", async () => {
    const f = fakeSocket();
    const c = new JsonRpcConnection(f.socket);
    const answer = c.request("initialize", {});
    expect(f.sent).toHaveLength(0);
    f.open();
    expect(f.sent[0]).toMatchObject({ id: 1, method: "initialize" });
    f.reply({ id: 1, result: { capabilities: {} } });
    await expect(answer).resolves.toEqual({ capabilities: {} });
  });

  it("delivers notifications and answers the server's configuration requests", () => {
    const f = fakeSocket();
    const c = new JsonRpcConnection(f.socket);
    f.open();
    const seen: any[] = [];
    c.on("textDocument/publishDiagnostics", (p) => seen.push(p));
    f.reply({ method: "textDocument/publishDiagnostics", params: { uri: "u", diagnostics: [] } });
    f.reply({ id: 7, method: "workspace/configuration", params: { items: [{}, {}] } });
    expect(seen).toEqual([{ uri: "u", diagnostics: [] }]);
    expect(f.sent.at(-1)).toEqual({ jsonrpc: "2.0", id: 7, result: [{}, {}] });
  });

  it("fails pending requests when the socket closes", async () => {
    const f = fakeSocket();
    const c = new JsonRpcConnection(f.socket);
    f.open();
    const answer = c.request("textDocument/hover", {});
    f.socket.close();
    await expect(answer).rejects.toThrow("disconnected");
  });
});

import { hoverMarkdown, toFileUri, toMonacoRange } from "./session";

describe("LSP shapes", () => {
  it("renders every hover shape as markdown", () => {
    expect(hoverMarkdown({ kind: "plaintext", value: "def f() -> int" })).toEqual(["```python\ndef f() -> int\n```"]);
    expect(hoverMarkdown({ kind: "markdown", value: "**x**" })).toEqual(["**x**"]);
    expect(hoverMarkdown(["a", { language: "python", value: "b" }])).toEqual(["a", "```python\nb\n```"]);
  });
  it("converts positions and paths", () => {
    expect(toMonacoRange({ start: { line: 0, character: 4 }, end: { line: 1, character: 0 } })).toEqual({
      startLineNumber: 1, startColumn: 5, endLineNumber: 2, endColumn: 1,
    });
    expect(toFileUri("/tmp/my project/src/a.py")).toBe("file:///tmp/my%20project/src/a.py");
  });
});
