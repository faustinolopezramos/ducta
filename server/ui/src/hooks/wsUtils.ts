export const MAX_RECONNECT_ATTEMPTS = 5;

export function apiWebSocketUrl(path: string): string {
  const configuredBase = import.meta.env.VITE_API_URL?.trim();
  const browserBase = `${globalThis.location?.protocol === "https:" ? "wss" : "ws"}://${globalThis.location?.host ?? "localhost:5173"}`;
  const apiBase = configuredBase && /^https?:\/\//i.test(configuredBase)
    ? configuredBase
    : `${browserBase}${configuredBase || "/api"}`;
  const url = new URL(apiBase);

  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.search = "";
  url.hash = "";
  url.pathname = `${url.pathname.replace(/\/+$/, "")}/${path.replace(/^\/+/, "")}`;
  return url.toString();
}

export function buildWsUrl(executionId: string): string {
  return apiWebSocketUrl(`ws/logs/${encodeURIComponent(executionId)}`);
}
