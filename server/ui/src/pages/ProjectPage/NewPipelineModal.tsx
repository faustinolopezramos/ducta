import { useState, type FormEvent } from "react";
import { apiErrorMessage, useCreatePipeline } from "../../api/mutations";
import { Button } from "../../components/ui/Button";
import { Modal } from "../../components/ui/Modal";

/** Pipeline names become YAML keys and URL segments; dots are the layer convention. */
const PIPELINE_NAME_RE = /^[a-zA-Z][a-zA-Z0-9_.-]*$/;

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
      { projectId, name: trimmed, spec: { nodes: [], type: "batch", active: true } },
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
          {problem ?? "Starts as an empty batch pipeline; add nodes on the canvas."}
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
