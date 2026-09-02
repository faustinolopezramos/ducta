/**
 * Tests for client.ts — the shared axios interceptors.
 *
 * The previous version of this file had 20 tests and exercised `client.ts` in
 * exactly one of them. The rest built a literal, reimplemented the interceptor's
 * logic inline, and asserted on their own reimplementation — one even carried
 * the comment "The actual implementation is in client.ts lines 31-47". 302 lines
 * of green that covered nothing, which is why the 401 path could resolve with
 * `undefined` for as long as it did.
 *
 * Everything here drives the real instance by swapping `defaults.adapter`, the
 * one technique that worked before. There is no `msw` in this project and none
 * is needed: the adapter *is* the seam.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AxiosAdapter, AxiosResponse, InternalAxiosRequestConfig } from "axios";

import client from "./client";
import { useAuthStore } from "../store/auth";

/** A JWT whose `exp` is `secondsFromNow` away. Only the payload is read. */
function makeToken(secondsFromNow: number): string {
  const payload = { sub: "u1", exp: Math.floor(Date.now() / 1000) + secondsFromNow };
  return `h.${btoa(JSON.stringify(payload))}.s`;
}

const VALID = () => makeToken(3600);
/** Past `getToken()`'s 30s skew buffer, so it is discarded on read. */
const ALREADY_STALE = () => makeToken(10);

function ok(config: InternalAxiosRequestConfig): AxiosResponse {
  return { data: { ok: true }, status: 200, statusText: "OK", headers: {}, config };
}

function httpError(status: number, config: InternalAxiosRequestConfig) {
  return Object.assign(new Error(`Request failed with status code ${status}`), {
    isAxiosError: true,
    config,
    response: { status, data: {}, statusText: "", headers: {}, config },
  });
}

/** Install an adapter for the duration of `fn`, then restore the original. */
async function withAdapter<T>(adapter: AxiosAdapter, fn: () => Promise<T>): Promise<T> {
  const previous = client.defaults.adapter;
  client.defaults.adapter = adapter;
  try {
    return await fn();
  } finally {
    client.defaults.adapter = previous;
  }
}

/**
 * Run `fn` with only `setTimeout` faked, driving the clock so the interceptor's
 * exponential backoff resolves without real waiting.
 *
 * That backoff is genuine wall-clock time — 1s for a single retry, 1+2+4=7s to
 * exhaust the budget — and these two tests alone were 8 of the suite's 9
 * seconds. `Date` is deliberately left real (`toFake` names setTimeout only):
 * the auth interceptor reads token `exp` through `Date.now()`, and freezing it
 * would couple these tests to logic they are not exercising.
 */
async function withFakeBackoff<T>(fn: () => Promise<T>): Promise<T> {
  vi.useFakeTimers({ toFake: ["setTimeout"] });
  try {
    const pending = fn();
    // Mark it handled while we drive the clock; the caller still sees the
    // rejection through the `await` below.
    pending.catch(() => {});
    // advanceTimersByTimeAsync flushes microtasks between timer callbacks,
    // which is what lets axios actually re-enter the adapter on each retry.
    await vi.advanceTimersByTimeAsync(10_000);
    return await pending;
  } finally {
    vi.useRealTimers();
  }
}

describe("client.ts interceptors", () => {
  beforeEach(() => {
    useAuthStore.setState({ token: VALID(), user: null });
    localStorage.clear();
    vi.restoreAllMocks();
    // Keep the interceptor's console.error out of the test output.
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    useAuthStore.setState({ token: null, user: null });
  });

  describe("request interceptor", () => {
    it("attaches the active token and the selected source", async () => {
      useAuthStore.setState({ token: "test_token_123", user: null });
      localStorage.setItem("ducta:selected-source", "my_datasource");

      const adapter = vi.fn(async (config) => ok(config));
      await withAdapter(adapter as unknown as AxiosAdapter, () =>
        client.get("/interceptor-contract"),
      );

      const config = adapter.mock.calls[0][0];
      expect(config.headers.get("Authorization")).toBe("Bearer test_token_123");
      expect(config.params).toMatchObject({ source: "my_datasource" });
    });

    it("sends no Authorization header when logged out", async () => {
      useAuthStore.setState({ token: null, user: null });

      const adapter = vi.fn(async (config) => ok(config));
      await withAdapter(adapter as unknown as AxiosAdapter, () => client.get("/anon"));

      expect(adapter.mock.calls[0][0].headers.get("Authorization")).toBeFalsy();
    });
  });

  describe("401 → token refresh", () => {
    it("retries the request with the refreshed token", async () => {
      const fresh = VALID();
      vi.spyOn(useAuthStore.getState(), "refreshTokenAsync").mockImplementation(async () => {
        useAuthStore.setState({ token: fresh });
      });

      let call = 0;
      const adapter = vi.fn(async (config) => {
        call += 1;
        if (call === 1) throw httpError(401, config);
        return ok(config);
      });

      const response = await withAdapter(adapter as unknown as AxiosAdapter, () =>
        client.get("/needs-auth"),
      );

      expect(response.status).toBe(200);
      expect(adapter).toHaveBeenCalledTimes(2);
      expect(adapter.mock.calls[1][0].headers.get("Authorization")).toBe(`Bearer ${fresh}`);
    });

    it("rejects — never resolves with undefined — when the refresh yields no usable token", async () => {
      // The regression. `getToken()` discards a token inside its 30s skew
      // buffer, so a "successful" refresh can leave nothing to retry with. The
      // interceptor used to fall off the end and resolve with `undefined`,
      // handing the caller a TypeError on `response.data` instead of an error.
      vi.spyOn(useAuthStore.getState(), "refreshTokenAsync").mockImplementation(async () => {
        useAuthStore.setState({ token: ALREADY_STALE() });
      });

      const adapter = vi.fn(async (config) => {
        throw httpError(401, config);
      });

      await expect(
        withAdapter(adapter as unknown as AxiosAdapter, () => client.get("/needs-auth")),
      ).rejects.toBeDefined();
    });

    it("logs out and signals the app when the refresh itself fails", async () => {
      vi.spyOn(useAuthStore.getState(), "refreshTokenAsync").mockRejectedValue(
        new Error("no session"),
      );
      const onUnauthorized = vi.fn();
      globalThis.addEventListener("ducta:unauthorized", onUnauthorized);

      const adapter = vi.fn(async (config) => {
        throw httpError(401, config);
      });

      await expect(
        withAdapter(adapter as unknown as AxiosAdapter, () => client.get("/needs-auth")),
      ).rejects.toBeDefined();

      globalThis.removeEventListener("ducta:unauthorized", onUnauthorized);
      expect(useAuthStore.getState().token).toBeNull();
      expect(onUnauthorized).toHaveBeenCalled();
    });

    it("refreshes once for concurrent 401s and retries both", async () => {
      const fresh = VALID();
      const refresh = vi
        .spyOn(useAuthStore.getState(), "refreshTokenAsync")
        .mockImplementation(async () => {
          await new Promise((r) => setTimeout(r, 5));
          useAuthStore.setState({ token: fresh });
        });

      const seen = new Set<string>();
      const adapter = vi.fn(async (config) => {
        const url = config.url as string;
        if (!seen.has(url)) {
          seen.add(url);
          throw httpError(401, config);
        }
        return ok(config);
      });

      const [a, b] = await withAdapter(adapter as unknown as AxiosAdapter, () =>
        Promise.all([client.get("/one"), client.get("/two")]),
      );

      expect(a.status).toBe(200);
      expect(b.status).toBe(200);
      expect(refresh).toHaveBeenCalledTimes(1);
    });

    it("does not attempt a refresh when skipRetry is set", async () => {
      const refresh = vi.spyOn(useAuthStore.getState(), "refreshTokenAsync");
      const adapter = vi.fn(async (config) => {
        throw httpError(401, config);
      });

      await expect(
        withAdapter(adapter as unknown as AxiosAdapter, () =>
          client.get("/no-retry", { _retryConfig: { skipRetry: true } } as never),
        ),
      ).rejects.toBeDefined();

      expect(refresh).not.toHaveBeenCalled();
      expect(adapter).toHaveBeenCalledTimes(1);
    });
  });

  describe("transient errors", () => {
    it("retries a 429 and returns the eventual success", async () => {
      let call = 0;
      const adapter = vi.fn(async (config) => {
        call += 1;
        if (call === 1) throw httpError(429, config);
        return ok(config);
      });

      const response = await withFakeBackoff(() =>
        withAdapter(adapter as unknown as AxiosAdapter, () => client.get("/rate-limited")),
      );

      expect(response.status).toBe(200);
      expect(adapter).toHaveBeenCalledTimes(2);
    });

    it("gives up after the retry budget and rejects", async () => {
      const adapter = vi.fn(async (config) => {
        throw httpError(429, config);
      });

      await expect(
        withFakeBackoff(() =>
          withAdapter(adapter as unknown as AxiosAdapter, () => client.get("/always-429")),
        ),
      ).rejects.toBeDefined();

      // 1 original + 3 retries (MAX_RETRIES).
      expect(adapter).toHaveBeenCalledTimes(4);
    });

    it("does not retry other 4xx responses", async () => {
      const adapter = vi.fn(async (config) => {
        throw httpError(404, config);
      });

      await expect(
        withAdapter(adapter as unknown as AxiosAdapter, () => client.get("/missing")),
      ).rejects.toBeDefined();

      expect(adapter).toHaveBeenCalledTimes(1);
    });
  });
});
