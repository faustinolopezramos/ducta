import type { GitChange } from "../../api/queries/git";

/** What a change touches, in the project's terms: a pipeline, a dataset file, source. */
function describe(path: string): string {
  const name = path.split("/").pop() ?? path;
  if (/(^|\/)pipelines\/.+\.ya?ml$/.test(path)) return `pipeline ${name.replace(/\.ya?ml$/, "")}`;
  if (/(^|\/)catalog(\/|\.ya?ml$)/.test(path)) return `catalog ${name.replace(/\.ya?ml$/, "")}`;
  if (/(^|\/)ducta\.ya?ml$/.test(path)) return "project settings";
  return path;
}

/**
 * A first line for the commit, from the files chosen: "Update pipeline
 * silver.clean and src/silver.py". Editable; it only saves typing.
 */
export function suggestCommitMessage(changes: GitChange[]): string {
  if (changes.length === 0) return "";
  const verb = changes.every((c) => c.status === "untracked" || c.status === "added")
    ? "Add"
    : changes.every((c) => c.status === "deleted")
      ? "Remove"
      : "Update";
  const parts = [...new Set(changes.map((c) => describe(c.path)))];
  if (parts.length > 3) return `${verb} ${parts.slice(0, 2).join(", ")} and ${parts.length - 2} more`;
  if (parts.length === 1) return `${verb} ${parts[0]}`;
  return `${verb} ${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
}
