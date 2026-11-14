import { useState, type FormEvent } from "react";
import { useCreateServerProject } from "../../api/queries";
import { useGenerateFromTemplate, useTemplates } from "../../api/templatesApi";
import { apiErrorMessage } from "../../api/mutations";
import { Button } from "../ui/Button";
import { Modal } from "../ui/Modal";

/** The rule the API applies to a project name (it becomes a directory). */
const NAME_RE = /^[a-zA-Z][a-zA-Z0-9_-]*$/;

const FALLBACK_TEMPLATES = [{ type: "medallion_basic", name: "Medallion Basic", description: "" }];

/**
 * One way to create a project. It used to be two buttons with the same "+"
 * icon — "New from template" and "Create project" — and two modals, neither a
 * form, so Enter did nothing and a failed template generation said nothing.
 * Now the starting point is a choice inside the form, the name is checked
 * against the rule the API enforces before it is sent, and a server refusal is
 * shown where the user is looking.
 */
export function NewProjectModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (projectId: string) => void;
}) {
  const [source, setSource] = useState<"empty" | "template">("empty");
  const [name, setName] = useState("");
  const [template, setTemplate] = useState("medallion_basic");
  const [error, setError] = useState<string | null>(null);
  const { data: templates } = useTemplates();
  const create = useCreateServerProject();
  const generate = useGenerateFromTemplate();

  const trimmed = name.trim();
  const nameProblem =
    trimmed && !NAME_RE.test(trimmed) ? "Start with a letter, then use only letters, digits, _ or -." : null;
  const pending = create.isPending || generate.isPending;
  const options = templates?.length ? templates : FALLBACK_TEMPLATES;
  const chosen = options.find((t) => t.type === template);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!trimmed || nameProblem || pending) return;
    setError(null);
    const onError = (err: unknown) =>
      setError(apiErrorMessage(err, "Couldn’t create the project. Choose a unique name and try again."));
    if (source === "empty") {
      create.mutate({ name: trimmed }, { onSuccess: () => onCreated(trimmed), onError });
    } else {
      generate.mutate(
        { template, project_name: trimmed },
        { onSuccess: (result) => onCreated(result.project_id), onError }
      );
    }
  };

  return (
    <Modal title="New project" onClose={onClose}>
      <form className="projects-modal__form" onSubmit={submit} noValidate>
        <fieldset className="dash-source">
          <legend className="projects-modal__label">Start from</legend>
          <label className="dash-source-option">
            <input
              type="radio"
              name="project-source"
              value="empty"
              checked={source === "empty"}
              onChange={() => setSource("empty")}
            />
            Empty project
          </label>
          <label className="dash-source-option">
            <input
              type="radio"
              name="project-source"
              value="template"
              checked={source === "template"}
              onChange={() => setSource("template")}
            />
            From a template
          </label>
        </fieldset>

        {source === "template" && (
          <>
            <label className="projects-modal__label" htmlFor="project-template">
              Template
            </label>
            <select
              id="project-template"
              className="projects-modal__select"
              value={template}
              onChange={(e) => setTemplate(e.target.value)}
            >
              {options.map((t) => (
                <option key={t.type} value={t.type}>
                  {t.name}
                </option>
              ))}
            </select>
            {chosen?.description && <p className="projects-modal__hint">{chosen.description}</p>}
          </>
        )}

        <label className="projects-modal__label" htmlFor="new-project-name">
          Project name
        </label>
        <input
          id="new-project-name"
          className="projects-modal__input"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="my_project"
          autoComplete="off"
          aria-invalid={Boolean(nameProblem)}
          aria-describedby="new-project-name-hint"
        />
        <p
          id="new-project-name-hint"
          className={`projects-modal__hint${nameProblem ? " dash-hint-error" : ""}`}
        >
          {nameProblem ?? "Used as the folder name under projects/."}
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
          <Button type="submit" variant="primary" loading={pending} disabled={!trimmed || Boolean(nameProblem)}>
            Create project
          </Button>
        </div>
      </form>
    </Modal>
  );
}
