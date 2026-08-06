import axios, { AxiosError, AxiosInstance, AxiosResponse, InternalAxiosRequestConfig } from "axios";
import { getToken, useAuthStore } from "../store/auth";
import { StorageService } from "../utils/storage";
import { normalizeSourceInput } from "../utils/sourcePath";

// ─────────────────────────────────────────────
// API CLIENT — Axios instances with shared interceptors
// Both the default client (30s timeout) and the execution client (5min timeout)
// use the same auth, source-injection, token-refresh, and retry logic via
// applySharedInterceptors() — a single source of truth.
// ─────────────────────────────────────────────

const API_BASE_URL = import.meta.env.VITE_API_URL ?? "/api";

// ── Shared interceptor state ──────────────────────────────────────────────────

interface RetryConfig {
  retryCount?: number;
  skipRetry?: boolean; // prevents infinite refresh loops
}

type RetryableRequestConfig = InternalAxiosRequestConfig & { _retryConfig?: RetryConfig };

// Shape of the JSON body returned by the API's exception handlers
// (see ducta.api.middleware.register_middleware / DuctaAPIError.to_dict()).
interface ApiErrorBody {
  error?: string;
  message?: string;
  detail?: unknown;
  request_id?: string;
}

let isRefreshing = false;
let failedQueue: { resolve: (token: string | null) => void; reject: (err: unknown) => void }[] = [];

const processQueue = (error: unknown, token: string | null = null) => {
  failedQueue.forEach((prom) => {
    if (error) prom.reject(error);
    else prom.resolve(token);
  });
  failedQueue = [];
};

// ── Shared interceptor functions ─────────────────────────────────────────────

function requestInterceptor(config: InternalAxiosRequestConfig): InternalAxiosRequestConfig {
  const token = getToken();
  if (token) {
    config.headers.set("Authorization", `Bearer ${token}`);
  }
  try {
    const source = normalizeSourceInput(StorageService.getSource());
    if (source) {
      if (!config.params) config.params = {};
      if (!config.params.source) config.params.source = source;
    }
  } catch (error) {
    if (error instanceof Error) {
      console.warn("[API Client] Failed to read source from storage:", error.message);
    }
  }
  return config;
}

/** Clear the session and tell the app to send the user to /login. */
function abandonSession(): void {
  useAuthStore.getState().logout();
  if (globalThis.location?.pathname !== "/login") {
    globalThis.dispatchEvent(new Event("ducta:unauthorized"));
  }
}

/**
 * Recover a 401 by refreshing the token, or give up cleanly.
 *
 * Always either returns a response or throws. It used to be able to fall off
 * the end and resolve with `undefined` — which happens routinely, because
 * `getToken()` discards a token within 30s of expiry, so a refresh can succeed
 * and still leave nothing usable. The interceptor then *resolved* with
 * `undefined` instead of rejecting, and the caller's `response.data` threw a
 * TypeError somewhere unrelated. Because that path always returned, the
 * interceptor's own "401 with no valid refresh → logout" branch was unreachable.
 */
async function handle401Error(
  error: AxiosError,
  config: RetryableRequestConfig | undefined,
  retryConfig: RetryConfig,
  instance: AxiosInstance,
): Promise<AxiosResponse> {
  if (isRefreshing) {
    const token = await new Promise<string | null>((resolve, reject) => {
      failedQueue.push({ resolve, reject });
    });
    if (!config || !token) {
      abandonSession();
      throw error;
    }
    config.headers.set("Authorization", `Bearer ${token}`);
    config._retryConfig = { ...retryConfig, skipRetry: true };
    return instance(config);
  }

  isRefreshing = true;
  try {
    const { refreshTokenAsync } = useAuthStore.getState();
    await refreshTokenAsync();
    const newToken = getToken();
    processQueue(null, newToken);

    if (!config || !newToken) {
      // Refresh "succeeded" but produced nothing we can retry with.
      abandonSession();
      throw error;
    }
    config.headers.set("Authorization", `Bearer ${newToken}`);
    config._retryConfig = { ...retryConfig, skipRetry: true };
    return instance(config);
  } catch (refreshError) {
    if (refreshError !== error) {
      processQueue(refreshError, null);
      abandonSession();
    }
    throw refreshError;
  } finally {
    isRefreshing = false;
  }
}

async function handleTransientError(
  error: AxiosError,
  config: RetryableRequestConfig | undefined,
  retryCount: number,
  instance: AxiosInstance,
): Promise<AxiosResponse | null> {
  const MAX_RETRIES = 3;
  if (
    retryCount < MAX_RETRIES &&
    (error.response?.status === 429 || error.code === "ECONNABORTED")
  ) {
    const delay = Math.pow(2, retryCount) * 1000;
    if (config) {
      config._retryConfig = { retryCount: retryCount + 1, skipRetry: false };
      return new Promise((resolve) => setTimeout(() => resolve(instance(config)), delay));
    }
  }
  return null;
}

// ── Apply shared interceptors to any Axios instance ─────────────────────────

function applySharedInterceptors(
  instance: AxiosInstance,
  opts: { skipTransientRetry?: boolean } = {},
) {
  instance.interceptors.request.use(requestInterceptor);

  instance.interceptors.response.use(
    (response) => response,
    async (error: AxiosError): Promise<AxiosResponse> => {
      const config = error.config as RetryableRequestConfig | undefined;
      const retryConfig: RetryConfig = config?._retryConfig ?? {};
      const retryCount = retryConfig.retryCount ?? 0;

      // Log enriched error info for debugging
      if (error.response?.data) {
        const apiError = error.response.data as ApiErrorBody;
        console.error(
          `[API Error] ${error.config?.method?.toUpperCase()} ${error.config?.url}:`,
          apiError.message || error.message,
          apiError.request_id ? `(Request ID: ${apiError.request_id})` : "",
          apiError.detail ? apiError.detail : ""
        );
      }

      // 401 → try token refresh
      if (error.response?.status === 401 && !retryConfig.skipRetry) {
        return handle401Error(error, config, retryConfig, instance);
      }

      // Transient errors (429, timeout) → exponential backoff
      if (!opts.skipTransientRetry) {
        const transientResult = await handleTransientError(error, config, retryCount, instance);
        if (transientResult !== null) return transientResult;
      }

      // A 401 that was not eligible for refresh (skipRetry — i.e. the retried
      // request came back 401 again, or /auth/refresh itself did). The refresh
      // path above handles its own failure; this is the terminal case.
      if (error.response?.status === 401) {
        abandonSession();
      }

      throw error;
    },
  );
}

// ── Client instances ─────────────────────────────────────────────────────────

const client = axios.create({
  baseURL: API_BASE_URL,
  headers: { "Content-Type": "application/json" },
  withCredentials: true,
  timeout: 30_000,
});
applySharedInterceptors(client);

/**
 * Client with extended timeout (5 minutes) for pipeline execution requests.
 * Skips transient retry since long-running requests should not be auto-retried.
 */
export const executionClient = axios.create({
  baseURL: API_BASE_URL,
  headers: { "Content-Type": "application/json" },
  withCredentials: true,
  timeout: 5 * 60 * 1000,
});
applySharedInterceptors(executionClient, { skipTransientRetry: true });

export default client;
