/**
 * A Debug Adapter Protocol client over a WebSocket carrying one message per
 * frame (the API bridge does DAP's Content-Length framing).
 */
export interface DapSocket {
  send(data: string): void;
  close(): void;
  onmessage: ((e: { data: unknown }) => void) | null;
  onclose: ((e: unknown) => void) | null;
  onopen: ((e: unknown) => void) | null;
  readyState: number;
}

type Listener = (body: any) => void;

export class DapClient {
  private seq = 1;
  private pending = new Map<number, { resolve: (b: any) => void; reject: (e: Error) => void }>();
  private listeners = new Map<string, Listener[]>();
  private queue: string[] = [];
  closed = false;

  constructor(private socket: DapSocket) {
    socket.onopen = () => {
      for (const m of this.queue) socket.send(m);
      this.queue = [];
    };
    socket.onmessage = (e) => this.receive(String(e.data));
    socket.onclose = () => {
      this.closed = true;
      for (const p of this.pending.values()) p.reject(new Error("The debug session ended"));
      this.pending.clear();
      this.emit("$close", undefined);
    };
  }

  request<T = any>(command: string, args?: unknown): Promise<T> {
    if (this.closed) return Promise.reject(new Error("The debug session ended"));
    const seq = this.seq++;
    const text = JSON.stringify({ seq, type: "request", command, arguments: args ?? {} });
    return new Promise<T>((resolve, reject) => {
      this.pending.set(seq, { resolve, reject });
      if (this.socket.readyState === 1) this.socket.send(text);
      else this.queue.push(text);
    });
  }

  on(event: string, listener: Listener): () => void {
    this.listeners.set(event, [...(this.listeners.get(event) ?? []), listener]);
    return () => this.listeners.set(event, (this.listeners.get(event) ?? []).filter((l) => l !== listener));
  }

  close() {
    this.socket.close();
  }

  private emit(event: string, body: unknown) {
    this.listeners.get(event)?.forEach((l) => l(body));
  }

  private receive(text: string) {
    let msg: any;
    try {
      msg = JSON.parse(text);
    } catch {
      return;
    }
    if (msg.type === "response") {
      const p = this.pending.get(msg.request_seq);
      if (!p) return;
      this.pending.delete(msg.request_seq);
      if (msg.success) p.resolve(msg.body ?? {});
      else p.reject(new Error(msg.message || `${msg.command} failed`));
    } else if (msg.type === "event") {
      this.emit(msg.event, msg.body);
    }
  }
}
