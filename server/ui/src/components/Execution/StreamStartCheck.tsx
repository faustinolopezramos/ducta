import type { StreamPlan } from "../../api/queries/streamPlan";
import { Button } from "../ui/Button";
import { Modal } from "../ui/Modal";
import { StreamPlanList } from "./StreamPlanCard";

/**
 * Shown instead of starting a stream whose plan has errors: each node with its problem,
 * so the stream is not started just to fail. A stream with no errors never sees it.
 */
export function StreamStartCheck({
  plan,
  pipeline,
  env,
  checking,
  onCheckAgain,
  onClose,
}: {
  plan: StreamPlan;
  pipeline: string;
  env: string;
  checking?: boolean;
  onCheckAgain: () => void;
  onClose: () => void;
}) {
  return (
    <Modal title={`${pipeline} can’t start in ${env}`} onClose={onClose} width={520}>
      <div className="projects-modal__form">
        <p className="projects-modal__hint">
          Starting it would fail on what is marked below. Fix it, then check again.
        </p>
        <StreamPlanList plan={plan} />
        <div className="projects-modal__actions">
          <Button type="button" variant="ghost" onClick={onClose}>
            Close
          </Button>
          <Button type="button" variant="primary" loading={checking} onClick={onCheckAgain}>
            Check again
          </Button>
        </div>
      </div>
    </Modal>
  );
}
