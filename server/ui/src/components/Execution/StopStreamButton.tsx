import { useState } from "react";
import { IconPlayerStop } from "@tabler/icons-react";
import { useCancelExecution } from "../../api/mutations";
import { ConfirmDialog } from "../ui/ConfirmDialog";
import { PermittedButton } from "../ui/PermittedButton";
import "./StreamingStatusPanel.css";

/** Stops the whole stream: every query finishes its batch, and a start resumes from the checkpoints. */
export function StopStreamButton({ executionId, name, className }: { executionId: string; name: string; className?: string }) {
  const [asking, setAsking] = useState(false);
  const cancel = useCancelExecution();
  return (
    <>
      <PermittedButton
        permission="pipeline.execute"
        variant="secondary"
        size="sm"
        className={className}
        loading={cancel.isPending}
        leftIcon={<IconPlayerStop size={14} />}
        title="Stop every query of this stream, each after its current batch"
        onClick={() => setAsking(true)}
      >
        Stop stream
      </PermittedButton>
      <ConfirmDialog
        open={asking}
        title={`Stop ${name}?`}
        description="Every query finishes its current batch and stops. Starting the stream again resumes each from its checkpoint."
        confirmLabel="Stop stream"
        pending={cancel.isPending}
        onCancel={() => setAsking(false)}
        onConfirm={() => cancel.mutate(executionId, { onSettled: () => setAsking(false) })}
      />
    </>
  );
}
