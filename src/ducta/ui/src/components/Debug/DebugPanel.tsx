import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { IconBug, IconPlayerPlay, IconPlayerStop, IconArrowForwardUp, IconArrowDownRight, IconArrowUpLeft, IconX } from "@tabler/icons-react";
import { useDebugger, useExecutionStatus } from "../../api/queries";
import { routes } from "../../utils/routes";
import { useDebugStore, type Variable } from "./debugStore";

/**
 * The debug run, debugged here: it waits for this panel to attach, runs to the
 * breakpoints set in the editor's margin, and — stopped — shows its stack and
 * variables, takes an expression, and continues or steps.
 */
export function DebugPanel({ projectId, executionId, onClose }: { projectId: string; executionId: string; onClose: () => void }) {
  const { data: info } = useDebugger(projectId);
  const { data: run } = useExecutionStatus(executionId);
  const s = useDebugStore();
  const root = info?.root;
  const [showIde, setShowIde] = useState(false);

  useEffect(() => {
    if (root && useDebugStore.getState().executionId !== executionId) useDebugStore.getState().start(projectId, executionId, root);
  }, [root, projectId, executionId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const st = useDebugStore.getState();
      if (st.status !== "stopped") return;
      if (e.key === "F5") st.resume();
      else if (e.key === "F10") st.step("next");
      else if (e.key === "F11" && e.shiftKey) st.step("stepOut");
      else if (e.key === "F11") st.step("stepIn");
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const label = {
    idle: "Starting…",
    connecting: "Waiting for the run to start…",
    running: "Running — it stops at your breakpoints",
    stopped: "Stopped",
    ended: "The debug run ended",
    error: s.error ?? "The debugger could not attach",
  }[s.status];
  const active = s.frames.find((f) => f.id === s.activeFrame);
  const anyBreakpoint = Object.values(s.breakpoints[projectId] ?? {}).some((l) => l.length > 0);

  return (
    <section className="debug-panel debug-panel--live" aria-label="Debugger" aria-live="polite">
      <header className="debug-panel__head">
        <IconBug size={16} aria-hidden="true" />
        <strong>{label}</strong>
        {run?.status && s.status !== "stopped" && <span className="debug-panel__meta">run {run.status}</span>}
        <button type="button" className="debug-panel__close" onClick={onClose} aria-label="Close">
          <IconX size={14} />
        </button>
      </header>

      {s.status === "running" && !anyBreakpoint && (
        <p className="debug-panel__text">No breakpoints yet — click in the margin beside a line of the node's code to add one.</p>
      )}

      <div className="debug-panel__controls" role="toolbar" aria-label="Debug controls">
        <button type="button" onClick={s.resume} disabled={s.status !== "stopped"} title="Continue (F5)"><IconPlayerPlay size={14} /> Continue</button>
        <button type="button" onClick={() => s.step("next")} disabled={s.status !== "stopped"} title="Step over (F10)"><IconArrowForwardUp size={14} /></button>
        <button type="button" onClick={() => s.step("stepIn")} disabled={s.status !== "stopped"} title="Step in (F11)"><IconArrowDownRight size={14} /></button>
        <button type="button" onClick={() => s.step("stepOut")} disabled={s.status !== "stopped"} title="Step out (⇧F11)"><IconArrowUpLeft size={14} /></button>
        <button type="button" onClick={s.stop} disabled={s.status === "ended" || s.status === "error"} title="Stop the debug run" className="is-danger"><IconPlayerStop size={14} /></button>
      </div>

      {s.status === "stopped" && (
        <>
          <h4 className="debug-panel__h">Call stack</h4>
          <ol className="debug-panel__frames">
            {s.frames.map((f) => (
              <li key={f.id} className={f.id === s.activeFrame ? "is-active" : f.inProject ? undefined : "is-library"}>
                <button type="button" onClick={() => s.selectFrame(f.id)}>
                  <span className="mono">{f.name}</span>
                </button>
                {f.file && f.inProject ? (
                  <Link className="mono debug-panel__where" to={routes.code(projectId, f.file, f.line)}>{f.file}:{f.line}</Link>
                ) : (
                  <span className="mono debug-panel__where">{f.file?.split("/").pop()}:{f.line}</span>
                )}
              </li>
            ))}
          </ol>
          {active && (
            <>
              <h4 className="debug-panel__h">Variables in {active.name}</h4>
              <VariableTree key={active.id} reference={-1} />
              <Evaluate key={`e${active.id}`} />
            </>
          )}
        </>
      )}

      <button type="button" className="debug-panel__ide" onClick={() => setShowIde((v) => !v)} aria-expanded={showIde}>
        {showIde ? "Hide" : "Use your IDE instead"}
      </button>
      {showIde && (
        <pre className="debug-panel__code-ide">{JSON.stringify({ ...(info?.vscode ?? {}), connect: { host: "127.0.0.1", port: run?.debug_port ?? "…" } }, null, 2)}</pre>
      )}
    </section>
  );
}

function VariableTree({ reference, depth = 0 }: { reference: number; depth?: number }) {
  const load = useDebugStore((s) => s.variables);
  const [vars, setVars] = useState<Variable[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    load(reference).then((v) => live && setVars(v)).catch((e) => live && setError(String(e.message ?? e)));
    return () => {
      live = false;
    };
  }, [load, reference]);
  if (error) return <p className="debug-panel__text">{error}</p>;
  if (!vars) return <p className="debug-panel__text">…</p>;
  return (
    <ul className="debug-panel__vars" style={{ paddingLeft: depth ? 12 : 0 }}>
      {vars.filter((v) => !v.name.startsWith("__")).map((v) => (
        <VariableRow key={v.name} v={v} depth={depth} />
      ))}
    </ul>
  );
}

function VariableRow({ v, depth }: { v: Variable; depth: number }) {
  const [open, setOpen] = useState(false);
  const expandable = v.variablesReference > 0 && depth < 6;
  return (
    <li>
      <button type="button" className="debug-panel__var" onClick={() => expandable && setOpen((o) => !o)} aria-expanded={expandable ? open : undefined}>
        <span className="debug-panel__caret">{expandable ? (open ? "▾" : "▸") : " "}</span>
        <span className="mono debug-panel__name">{v.name}</span>
        <span className="mono debug-panel__value" title={v.value}>{v.value}</span>
      </button>
      {open && <VariableTree reference={v.variablesReference} depth={depth + 1} />}
    </li>
  );
}

function Evaluate() {
  const evaluate = useDebugStore((s) => s.evaluate);
  const [expr, setExpr] = useState("");
  const [history, setHistory] = useState<{ expr: string; out: string; error?: boolean }[]>([]);
  const run = () => {
    if (!expr.trim()) return;
    const e = expr;
    setExpr("");
    evaluate(e)
      .then((out) => setHistory((h) => [...h, { expr: e, out }]))
      .catch((err) => setHistory((h) => [...h, { expr: e, out: String(err.message ?? err), error: true }]));
  };
  return (
    <div className="debug-panel__eval">
      {history.map((h, i) => (
        <div key={i} className={h.error ? "is-error" : undefined}>
          <span className="mono">› {h.expr}</span>
          <span className="mono">{h.out}</span>
        </div>
      ))}
      <input
        className="mono-input"
        value={expr}
        onChange={(e) => setExpr(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && run()}
        placeholder="Evaluate in this frame, e.g. df.count()"
        aria-label="Evaluate an expression in the stopped frame"
      />
    </div>
  );
}
