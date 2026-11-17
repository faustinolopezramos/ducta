import { useState, type FormEvent } from "react";
import { apiErrorMessage, useCreatePipeline } from "../../api/mutations";
import { Button } from "../../components/ui/Button";
import { Modal } from "../../components/ui/Modal";
import { SegmentedControl } from "../../components/ui/SegmentedControl";

/** Pipeline names become YAML keys and URL segments; dots are the layer convention. */
const PIPELINE_NAME_RE = /^[a-zA-Z][a-zA-Z0-9_.-]*$/;

type PipelineKind = "batch" | "streaming" | "ml";

/** What each kind is, said where it is chosen: a stream is nothing like a batch to start from. */
const KINDS: { value: PipelineKind; label: string; hint: string; spec: Record<string, unknown> }[] = [
  {
    value: "batch",
    label: "Batch",
    hint: "Runs over a date range and finishes. Add nodes on the canvas.",
    spec: { type: "batch" },
  },
  {
    value: "streaming",
    label: "Streaming",
    hint: "Runs until you stop it, with no date range. Each node declares its own source and sink.",
    spec: { type: "streaming", requires_dates: false },
  },
  {
    value: "ml",
    label: "ML",
    hint: "Nodes that train and score models, tracked as experiments. Set the split in the YAML lens.",
    spec: { type: "ml" },
  },
];

/**
 * Creating a pipeline, as a form: Enter submits, the name is checked before it
 * is sent (including against the pipelines that already exist), and a refusal
 * is shown in the dialog. It used to be an inline card that only appeared in
 * the list view, so asking for a pipeline from the map first switched views.
 */
export function NewPipelineModal({
  projectId,
  existing,
  onClose,
  onCreated,
}: {
  projectId: string;
  existing: string[];
  onClose: () => void;
  onCreated: (name: string) => void;
}) {
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [kind, setKind] = useState<PipelineKind>("batch");
  const { mutate: createPipeline, isPending } = useCreatePipeline();

  const trimmed = name.trim();
  const problem = !trimmed
    ? null
    : !PIPELINE_NAME_RE.test(trimmed)
      ? "Start with a letter, then use only letters, digits, _, - or ."
      : existing.includes(trimmed)
        ? `A pipeline named “${trimmed}” already exists in this project.`
        : null;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!trimmed || problem || isPending) return;
    setError(null);
    createPipeline(
      { projectId, name: trimmed, spec: { nodes: [], ...KINDS.find((k) => k.value === kind)!.spec, active: true } },
      {
        onSuccess: () => onCreated(trimmed),
        onError: (err: unknown) => setError(apiErrorMessage(err, "Couldn’t create the pipeline. Try again.")),
      }
    );
  };

  return (
    <Modal title="New pipeline" onClose={onClose}>
      <form className="projects-modal__form" onSubmit={submit} noValidate>
        <label className="projects-modal__label" htmlFor="new-pipeline-name">
          Pipeline name
        </label>
        <input
          id="new-pipeline-name"
          className="projects-modal__input"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="silver.clean"
          autoComplete="off"
          aria-invalid={Boolean(problem)}
          aria-describedby="new-pipeline-name-hint"
        />
        <p id="new-pipeline-name-hint" className={`projects-modal__hint${problem ? " dash-hint-error" : ""}`}>
          {problem ?? "Dots mark layers, like silver.clean."}
        </p>
        <span className="projects-modal__label" id="new-pipeline-kind">
          Type
        </span>
        <SegmentedControl<PipelineKind>
          aria-label="Pipeline type"
          className="projects-modal__kind"
          options={KINDS.map(({ value, label }) => ({ value, label }))}
          value={kind}
          onChange={setKind}
        />
        <p className="projects-modal__hint projects-modal__hint--below" aria-live="polite">
          {KINDS.find((k) => k.value === kind)!.hint}
        </p>
        {error && (
          <p className="dash-form-error" role="alert">
            {error}
          </p>
        )}
        <div className="projects-modal__actions">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" loading={isPending} disabled={!trimmed || Boolean(problem)}>
            Create pipeline
          </Button>
        </div>
      </form>
    </Modal>
  );
}
