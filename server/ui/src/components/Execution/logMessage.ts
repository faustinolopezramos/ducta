/** JVM stack frames: "\tat org.apache.spark.sql…(File.scala:123)". */
const JVM_FRAME = /^\s+at [\w.$<>]+\(.*\)\s*$/;
const KEEP_FRAMES = 2;

/**
 * A message with long runs of JVM frames folded: the first two of each run
 * stay, the rest become one "… N more JVM frames" line. `hidden` says how
 * many were folded (0: nothing to fold).
 */
export function foldJvmFrames(message: string): { text: string; hidden: number } {
  const out: string[] = [];
  let run: string[] = [];
  let hidden = 0;
  const flush = () => {
    out.push(...run.slice(0, KEEP_FRAMES));
    if (run.length > KEEP_FRAMES) {
      const folded = run.length - KEEP_FRAMES;
      hidden += folded;
      out.push(`        … ${folded} more JVM frames`);
    }
    run = [];
  };
  for (const line of message.split("\n")) {
    if (JVM_FRAME.test(line)) run.push(line);
    else {
      flush();
      out.push(line);
    }
  }
  flush();
  return hidden ? { text: out.join("\n"), hidden } : { text: message, hidden: 0 };
}

/** Python external stack frames: File ".../site-packages/...". */
const PYTHON_INTERNAL_FRAME = /^\s*File ".*(?:site-packages|dist-packages|\/lib\/python\d*\.?\d*)\/.*", line \d+/;

/**
 * Fold long runs of external/library frames (JVM or Python site-packages), keeping project code prominent.
 */
export function foldTracebackFrames(message: string): { text: string; hidden: number } {
  const jvmFolded = foldJvmFrames(message);
  const lines = jvmFolded.text.split("\n");
  const out: string[] = [];
  let internalRun = 0;
  let totalHidden = jvmFolded.hidden;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (PYTHON_INTERNAL_FRAME.test(line)) {
      internalRun++;
      // Also consume the code line following the File line if indented
      if (i + 1 < lines.length && /^\s{4,}\S/.test(lines[i + 1])) {
        i++;
      }
    } else {
      if (internalRun > 2) {
        out.push(`        … ${internalRun} internal library frames hidden`);
        totalHidden += internalRun;
      } else if (internalRun > 0) {
        out.push(`        … ${internalRun} internal frame(s)`);
      }
      internalRun = 0;
      out.push(line);
    }
  }
  if (internalRun > 2) {
    out.push(`        … ${internalRun} internal library frames hidden`);
    totalHidden += internalRun;
  } else if (internalRun > 0) {
    out.push(`        … ${internalRun} internal frame(s)`);
  }
  return { text: out.join("\n"), hidden: totalHidden };
}

/** Folders a project's own files live under — where a path in a trace becomes project-relative. */
const PROJECT_DIRS = ["src/", "pipelines/", "catalog/", "tests/", "lib/", "jobs/", "notebooks/"];

export interface FileRef {
  start: number;
  end: number;
  /** Project-relative. */
  file: string;
  line: number;
}

/**
 * Places in a message that point at a project file and line — Python's
 * `File "…/src/silver.py", line 42` and `src/silver.py:42`. Paths outside the
 * project's own folders (site-packages, the JVM) are not links.
 */
export function fileRefs(text: string): FileRef[] {
  const out: FileRef[] = [];
  const patterns = [/File "([^"]+\.py)", line (\d+)/g, /((?:[\w.-]+\/)*[\w.-]+\.(?:py|ya?ml)):(\d+)/g];
  for (const re of patterns) {
    for (const m of text.matchAll(re)) {
      const raw = m[1];
      if (/site-packages|dist-packages|\/lib\/python/.test(raw)) continue;
      const at = PROJECT_DIRS.map((d) => raw.lastIndexOf(d.replace(/\/$/, "") + "/")).filter((i) => i >= 0 && (i === 0 || raw[i - 1] === "/"));
      if (at.length === 0) continue;
      const file = raw.slice(Math.max(...at));
      const start = m.index!;
      if (out.some((r) => start < r.end && r.start < start + m[0].length)) continue;
      out.push({ start, end: start + m[0].length, file, line: Number(m[2]) });
    }
  }
  return out.sort((a, b) => a.start - b.start);
}
