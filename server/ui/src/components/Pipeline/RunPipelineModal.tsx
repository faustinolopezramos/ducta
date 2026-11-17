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
import { fetchStreamPlan, type StreamPlan } from "../../api/queries/streamPlan";
import { StreamPlanList } from "../Execution/StreamPlanCard";
import "../ui/Input.css";

/**
 * Centered "Run pipeline" modal for the List view — the canvas already has a
 * visible environment selector next to its own Run button; this gives the
 * same choice to the List's pipeline cards, which had no run action at all.
 */
export function RunPipelineModal({
  projectId,
  pipelineName,
  streaming = false,
  onClose,
}: {
  projectId: string;
  pipelineName: string;
  /** A stream is started, not run, and its plan is checked first: it must not fail on a typo. */
  streaming?: boolean;
  onClose: () => void;
}) {
  const defaultEnv = useSourceStore((s) => s.activeEnv) ?? "base";
  const { data: envsData } = useEnvironments();
  const envs: string[] = envsData?.environments?.length ? envsData.environments : [defaultEnv];
  const [env, setEnv] = useState(defaultEnv);
  const canRun = usePermission("pipeline.execute");
  const execute = useExecutePipeline();
  const [checking, setChecking] = useState(false);
  const [blocked, setBlocked] = useState<StreamPlan | null>(null);

  const submit = async () => {
    if (streaming) {
      setChecking(true);
      try {
        const plan = await fetchStreamPlan(projectId, pipelineName, env);
        if (!plan.ok) {
          setBlocked(plan);
          return;
        }
        setBlocked(null);
      } catch {
        // The plan is a courtesy: if it cannot be made, starting reports the real problem.
      } finally {
        setChecking(false);
      }
    }
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
    <Modal title={`${streaming ? "Start stream" : "Run"} ${pipelineName}`} onClose={onClose} width={streaming ? 480 : 420}>
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

        {blocked && (
          <>
            <p className="projects-modal__hint projects-modal__hint--below">
              It would fail on what is marked below. Fix it, then start again.
            </p>
            <StreamPlanList plan={blocked} />
          </>
        )}

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <Button variant="ghost" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={submit}
            disabled={execute.isPending || checking || !canRun}
            title={canRun ? undefined : requiresPermission("pipeline.execute")}
            leftIcon={<IconPlayerPlay size={15} />}
          >
            {execute.isPending || checking ? (streaming && checking ? "Checking…" : "Starting…") : streaming ? "Start stream" : "Run"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
