export const uid = (): string =>
  globalThis.crypto?.randomUUID?.() ??
  `id-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
export const now = (): string => new Date().toISOString().slice(0, 10);
