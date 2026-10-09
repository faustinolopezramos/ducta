/** `root` + `path`, with no empty segments ("" root = the workspace itself). */
export function joinPath(root: string, path: string): string {
  return [root, path].filter(Boolean).join("/").replace(/\/+/g, "/");
}

const LANGUAGES: Record<string, string> = {
  py: "python",
  yaml: "yaml",
  yml: "yaml",
  json: "json",
  toml: "toml",
  md: "markdown",
  sql: "sql",
  sh: "shell",
  txt: "plaintext",
  ini: "ini",
  cfg: "ini",
};

/** Monaco language id from a file name. */
export function languageFor(path: string): string {
  const ext = path.split(".").pop()?.toLowerCase() ?? "";
  return LANGUAGES[ext] ?? "plaintext";
}
