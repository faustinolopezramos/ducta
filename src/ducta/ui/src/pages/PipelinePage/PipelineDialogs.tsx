import type React from "react";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import type { Blocker } from "react-router-dom";
import { RunOptionsDialog, type RunOptions } from "../../components/Execution/RunOptionsDialog";

export interface PipelineDialogsProps {
  extractDialog?: React.ReactNode;
  subDialog?: React.ReactNode;
  runOptionsOpen: boolean;
  pipelineId?: string;
  activeEnv: string;
  pipelineNodes: Array<{ id: string }>;
  selectedInThisPipeline?: string | null;
  onCloseRunOptions: () => void;
  onRunWithOptions: (options: RunOptions) => void;
  confirmRun: (() => void) | null;
  /** The node the confirmed run is limited to; null when the whole pipeline runs. */
  confirmNode?: string | null;
  onCancelConfirmRun: () => void;
  onConfirmRun: () => void;
  blocker: Blocker;
  aiFixDialog?: React.ReactNode;
}

export function PipelineDialogs({
  extractDialog,
  subDialog,
  runOptionsOpen,
  pipelineId,
  activeEnv,
  pipelineNodes,
  selectedInThisPipeline,
  onCloseRunOptions,
  onRunWithOptions,
  confirmRun,
  confirmNode = null,
  onCancelConfirmRun,
  onConfirmRun,
  blocker,
  aiFixDialog,
}: PipelineDialogsProps) {
  return (
    <>
      {extractDialog}
      {subDialog}
      {runOptionsOpen && (
        <RunOptionsDialog
          pipeline={pipelineId ?? ""}
          env={activeEnv ?? ""}
          nodes={pipelineNodes.map((n) => n.id)}
          initialNode={selectedInThisPipeline ?? null}
          onCancel={onCloseRunOptions}
          onRun={onRunWithOptions}
        />
      )}
      <ConfirmDialog
        open={confirmRun !== null}
        tone="danger"
        title={confirmNode ? `Run node ${confirmNode} in ${activeEnv}?` : `Run ${pipelineId} in ${activeEnv}?`}
        description={
          confirmNode
            ? `${activeEnv} is production: this node writes real data. Type the node's name to run it.`
            : `${activeEnv} is production: this run writes real data. Type the pipeline's name to run it.`
        }
        requireTyping={confirmNode ?? pipelineId ?? ""}
        confirmLabel="Run in production"
        onCancel={onCancelConfirmRun}
        onConfirm={onConfirmRun}
      />
      <ConfirmDialog
        open={blocker.state === "blocked"}
        title="Leave without saving?"
        description="You have unsaved pipeline changes that will be lost."
        tone="danger"
        confirmLabel="Leave"
        onConfirm={() => blocker.proceed?.()}
        onCancel={() => blocker.reset?.()}
      />
      {aiFixDialog}
    </>
  );
}
