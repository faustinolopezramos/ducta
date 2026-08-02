import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useWebTerminal } from "./useWebTerminal";

class MockWebSocket {
  static readonly OPEN = 1;
  static instances: MockWebSocket[] = [];
  readonly url: string;
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  close = vi.fn(() => {
    this.readyState = 3;
  });
  send = vi.fn();

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }
}

describe("useWebTerminal", () => {
  afterEach(() => {
    MockWebSocket.instances = [];
    vi.unstubAllGlobals();
  });

  it("closes the previous socket and ignores its late close event after reconnecting", () => {
    vi.stubGlobal("WebSocket", MockWebSocket);
    const { result, unmount } = renderHook(() => useWebTerminal());
    const first = MockWebSocket.instances[0];

    act(() => result.current.reconnect());
    const second = MockWebSocket.instances[1];

    expect(first.close).toHaveBeenCalledOnce();
    expect(second.url).toContain("/api/ws/terminal");

    act(() => first.onclose?.({ code: 1000, reason: "" } as CloseEvent));
    expect(result.current.status).toBe("connecting");

    act(() => second.onopen?.());
    expect(result.current.status).toBe("connected");

    unmount();
    expect(second.close).toHaveBeenCalledOnce();
  });
});
