/**
 * Short display label for a git source URL/path — the last non-empty path
 * segment, with a trailing `.git` and slashes stripped. Shared by
 * `Sidebar/SourceSwitcher` and `Workspace/ConnectWorkspaceForm`, which
 * previously each carried their own copy of this exact rule.
 */
export function sourceLabel(src: string): string {
  if (!src) return "—";
  const cleaned = src.replace(/\.git$/, "").replace(/\/+$/, "");
  const seg = cleaned.split(/[/\\]/).filter(Boolean).pop();
  return seg || cleaned;
}
