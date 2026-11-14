import { useMemo, useState, type FormEvent } from "react";
import { IconAlertTriangle, IconCircleCheck, IconCircleX } from "@tabler/icons-react";
import type { AIAttempt, AIDraft, Blueprint } from "../../api/aiApi";
import { Button } from "../ui/Button";
import { ConfirmDialog } from "../ui/ConfirmDialog";

/**
 * Ducta Architect inside "Build with AI" (several pipelines): the model asks
 * what it cannot assume, designs a blueprint Ducta checks without a model,
 * and — once approved — writes only the code, module by module.
 */

/** "Step 2 of 3 · Blueprint": where the person is in the design. */
export function ArchitectStepLine({ step, detail }: { step: 1 | 2 | 3; detail: string }) {
  return (
    <p className="ai-stepline">
      Step {step} of 3 · {detail}
    </p>
  );
}

// ── 1. Questions ─────────────────────────────────────────────────────────────

/** The questions the model asked, as the note sent with the next design. */
export function answersNote(questions: string[], answers: Record<number, string>): string {
  return [
    "Answers to your questions:",
    ...questions.map((q, i) => {
      const a = (answers[i] ?? "").trim();
      return `- ${q}\n  ${a || "(not answered: assume it, and list it under assumptions)"}`;
    }),
  ].join("\n");
}

export function QuestionsStep({
  questions,
  pending,
  error,
  onBack,
  onSubmit,
}: {
  questions: string[];
  pending: boolean;
  error: string | null;
  onBack: () => void;
  onSubmit: (note: string) => void;
}) {
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!pending) onSubmit(answersNote(questions, answers));
  };
  return (
    <form className="ai-step" onSubmit={submit} noValidate>
      <ArchitectStepLine step={1} detail="Design" />
      <p className="ai-context">
        Before designing, the model asks what it cannot assume. Answer what you can; anything left blank is assumed
        and listed in the blueprint.
      </p>
      {questions.map((q, i) => (
        <label key={i} className="ai-question">
          <span>{q}</span>
          <input
            type="text"
            className="projects-modal__input"
            value={answers[i] ?? ""}
            onChange={(e) => setAnswers((prev) => ({ ...prev, [i]: e.target.value }))}
            // eslint-disable-next-line jsx-a11y/no-autofocus -- the first answer is what the dialog asks for
            autoFocus={i === 0}
          />
        </label>
      ))}
      {error && (
        <p className="dash-form-error" role="alert">
          {error}
        </p>
      )}
      <div className="ai-actions ai-actions--split">
        <Button type="button" variant="ghost" className="ai-actions__start" onClick={onBack}>
          Back
        </Button>
        <Button type="submit" variant="primary" loading={pending}>
          Design with these answers
        </Button>
      </div>
    </form>
  );
}

// ── 2. Blueprint ─────────────────────────────────────────────────────────────

const LAYERS = ["bronze", "silver", "gold"] as const;
const LAYER_LABEL: Record<string, string> = { bronze: "Bronze", silver: "Silver", gold: "Gold", other: "Other" };

export interface MapCard {
  dataset: string;
  isNew: boolean;
  description?: string;
  /** "merge on order_id · delta" */
  write?: string;
  /** "not null: a, b · unique: a" */
  contract?: string;
  pipeline?: string;
  node?: string;
}

/** A dataset name that wraps at its dots, never inside a word. */
function Dotted({ name }: { name: string }) {
  const parts = name.split(".");
  return (
    <code>
      {parts.map((p, i) => (
        <span key={i}>
          {p}
          {i < parts.length - 1 && (
            <>
              .<wbr />
            </>
          )}
        </span>
      ))}
    </code>
  );
}

const layerOf = (dataset: string) => {
  const head = dataset.split(".")[0];
  return (LAYERS as readonly string[]).includes(head) ? head : "other";
};

/** The blueprint as columns of datasets per layer: what it reads (reused) and what it adds. */
export function blueprintMap(bp: Blueprint): { layer: string; cards: MapCard[] }[] {
  const writer: Record<string, { pipeline: string; node: string }> = {};
  const reused = new Set<string>();
  for (const [pipeline, spec] of Object.entries(bp.pipelines)) {
    for (const [node, n] of Object.entries(spec.nodes ?? {})) {
      for (const out of n.outputs ?? []) writer[out] = { pipeline, node };
      for (const input of Object.values(n.inputs ?? {})) if (!bp.datasets[input]) reused.add(input);
    }
  }
  const cards: MapCard[] = [
    ...[...reused].sort().map((dataset) => ({ dataset, isNew: false })),
    ...Object.entries(bp.datasets).map(([dataset, d]) => {
      const write = d.write ?? "overwrite";
      const keys = d.keys?.length ? ` on ${d.keys.join(", ")}` : "";
      const contract = [
        d.not_null?.length ? `not null: ${d.not_null.join(", ")}` : "",
        d.unique?.length ? `unique: ${d.unique.join(", ")}` : "",
        d.pii?.length ? `personal data: ${d.pii.join(", ")}` : "",
      ]
        .filter(Boolean)
        .join(" · ");
      return {
        dataset,
        isNew: true,
        description: d.description,
        write: `${write}${write === "merge" ? keys : ""} · ${d.format ?? "the layer's format"}`,
        contract: contract || undefined,
        ...writer[dataset],
      };
    }),
  ];
  const order = [...LAYERS, "other"];
  return order
    .map((layer) => ({ layer, cards: cards.filter((c) => layerOf(c.dataset) === layer) }))
    .filter((col) => col.cards.length > 0 || (LAYERS as readonly string[]).includes(col.layer));
}

/** "2 pipelines, 3 datasets and 2 modules". */
export function blueprintSize(bp: Blueprint): string {
  const pipelines = Object.values(bp.pipelines);
  const modules = pipelines.filter((p) => Object.values(p.nodes ?? {}).some((n) => (n.kind ?? "transform") === "transform"));
  const n = (count: number, what: string) => `${count} ${what}${count === 1 ? "" : "s"}`;
  return `${n(pipelines.length, "pipeline")}, ${n(Object.keys(bp.datasets).length, "dataset")} and ${n(modules.length, "module")}`;
}

export function BlueprintStep({
  draft,
  revising,
  building,
  error,
  onRevise,
  onBuild,
  onDiscard,
  discarding,
}: {
  draft: AIDraft;
  revising: boolean;
  building: boolean;
  error: string | null;
  onRevise: (note: string) => void;
  onBuild: () => void;
  onDiscard: () => void;
  discarding: boolean;
}) {
  const [view, setView] = useState<"map" | "yaml">("map");
  const [note, setNote] = useState("");
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const bp = draft.blueprint ?? null;
  const columns = useMemo(() => (bp ? blueprintMap(bp) : []), [bp]);
  const warnings = draft.warnings ?? [];
  const busy = revising || building;

  return (
    <div className="ai-step">
      <ArchitectStepLine step={2} detail="Blueprint" />
      {bp?.goal && <p className="ai-context">{bp.goal}</p>}

      <div className="ai-bp">
        <div className="ai-bp__main">
          <div className="ai-bp__toggle" role="group" aria-label="Show the blueprint as">
            <button type="button" aria-pressed={view === "map"} onClick={() => setView("map")}>
              Map
            </button>
            <button type="button" aria-pressed={view === "yaml"} onClick={() => setView("yaml")}>
              YAML
            </button>
          </div>
          {!bp ? (
            <p className="ai-dim">The model's answer is not a blueprint Ducta can read. Ask for changes, or start again.</p>
          ) : view === "yaml" ? (
            <pre className="ai-bp__yaml">{draft.blueprint_yaml}</pre>
          ) : (
            <div className="ai-bp__map">
              {columns.map((col) => (
                <section key={col.layer} className="ai-bp__layer" aria-label={LAYER_LABEL[col.layer]}>
                  <h3>{LAYER_LABEL[col.layer]}</h3>
                  {col.cards.length === 0 && <p className="ai-dim ai-fine">Nothing in this layer</p>}
                  {col.cards.map((c) =>
                    c.isNew ? (
                      <article key={c.dataset} className="ai-bp__card ai-bp__card--new">
                        <header>
                          <Dotted name={c.dataset} />
                          <span className="ai-bp__new">New</span>
                        </header>
                        {c.description && <p className="ai-dim">{c.description}</p>}
                        {c.write && <p>{c.write}</p>}
                        {c.contract && <p className="ai-dim">{c.contract}</p>}
                        {c.pipeline && (
                          <p className="ai-bp__writer ai-dim">
                            pipeline <b>{c.pipeline}</b> · node {c.node}
                          </p>
                        )}
                      </article>
                    ) : (
                      <article key={c.dataset} className="ai-bp__card">
                        <Dotted name={c.dataset} />
                        <p className="ai-dim">in the catalog · reused</p>
                      </article>
                    ),
                  )}
                </section>
              ))}
            </div>
          )}
        </div>

        <aside className="ai-bp__side">
          <div>
            <h3>Checked by Ducta</h3>
            {draft.ok ? (
              <>
                <p className="ai-bp__verdict">
                  <IconCircleCheck size={15} className="ai-ok" aria-hidden="true" /> Valid in every environment — no
                  model involved
                </p>
                <ul className="ai-bp__rules">
                  <li>Every input exists; one writer per dataset</li>
                  <li>Data flows bronze → silver → gold</li>
                  <li>Names are free; a merge has keys and is Delta</li>
                </ul>
              </>
            ) : (
              <ul className="ai-problems" aria-label="What Ducta found">
                {draft.blocking.map((p, i) => (
                  <li key={i}>
                    <IconCircleX size={13} className="ai-bad" aria-hidden="true" />
                    <span>{p.message}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
          {warnings.length > 0 && (
            <div className="ai-bp__warn" role="note">
              <p>
                <IconAlertTriangle size={14} aria-hidden="true" /> {warnings.length} warning
                {warnings.length === 1 ? "" : "s"}
              </p>
              <ul>
                {warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </div>
          )}
          {bp && bp.assumptions.length > 0 && (
            <div>
              <h3>Assumptions</h3>
              <ul className="ai-bp__rules">
                {bp.assumptions.map((a, i) => (
                  <li key={i}>{a}</li>
                ))}
              </ul>
            </div>
          )}
          {bp && (
            <p className="ai-dim ai-fine">It would add {blueprintSize(bp)}. The code is written in the next step.</p>
          )}
        </aside>
      </div>

      {error && (
        <p className="dash-form-error" role="alert">
          {error}
        </p>
      )}
      <form
        className="ai-actions ai-bp__footer"
        onSubmit={(e) => {
          e.preventDefault();
          if (note.trim() && !busy) onRevise(note.trim());
        }}
      >
        <Button type="button" variant="ghost" className="ai-discard" onClick={() => setConfirmDiscard(true)}>
          Discard
        </Button>
        <label className="ai-bp__ask">
          <span className="sr-only">Ask for changes</span>
          <input
            type="text"
            className="projects-modal__input"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Ask for changes, e.g. “owner: data-team for both”"
          />
        </label>
        <Button type="submit" variant="secondary" loading={revising} disabled={!note.trim() || busy}>
          Ask for changes
        </Button>
        <Button
          type="button"
          variant="primary"
          loading={building}
          disabled={!draft.ok || busy}
          title={draft.ok ? undefined : "Ducta found problems in the blueprint: ask for changes first"}
          onClick={onBuild}
        >
          Build
        </Button>
      </form>
      <ConfirmDialog
        open={confirmDiscard}
        title="Discard this blueprint?"
        description="It is deleted from the project's drafts. Nothing in the project changes."
        confirmLabel="Discard blueprint"
        tone="danger"
        pending={discarding}
        onConfirm={() => {
          onDiscard();
          setConfirmDiscard(false);
        }}
        onCancel={() => setConfirmDiscard(false)}
      />
    </div>
  );
}

// ── 3. Build ─────────────────────────────────────────────────────────────────

export interface ModuleProgress {
  path: string;
  attempts: AIAttempt[];
  accepted: boolean;
}

/** A build's attempts, per module (each attempt names the module it wrote), in order. */
export function modulesOf(attempts: AIAttempt[]): ModuleProgress[] {
  const out: ModuleProgress[] = [];
  for (const a of attempts) {
    const path = a.files[0] ?? "module";
    let m = out.find((x) => x.path === path);
    if (!m) {
      m = { path, attempts: [], accepted: false };
      out.push(m);
    }
    m.attempts.push(a);
    m.accepted = a.errors + a.rejected.length === 0;
  }
  return out;
}

/** "pipelines/m.py:3: `collect()` brings every row… — Keep the work…" → "`collect()` brings every row…". */
export function problemTitle(message: string): string {
  return message.replace(/^[\w./-]+\.py(:\d+)?:\s*/, "").split(" — ")[0];
}

function moduleDetail(m: ModuleProgress): string {
  const last = m.attempts[m.attempts.length - 1];
  const why = (a?: AIAttempt) => {
    const found = a?.messages?.[0] ?? a?.rejected[0];
    return found ? problemTitle(found) : "";
  };
  if (!m.accepted) return why(last) || "not accepted";
  if (m.attempts.length === 1) return "accepted on attempt 1";
  const first = why(m.attempts[0]);
  return `accepted on attempt ${m.attempts.length}${first ? ` — attempt 1: ${first}` : ""}`;
}

/** "Modules, in dependency order": what the model wrote and how each was accepted. */
export function ModulesList({ attempts, running }: { attempts: AIAttempt[]; running?: boolean }) {
  const modules = modulesOf(attempts);
  return (
    <div className="ai-modules">
      <h3>Modules, in dependency order</h3>
      <ol>
        {modules.map((m) => (
          <li key={m.path}>
            {m.accepted ? (
              <IconCircleCheck size={15} className="ai-ok" aria-hidden="true" />
            ) : (
              <IconCircleX size={15} className="ai-bad" aria-hidden="true" />
            )}
            <span>
              <code>{m.path}</code>
              <span className="ai-dim ai-fine">{moduleDetail(m)}</span>
            </span>
          </li>
        ))}
        {running && <li className="ai-dim">Writing the next module…</li>}
      </ol>
      <p className="ai-dim ai-fine">
        Ducta wrote the YAML. Each module was accepted only with the blueprint's exact signatures and no I/O of its
        own.
      </p>
    </div>
  );
}
