import { act, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { useFileSave } from "./useFileSave";

const calls: any[] = [];
let respond: (vars: any, opts: any) => void = () => {};
vi.mock("../../api/mutations", () => ({
  useWriteWorkspaceFile: () => ({
    isPending: false,
    mutate: (vars: any, opts: any) => {
      calls.push(vars);
      respond(vars, opts);
    },
  }),
}));

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>
);

describe("useFileSave", () => {
  it("saves against the version it opened, and holds both sides on a conflict", async () => {
    respond = (_v, opts) =>
      opts.onError({ response: { status: 409, data: { detail: { content: "theirs\n", version: "v2" } } } });
    const { result } = renderHook(() => useFileSave("src/a.py", "v1"), { wrapper });
    let failed: Promise<void> | undefined;
    act(() => {
      failed = result.current.save("mine\n");
      failed.catch(() => {});
    });
    await expect(failed).rejects.toMatchObject({ response: { status: 409 } });
    expect(calls.at(-1)).toEqual({ path: "src/a.py", content: "mine\n", expectedVersion: "v1" });
    expect(result.current.conflict).toEqual({ mine: "mine\n", theirs: "theirs\n", version: "v2" });

    const saved = vi.fn();
    respond = (_v, opts) => opts.onSuccess();
    act(() => {
      result.current.keepMine();
    });
    expect(calls.at(-1)).toEqual({ path: "src/a.py", content: "mine\n", expectedVersion: "v2" });
    expect(result.current.conflict).toBeNull();
    expect(saved).not.toHaveBeenCalled();
  });

  it("settles with the save, so the editor can tell a failed one", async () => {
    const saved = vi.fn();
    const { result } = renderHook(() => useFileSave("src/a.py", "v1", saved), { wrapper });
    respond = (_v, opts) => opts.onSuccess();
    await act(() => result.current.save("ok\n"));
    expect(saved).toHaveBeenCalledTimes(1);

    respond = (_v, opts) => opts.onError({ response: { status: 500 } });
    await expect(act(() => result.current.save("boom\n"))).rejects.toMatchObject({ response: { status: 500 } });
    expect(result.current.conflict).toBeNull();
  });
});
