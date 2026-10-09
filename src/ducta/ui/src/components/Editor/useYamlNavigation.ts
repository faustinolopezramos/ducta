import { useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLocation, useNavigate } from "react-router-dom";
import type { Monaco } from "@monaco-editor/react";
import client from "../../api/client";
import { useCodeIndex, useProjectDatasets } from "../../api/queries";
import { projectIdFromPath, routes } from "../../utils/routes";
import { resolveToken, tokenAt, type NavigationIndex, type Target } from "./yamlNavigation";

type Model = { getLineContent: (n: number) => string; uri: { toString(): string } };
type Position = { lineNumber: number; column: number };

// The providers are registered once per Monaco; they read the current project's index.
let registeredFor: Monaco | null = null;
let current: { index: NavigationIndex; describe: (t: Target) => string; open: (t: Target) => void } | null = null;

function register(monaco: Monaco) {
  if (registeredFor === monaco) return;
  registeredFor = monaco;
  const targetAt = (model: Model, position: Position) => {
    if (!current) return null;
    const token = tokenAt(model.getLineContent(position.lineNumber), position.column);
    if (!token) return null;
    const target = resolveToken(token.text, current.index);
    return target ? { token, target } : null;
  };
  monaco.languages.registerDefinitionProvider("yaml", {
    // ⌘-click: the function's def, the dataset's catalog entry, the node's block.
    provideDefinition: (model: Model, position: Position) => {
      const hit = targetAt(model, position);
      if (hit) current?.open(hit.target);
      return null;
    },
  });
  monaco.languages.registerHoverProvider("yaml", {
    provideHover: (model: Model, position: Position) => {
      const hit = targetAt(model, position);
      if (!hit || !current) return null;
      return {
        range: { startLineNumber: position.lineNumber, endLineNumber: position.lineNumber, startColumn: hit.token.start, endColumn: hit.token.end },
        contents: [{ value: current.describe(hit.target) }, { value: "_⌘-click to open_" }],
      };
    },
  });
}

/**
 * In a project's YAML: hover a dataset, node or `module:function` to see what
 * it is, ⌘-click to go to it — the catalog entry, the pipeline block, the def.
 */
export function useYamlNavigation(monaco: Monaco | null, enabled: boolean) {
  const projectId = projectIdFromPath(useLocation().pathname) ?? "";
  const navigate = useNavigate();
  const on = enabled && !!projectId;
  const { data: locations } = useQuery<{ datasets: NavigationIndex["datasets"]; nodes: NavigationIndex["nodes"] }>({
    queryKey: ["server-projects", projectId, "locations"],
    queryFn: () => client.get(`/projects/${projectId}/locations`).then((r) => r.data),
    enabled: on,
    staleTime: 15 * 1000,
    retry: false,
  });
  const { data: codeIndex } = useCodeIndex(on ? projectId : "");
  const { data: datasets } = useProjectDatasets(on ? projectId : "");

  const index = useMemo<NavigationIndex>(() => {
    const functions: NavigationIndex["functions"] = {};
    for (const [file, fns] of Object.entries(codeIndex?.files ?? {})) {
      const module = file.replace(/\.py$/, "").replace(/\//g, ".").replace(/\.__init__$/, "");
      for (const f of fns) functions[`${module}:${f.name}`] = { file, line: f.line };
    }
    for (const n of codeIndex?.nodes ?? []) functions[`${n.module}:${n.function}`] ??= { file: n.file, line: n.line ?? null };
    return { datasets: locations?.datasets ?? {}, nodes: locations?.nodes ?? {}, functions };
  }, [locations, codeIndex]);

  useEffect(() => {
    if (!on || !monaco) return;
    register(monaco);
    const byName = new Map((datasets?.datasets ?? []).map((d) => [d.name, d]));
    current = {
      index,
      open: (t) => navigate(routes.code(projectId, t.at.file, t.at.line ?? undefined)),
      describe: (t) => {
        if (t.kind === "function") return `**${t.name}** — function in \`${t.at.file}:${t.at.line ?? "?"}\``;
        if (t.kind === "node") return `**${t.name}** — node of pipeline \`${t.at.pipeline ?? "?"}\``;
        const d = byName.get(t.name);
        const parts = [`**${t.name}** — dataset`, d?.format && `format \`${d.format}\``, d?.layer && `layer ${d.layer}`];
        const writers = d?.producers.map((p) => p.node).join(", ");
        const readers = d?.consumers.map((p) => p.node).join(", ");
        return [parts.filter(Boolean).join(" · "), writers && `written by ${writers}`, readers && `read by ${readers}`, d?.description]
          .filter(Boolean)
          .join("\n\n");
      },
    };
  }, [on, monaco, index, datasets, navigate, projectId]);
}
