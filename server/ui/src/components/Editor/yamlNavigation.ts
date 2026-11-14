/** The token under a column of a YAML line: a dataset (`silver.orders`) or a `module:function`. */
export function tokenAt(line: string, column: number): { text: string; start: number; end: number } | null {
  const re = /[A-Za-z_][\w.-]*(?::[A-Za-z_]\w*)?/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(line))) {
    const start = m.index + 1;
    const end = start + m[0].length;
    if (column >= start && column <= end) return { text: m[0], start, end };
  }
  return null;
}

export interface Located {
  file: string;
  line: number | null;
}

export interface NavigationIndex {
  datasets: Record<string, Located>;
  nodes: Record<string, Located & { pipeline?: string }>;
  /** `module:function` → where the function is defined. */
  functions: Record<string, Located>;
}

export type Target =
  | { kind: "function"; name: string; at: Located }
  | { kind: "dataset"; name: string; at: Located }
  | { kind: "node"; name: string; at: Located & { pipeline?: string } };

/** What a token refers to in the project, if anything. */
export function resolveToken(token: string, index: NavigationIndex): Target | null {
  if (token.includes(":") && index.functions[token]) return { kind: "function", name: token, at: index.functions[token] };
  if (index.datasets[token]) return { kind: "dataset", name: token, at: index.datasets[token] };
  if (index.nodes[token]) return { kind: "node", name: token, at: index.nodes[token] };
  return null;
}
