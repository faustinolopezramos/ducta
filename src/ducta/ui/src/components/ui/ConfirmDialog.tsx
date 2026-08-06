import { useEffect, useId, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Modal } from "./Modal";
import { Button } from "./Button";
import "./ConfirmDialog.css";

/**
 * Confirmation for an action the user cannot take back.
 *
 * This replaces `window.confirm()`, which the app used for every destructive
 * action. The native dialog prefixes the host ("127.0.0.1:8000 says…"), cannot
 * be styled, cannot show what is about to be affected, gives a delete and a
 * rename the same weight — and, after a few uses, the browser offers to
 * suppress it, at which point the destructive action runs with no confirmation
 * at all.
 *
 * Built on `Modal`, so it inherits the focus trap, Escape handling and focus
 * restoration in `useDialogA11y` rather than reimplementing them.
 */
export interface ConfirmSpec {
  /** Short, specific: "Delete run 3f9a2c?" rather than "Are you sure?" */
  title: string;
  /** What happens, and what cannot be undone. */
  description?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  /** `danger` colours the confirm button and marks the dialog as destructive. */
  tone?: "default" | "danger";
  /**
   * Require the user to type this exact string before confirming. For actions
   * whose blast radius justifies the friction — promoting to production,
   * deleting something referenced elsewhere.
   */
  requireTyping?: string;
}

export interface ConfirmDialogProps extends ConfirmSpec {
  open: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  /** Disables the confirm button while the action is in flight. */
  pending?: boolean;
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  tone = "default",
  requireTyping,
  onConfirm,
  onCancel,
  pending = false,
}: Readonly<ConfirmDialogProps>) {
  const [typed, setTyped] = useState("");
  const confirmRef = useRef<HTMLButtonElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const inputId = useId();
  const descriptionId = `${inputId}-description`;

  // Reset between openings so a previous attempt's text never carries over.
  useEffect(() => {
    if (open) setTyped("");
  }, [open]);

  // `Modal`'s useDialogA11y focuses the dialog container on mount, so the
  // initial focus has to be claimed after it — `autoFocus` alone loses the race.
  // The input when one must be typed, the confirm button otherwise.
  useEffect(() => {
    if (!open) return;
    const target = requireTyping ? inputRef.current : confirmRef.current;
    target?.focus();
  }, [open, requireTyping]);

  if (!open) return null;

  const satisfied = !requireTyping || typed.trim() === requireTyping;

  return (
    <Modal
      open
      title={title}
      onClose={onCancel}
      width={440}
      ariaDescribedBy={description ? descriptionId : undefined}
    >
      <div className="confirm-dialog">
        {description && (
          <p id={descriptionId} className="confirm-dialog__description">
            {description}
          </p>
        )}

        {requireTyping && (
          <label className="confirm-dialog__typing" htmlFor={inputId}>
            <span>
              Type <code>{requireTyping}</code> to confirm
            </span>
            <input
              id={inputId}
              ref={inputRef}
              className="confirm-dialog__input"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && satisfied && !pending) onConfirm();
              }}
              autoComplete="off"
              aria-describedby={description ? descriptionId : undefined}
            />
          </label>
        )}

        <div className="confirm-dialog__actions">
          <Button variant="ghost" onClick={onCancel} disabled={pending}>
            {cancelLabel}
          </Button>
          <Button
            ref={confirmRef}
            variant={tone === "danger" ? "danger" : "primary"}
            onClick={onConfirm}
            disabled={!satisfied}
            loading={pending}
          >
            {confirmLabel}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
