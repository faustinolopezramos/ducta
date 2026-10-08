import { useState } from "react";
import { IconPlayerPlay } from "@tabler/icons-react";
import { Modal } from "../ui/Modal";
import { Button } from "../ui/Button";
import { Field } from "../ui/Field";
import { toastStore } from "../../hooks/useModalStack";
import { requiresPermission, usePermission } from "../../hooks/usePermission";
import { useSourceStore } from "../../store/workspace";
import { useEnvironments } from "../../api/queries";
import { useExecutePipeline, apiErrorMessage } from "../../api/mutations";
import "../ui/Input.css";

/**
 * Centered "Run pipeline" modal for the List view — the canvas already has a
 * visible environment selector next to its own Run button; this gives the
 * same choice to the List's pipeline cards, which had no run action at all.
 */
export function RunPipelineModal({
  projectId,
  pipelineName,
  onClose,
}: {
  projectId: string;
  pipelineName: string;
  onClose: () => void;
}) {
  const defaultEnv = useSourceStore((s) => s.activeEnv) ?? "base";
  const { data: envsData } = useEnvironments();
  const envs: string[] = envsData?.environments?.length ? envsData.environments : [defaultEnv];
  const [env, setEnv] = useState(defaultEnv);
  const canRun = usePermission("pipeline.execute");
  const execute = useExecutePipeline();

  const submit = () => {
    execute.mutate(
      { projectId, pipelineName, env },
      {
        onSuccess: () => {
          toastStore.getState().show(`Execution started — ${pipelineName} (${env})`, "success");
          onClose();
        },
        onError: (e) => {
          toastStore.getState().show(apiErrorMessage(e, "Failed to start execution"), "error");
        },
      }
    );
  };

  return (
    <Modal title={`Run ${pipelineName}`} onClose={onClose} width={420}>
      <div style={{ display: "grid", gap: 14 }}>
        <Field label="Environment">
          <select
            className="input-field"
            value={env}
            onChange={(e) => setEnv(e.target.value)}
          >
            {envs.map((e) => (
              <option key={e} value={e}>{e}</option>
            ))}
          </select>
        </Field>

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <Button variant="ghost" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={submit}
            disabled={execute.isPending || !canRun}
            title={canRun ? undefined : requiresPermission("pipeline.execute")}
            leftIcon={<IconPlayerPlay size={15} />}
          >
            {execute.isPending ? "Starting…" : "Run"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
