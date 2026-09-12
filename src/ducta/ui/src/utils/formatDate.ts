/**
 * Shared date formatter, previously duplicated near-verbatim in
 * `pages/MLOpsPage/shared.tsx` and `pages/QualityPage/shared.tsx`. The two
 * differed only in whether `year` is shown — MLOps run history can span
 * years, quality-check history is assumed recent — so that difference is
 * kept as an explicit option rather than collapsed to one behavior.
 */
export function formatDate(iso?: string | null, options?: { includeYear?: boolean }): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString([], {
    month: "short",
    day: "numeric",
    ...(options?.includeYear ? { year: "numeric" as const } : {}),
    hour: "2-digit",
    minute: "2-digit",
  });
}
