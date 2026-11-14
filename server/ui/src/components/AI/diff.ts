/** One file's part of a unified diff, line by line. */
export interface DiffLine {
  kind: "add" | "del" | "ctx" | "hunk" | "meta";
  text: string;
  oldLineNumber?: number | null;
  newLineNumber?: number | null;
}

export interface FileDiff {
  path: string;
  lines: DiffLine[];
  additions: number;
  deletions: number;
}

/**
 * Split the unified diff the API returns (every file of a draft, one after the
 * other) into one entry per file, keyed by the path after `+++ b/`.
 * Also tracks line numbers and addition/deletion counts per file.
 */
export function splitDiff(diff: string): FileDiff[] {
  const out: FileDiff[] = [];
  let current: FileDiff | null = null;
  let oldNum = 1;
  let newNum = 1;

  for (const text of diff.split("\n")) {
    if (text.startsWith("--- ")) continue;
    if (text.startsWith("+++ ")) {
      current = {
        path: text.replace(/^\+\+\+ (b\/)?/, ""),
        lines: [],
        additions: 0,
        deletions: 0,
      };
      out.push(current);
      oldNum = 1;
      newNum = 1;
      continue;
    }
    if (!current || text === "") continue;

    if (text.startsWith("@@")) {
      const match = text.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
      if (match) {
        oldNum = Number.parseInt(match[1], 10);
        newNum = Number.parseInt(match[2], 10);
      }
      current.lines.push({ kind: "hunk", text, oldLineNumber: null, newLineNumber: null });
      continue;
    }

    if (text.startsWith("+")) {
      current.additions++;
      current.lines.push({
        kind: "add",
        text,
        oldLineNumber: null,
        newLineNumber: newNum++,
      });
    } else if (text.startsWith("-")) {
      current.deletions++;
      current.lines.push({
        kind: "del",
        text,
        oldLineNumber: oldNum++,
        newLineNumber: null,
      });
    } else if (text.startsWith("\\")) {
      current.lines.push({
        kind: "meta",
        text,
        oldLineNumber: null,
        newLineNumber: null,
      });
    } else {
      current.lines.push({
        kind: "ctx",
        text,
        oldLineNumber: oldNum++,
        newLineNumber: newNum++,
      });
    }
  }
  return out;
}

/** The pipeline a draft creates or changes, from its files. */
export function pipelineOf(files: string[]): string | null {
  const file = files.find((f) => /^pipelines\/[^/]+\.ya?ml$/.test(f));
  return file ? file.replace(/^pipelines\//, "").replace(/\.ya?ml$/, "") : null;
}
