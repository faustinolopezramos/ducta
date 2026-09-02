import { useState, useEffect, useRef, useCallback } from "react";
import { buildTerminalWsUrl } from "./wsUtils";

export type TerminalStatus = "connecting" | "connected" | "disconnected" | "disabled" | "unsupported";

// Caps the accumulated buffer so a long-lived terminal session can't grow
// output (and the per-message re-render cost of parsing it) without bound.
const MAX_OUTPUT_CHARS = 200_000;

export function useWebTerminal() {
  const [status, setStatus] = useState<TerminalStatus>("connecting");
  const [output, setOutput] = useState<string>("");
  const wsRef = useRef<WebSocket | null>(null);
  const connectionIdRef = useRef(0);

  const appendOutput = useCallback((chunk: string) => {
    setOutput((prev) => {
      const next = prev + chunk;
      return next.length > MAX_OUTPUT_CHARS ? next.slice(-MAX_OUTPUT_CHARS) : next;
    });
  }, []);

  const connect = useCallback(() => {
    const connectionId = connectionIdRef.current + 1;
    connectionIdRef.current = connectionId;
    wsRef.current?.close();
    wsRef.current = null;
    setStatus("connecting");
    setOutput("");

    // Token is NOT appended to the URL. The httpOnly access_token cookie is
    // sent automatically during the WebSocket handshake (see
    // routes/terminal.py::_extract_token, which never reads a query param).
    // Putting the JWT in query params would expose it in server logs and
    // browser history.
    const ws = new WebSocket(buildTerminalWsUrl());
    wsRef.current = ws;

    const isCurrentConnection = () => connectionIdRef.current === connectionId;

    ws.onopen = () => {
      if (!isCurrentConnection()) return;
      setStatus("connected");
    };

    ws.onmessage = (event) => {
      if (!isCurrentConnection()) return;
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === "output" && msg.data) {
          appendOutput(msg.data);
        }
      } catch (err) {
        appendOutput(event.data);
      }
    };

    ws.onerror = () => {
      if (!isCurrentConnection()) return;
      setStatus("disconnected");
    };

    ws.onclose = (event) => {
      if (!isCurrentConnection()) return;
      wsRef.current = null;
      if (event.code === 1008 && event.reason === "Terminal disabled") {
        setStatus("disabled");
      } else if (event.code === 1011 && event.reason?.includes("not supported")) {
        setStatus("unsupported");
      } else {
        setStatus("disconnected");
      }
    };
  }, [appendOutput]);

  const sendInput = useCallback((data: string) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "input", data }));
    }
  }, []);

  const sendResize = useCallback((cols: number, rows: number) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "resize", cols, rows }));
    }
  }, []);

  const clear = useCallback(() => {
    setOutput("");
  }, []);

  useEffect(() => {
    // Opening the socket is exactly what an effect is for; `connect` clears the
    // output buffer for the new connection on its way in.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    connect();
    return () => {
      connectionIdRef.current += 1;
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [connect]);

  return {
    status,
    output,
    sendInput,
    sendResize,
    clear,
    reconnect: connect,
  };
}
