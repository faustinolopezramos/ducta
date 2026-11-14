export type LineOp = { kind: "equal" | "insert" | "delete"; a: number; b: number };

/**
 * Myers' O(ND) diff over lines: the shortest edit script from `a` to `b`, as
 * equal / insert / delete steps (`a`, `b` are 0-based line indexes).
 */
export function diffLines(a: string[], b: string[]): LineOp[] {
  const n = a.length;
  const m = b.length;
  const max = n + m;
  const v = new Int32Array(2 * max + 2);
  const trace: Int32Array[] = [];
  const off = max + 1;
  outer: for (let d = 0; d <= max; d++) {
    trace.push(v.slice());
    for (let k = -d; k <= d; k += 2) {
      let x = k === -d || (k !== d && v[off + k - 1] < v[off + k + 1]) ? v[off + k + 1] : v[off + k - 1] + 1;
      let y = x - k;
      while (x < n && y < m && a[x] === b[y]) {
        x++;
        y++;
      }
      v[off + k] = x;
      if (x >= n && y >= m) break outer;
    }
  }
  // Walk the trace back into an edit script.
  const ops: LineOp[] = [];
  let x = n;
  let y = m;
  for (let d = trace.length - 1; d >= 0; d--) {
    const vd = trace[d];
    const k = x - y;
    const prevK = k === -d || (k !== d && vd[off + k - 1] < vd[off + k + 1]) ? k + 1 : k - 1;
    const prevX = vd[off + prevK];
    const prevY = prevX - prevK;
    while (x > prevX && y > prevY) ops.push({ kind: "equal", a: --x, b: --y });
    if (d > 0) {
      if (x === prevX) ops.push({ kind: "insert", a: x, b: --y });
      else ops.push({ kind: "delete", a: --x, b: y });
    }
  }
  return ops.reverse();
}

export interface GutterMark {
  kind: "added" | "modified" | "deleted";
  /** 1-based lines of the current text: first and last (a deletion marks the line after it). */
  from: number;
  to: number;
}

/** What changed against `base`, as the gutter shows it: added, modified, deleted-here. */
export function gutterMarks(base: string, current: string): GutterMark[] {
  const ops = diffLines(base.split("\n"), current.split("\n"));
  const marks: GutterMark[] = [];
  let i = 0;
  while (i < ops.length) {
    if (ops[i].kind === "equal") {
      i++;
      continue;
    }
    let dels = 0;
    const ins: number[] = [];
    let at = ops[i].b;
    while (i < ops.length && ops[i].kind !== "equal") {
      if (ops[i].kind === "delete") dels++;
      else ins.push(ops[i].b);
      at = ops[i].b;
      i++;
    }
    if (ins.length === 0) marks.push({ kind: "deleted", from: at + 1, to: at + 1 });
    else marks.push({ kind: dels > 0 ? "modified" : "added", from: ins[0] + 1, to: ins[ins.length - 1] + 1 });
  }
  return marks;
}
