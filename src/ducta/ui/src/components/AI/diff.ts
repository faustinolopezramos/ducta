/** One file's part of a unified diff, line by line. */
export interface FileDiff {
  path: string;
  lines: { kind: "add" | "del" | "ctx" | "hunk" | "meta"; text: string }[];
}

/**
 * Split the unified diff the API returns (every file of a draft, one after the
 * other) into one entry per file, keyed by the path after `+++ b/`.
 */
export function splitDiff(diff: string): FileDiff[] {
  const out: FileDiff[] = [];
  let current: FileDiff | null = null;
  for (const text of diff.split("\n")) {
    if (text.startsWith("--- ")) continue;
    if (text.startsWith("+++ ")) {
      current = { path: text.replace(/^\+\+\+ (b\/)?/, ""), lines: [] };
      out.push(current);
      continue;
    }
    if (!current || text === "") continue;
    const kind = text.startsWith("@@")
      ? "hunk"
      : text.startsWith("+")
        ? "add"
        : text.startsWith("-")
          ? "del"
          : text.startsWith("\\")
            ? "meta"
            : "ctx";
    current.lines.push({ kind, text });
  }
  return out;
}

/** The pipeline a draft creates or changes, from its files. */
export function pipelineOf(files: string[]): string | null {
  const file = files.find((f) => /^pipelines\/[^/]+\.ya?ml$/.test(f));
  return file ? file.replace(/^pipelines\//, "").replace(/\.ya?ml$/, "") : null;
}
