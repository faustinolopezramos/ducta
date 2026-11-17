import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
vi.mock("../client", () => ({ default: { get: (...args: unknown[]) => get(...args) } }));

import { useStreamRows, type StreamRowsWatch } from "./streamRows";

function setup(watch: StreamRowsWatch) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  return renderHook((w: StreamRowsWatch) => useStreamRows("run-1", "clean", 50, w), { wrapper, initialProps: watch });
}

beforeEach(() => {
  get.mockReset();
  get.mockResolvedValue({ data: { node: "clean", available: true, columns: [], rows: [] } });
});

describe("useStreamRows", () => {
  it("reads once, then again only when a new batch lands", async () => {
    const { rerender } = setup({ live: true, paused: false, batch: 7 });
    await waitFor(() => expect(get).toHaveBeenCalledTimes(1));
    rerender({ live: true, paused: false, batch: 7 }); // a status poll with no new batch
    expect(get).toHaveBeenCalledTimes(1);
    rerender({ live: true, paused: false, batch: 8 });
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
  });

  it("does not re-read while paused, and catches up on resume", async () => {
    const { rerender } = setup({ live: true, paused: false, batch: 7 });
    await waitFor(() => expect(get).toHaveBeenCalledTimes(1));
    rerender({ live: true, paused: true, batch: 9 });
    expect(get).toHaveBeenCalledTimes(1);
    rerender({ live: true, paused: false, batch: 9 });
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
  });

  it("reads a stopped stream once, whatever its batch says", async () => {
    const { rerender } = setup({ live: false, paused: false, batch: 7 });
    await waitFor(() => expect(get).toHaveBeenCalledTimes(1));
    rerender({ live: false, paused: false, batch: 8 });
    expect(get).toHaveBeenCalledTimes(1);
  });
});
