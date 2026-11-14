/**
 * JSON-RPC 2.0 over a WebSocket that carries one message per frame — the
 * API's language-server bridge does the LSP Content-Length framing.
 */
export interface Socket {
  send(data: string): void;
  close(): void;
  onmessage: ((e: { data: unknown }) => void) | null;
  onclose: ((e: unknown) => void) | null;
  onopen: ((e: unknown) => void) | null;
  readyState: number;
}

type Handler = (params: any) => void;

export class JsonRpcConnection {
  private nextId = 1;
  private pending = new Map<number, { resolve: (v: any) => void; reject: (e: Error) => void }>();
  private handlers = new Map<string, Handler[]>();
  private queue: string[] = [];
  closed = false;

  constructor(private socket: Socket) {
    socket.onopen = () => {
      for (const m of this.queue) socket.send(m);
      this.queue = [];
    };
    socket.onmessage = (e) => this.receive(String(e.data));
    socket.onclose = () => {
      this.closed = true;
      for (const p of this.pending.values()) p.reject(new Error("language server disconnected"));
      this.pending.clear();
      this.handlers.get("$close")?.forEach((h) => h(undefined));
    };
  }

  private post(message: object) {
    const text = JSON.stringify({ jsonrpc: "2.0", ...message });
    if (this.socket.readyState === 1) this.socket.send(text);
    else this.queue.push(text);
  }

  request<T = any>(method: string, params?: unknown): Promise<T> {
    if (this.closed) return Promise.reject(new Error("language server disconnected"));
    const id = this.nextId++;
    return new Promise<T>((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.post({ id, method, params });
    });
  }

  notify(method: string, params?: unknown) {
    if (!this.closed) this.post({ method, params });
  }

  on(method: string, handler: Handler): () => void {
    const list = this.handlers.get(method) ?? [];
    list.push(handler);
    this.handlers.set(method, list);
    return () => this.handlers.set(method, (this.handlers.get(method) ?? []).filter((h) => h !== handler));
  }

  close() {
    this.socket.close();
  }

  private receive(text: string) {
    let msg: any;
    try {
      msg = JSON.parse(text);
    } catch {
      return;
    }
    if (msg.id != null && (("result" in msg) || ("error" in msg)) && this.pending.has(msg.id)) {
      const p = this.pending.get(msg.id)!;
      this.pending.delete(msg.id);
      if (msg.error) p.reject(new Error(msg.error.message ?? "language server error"));
      else p.resolve(msg.result);
      return;
    }
    if (msg.method && msg.id != null) {
      // A request from the server (workspace/configuration, window/workDoneProgress/create…):
      // answer so it does not wait; configuration gets one empty object per item.
      const result = msg.method === "workspace/configuration" ? (msg.params?.items ?? []).map(() => ({})) : null;
      this.post({ id: msg.id, result });
      return;
    }
    if (msg.method) this.handlers.get(msg.method)?.forEach((h) => h(msg.params));
  }
}
