/**
 * Monaco, bundled with the app rather than fetched from a CDN at runtime —
 * the UI is local-first and must work offline — with the YAML language server
 * (schema validation, completion, hover) and Ducta's own themes.
 *
 * Imported for its side effects by the editor components, which are lazy
 * chunks: none of this loads until an editor is opened.
 */
import * as monaco from "./monacoCore";
import { loader } from "@monaco-editor/react";
import { configureMonacoYaml, type MonacoYaml } from "monaco-yaml";
import EditorWorker from "monaco-editor/editor/editor.worker?worker";
import YamlWorker from "monaco-yaml/yaml.worker?worker";
import { withLegacyWorkers } from "./workerCompat";

(globalThis as unknown as { MonacoEnvironment: unknown }).MonacoEnvironment = {
  getWorker(_moduleId: string, label: string) {
    return label === "yaml" ? new YamlWorker() : new EditorWorker();
  },
};

loader.config({ monaco });

export { monaco };

// ── YAML: the project's own schema ────────────────────────────────────────────

let yaml: MonacoYaml | null = null;
let lastSchemaKey = "";

/** The format-2 schema as GET /projects/{id}/schema returns it. */
export interface ProjectSchema {
  $defs: { project: object; catalog: object; pipeline: object; profiles?: object; node_template?: object; pipeline_template?: object };
}

/**
 * Point the YAML language server at the project's schema, by file:
 * `ducta.yaml`, `catalog*.yaml` / `catalog/*.yaml`, `pipelines/**.yaml`.
 * The editor then validates, completes and documents keys as the loader
 * will read them. Idempotent for the same schema.
 */
export function setProjectSchema(schema: ProjectSchema) {
  const key = JSON.stringify(Object.keys(schema.$defs ?? {})) + JSON.stringify(schema).length;
  if (key === lastSchemaKey) return;
  lastSchemaKey = key;
  const defs = schema.$defs;
  const schemas = [
    { uri: "ducta://schema/project.json", fileMatch: ["**/ducta.yaml", "**/ducta.yml"], schema: defs.project },
    {
      uri: "ducta://schema/catalog.json",
      fileMatch: ["**/catalog.yaml", "**/catalog.yml", "**/catalog/*.yaml", "**/catalog/*.yml"],
      schema: defs.catalog,
    },
    { uri: "ducta://schema/pipeline.json", fileMatch: ["**/pipelines/**/*.yaml", "**/pipelines/**/*.yml"], schema: defs.pipeline },
  ];
  if (defs.profiles) {
    schemas.push({ uri: "ducta://schema/profiles.json", fileMatch: ["**/quality_profiles.yaml"], schema: defs.profiles });
  }
  if (defs.pipeline_template) {
    schemas.push({
      uri: "ducta://schema/pipeline_template.json",
      fileMatch: ["**/templates/pipelines/*.yaml", "**/templates/pipelines/*.yml"],
      schema: defs.pipeline_template,
    });
  }
  if (defs.node_template) {
    schemas.push({
      uri: "ducta://schema/node_template.json",
      fileMatch: ["**/templates/nodes/*.yaml", "**/templates/nodes/*.yml"],
      schema: defs.node_template,
    });
  }
  const options = { enableSchemaRequest: false, validate: true, completion: true, hover: true, schemas };
  if (yaml) yaml.update(options);
  else yaml = configureMonacoYaml(withLegacyWorkers(monaco), options);
}

// ── Themes from the design tokens ────────────────────────────────────────────

function cssVar(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return /^#[0-9a-f]{6}$/i.test(value) ? value : fallback;
}

/**
 * `ducta-light` / `ducta-dark`: Monaco's base themes with the app's surface,
 * text and accent colours, so the editor reads as part of the app. Re-defined
 * on each call so a theme switch picks up the current tokens.
 */
export function defineDuctaTheme(dark: boolean): string {
  const name = dark ? "ducta-dark" : "ducta-light";
  monaco.editor.defineTheme(name, {
    base: dark ? "vs-dark" : "vs",
    inherit: true,
    rules: [],
    colors: {
      "editor.background": cssVar("--surface", dark ? "#141F24" : "#FFFFFF"),
      "editor.foreground": cssVar("--text", dark ? "#E6EDF0" : "#1A2328"),
      "editorLineNumber.foreground": cssVar("--text-dim", dark ? "#5B6B73" : "#9AA5AB"),
      "editorCursor.foreground": cssVar("--primary", dark ? "#38BDF8" : "#0B5F73"),
      "editor.selectionBackground": dark ? "#38BDF833" : "#0B5F7326",
      "editorCodeLens.foreground": cssVar("--text-muted", dark ? "#8A9AA2" : "#5E6B72"),
    },
  });
  return name;
}
