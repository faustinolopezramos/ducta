import { useCallback, useEffect, useState } from "react";
import { useBlocker } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import yaml from "js-yaml";
import { nodeCodeQuery } from "../../api/queries";
import { apiErrorMessage, useUpdateNode, useUpdatePipeline } from "../../api/mutations";
import { useBuilderStore } from "../../store/builderStore";
import type { EditorMarker } from "../../components/CodeEditor";

type ShowToast = (message: string, kind: "success" | "error" | "info") => void;

/**
 * Changing the pipeline from its page: the YAML lens, adding a node, opening a
 * node's code, the command palette — and guarding unsaved canvas edits.
 *
 * Every write goes to the server; the pipeline query refetches on success, so
 * there is no local copy to patch up afterwards.
 */
export function usePipelineEditing({
  projectId,
  pipelineId,
  rawPipelineSpec,
  commitSha,
  selectNodeById,
  showToast,
}: {
  projectId: string | undefined;
  pipelineId: string | undefined;
  rawPipelineSpec: Record<string, any> | undefined;
  /** pipelines.yaml is one file per project, so OCC is file-scoped: the version this page last saw. */
  commitSha: string | undefined;
  selectNodeById: (id: string | null) => void;
  showToast: ShowToast;
}) {
  const { mutate: updatePipeline } = useUpdatePipeline();
  const { mutate: updateNode } = useUpdateNode();

  const [yamlMarkers, setYamlMarkers] = useState<EditorMarker[]>([]);
  const [isCodeEditorOpen, setIsCodeEditorOpen] = useState(false);
  const [openedNodeCode, setOpenedNodeCode] = useState<string>("");
  const [addNodeOpen, setAddNodeOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);

  // ── Unsaved canvas edits ──────────────────────────────────────────────────
  // Rendered as a <ConfirmDialog> by the consuming page (PipelinePage) rather
  // than window.confirm() here — a hook has no JSX of its own to render one,
  // and window.confirm can't be styled and blocks the whole tab. Only leaving
  // the pipeline is blocked: switching lens or focus rewrites the query string,
  // and asking "leave without saving?" for that would fire on every click.
  const isDirty = useBuilderStore((s) => s.isDirty);
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      isDirty && currentLocation.pathname !== nextLocation.pathname
  );
  useEffect(() => {
    if (!isDirty) return;
    const handler = (e: BeforeUnloadEvent) => { e.preventDefault(); };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [isDirty]);

  const handleSaveYaml = (newYaml: string) => {
    if (!projectId || !pipelineId) return;
    try {
      const parsedSpec = yaml.load(newYaml) as Record<string, any>;
      updatePipeline(
        { projectId, name: pipelineId, spec: parsedSpec, expectedSha: commitSha },
        {
          onSuccess: () => showToast(`Updated pipeline "${pipelineId}" specification`, "success"),
          onError: (err: any) => showToast(apiErrorMessage(err, "Failed to update pipeline"), "error"),
        }
      );
    } catch (e: any) {
      showToast(`Invalid YAML format: ${e.message}`, "error");
    }
  };

  const handleAddNode = (name: string, mod: string) => {
    if (!name || !mod || !projectId || !pipelineId) return;
    updateNode(
      // `function` is what makes the node addressable; the old payload sent
      // `type: "batch"`, which is a pipeline field a node has no use for.
      // `pipeline`: in a format-2 project a node is created inside its pipeline.
      { name, spec: { module: mod, function: "run", input: [], output: [] }, pipeline: pipelineId },
      {
        onSuccess: () => {
          const currentNodes: string[] = Array.isArray(rawPipelineSpec?.nodes) ? rawPipelineSpec.nodes : [];
          updatePipeline(
            {
              projectId,
              name: pipelineId,
              spec: { ...(rawPipelineSpec ?? {}), nodes: [...currentNodes, name] },
              expectedSha: commitSha,
            },
            {
              onSuccess: () => {
                showToast(`Node "${name}" added`, "success");
                setAddNodeOpen(false);
              },
              onError: (err: any) => showToast(
                `Node "${name}" was created but could not be linked to the pipeline. Add it manually via the YAML lens. Error: ${apiErrorMessage(err, "Unknown error")}`,
                "error"
              ),
            }
          );
        },
        onError: (err: any) => showToast(err?.message || "Failed to create node", "error"),
      }
    );
  };

  // ── Opening a node's code from anywhere (the list has no code of its own) ─
  // Through the same query the focus panel uses, so code it already loaded
  // opens straight from the cache.
  const queryClient = useQueryClient();
  const openCodeFor = useCallback(
    async (id: string) => {
      selectNodeById(id);
      try {
        const data = await queryClient.fetchQuery(nodeCodeQuery(id));
        if (data?.code != null) {
          setOpenedNodeCode(data.code);
          setIsCodeEditorOpen(true);
        } else {
          showToast(`No source file found for node "${id}"`, "info");
        }
      } catch (err) {
        showToast(apiErrorMessage(err, `Failed to load the code of node "${id}"`), "error");
      }
    },
    [queryClient, selectNodeById, showToast]
  );

  return {
    yamlMarkers, setYamlMarkers,
    isCodeEditorOpen, setIsCodeEditorOpen, openedNodeCode, setOpenedNodeCode, openCodeFor,
    addNodeOpen, setAddNodeOpen, paletteOpen, setPaletteOpen,
    handleSaveYaml, handleAddNode,
    blocker,
  };
}
