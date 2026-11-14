import { useState } from "react";
import { Button, type ButtonProps } from "./Button";
import { ConfirmDialog, type ConfirmSpec } from "./ConfirmDialog";
import { toastStore } from "../../hooks/useModalStack";

export interface ActionButtonProps extends Omit<ButtonProps, "onClick" | "loading"> {
  /** Performs the action; throw (or reject) on failure. */
  onAction: () => Promise<unknown> | void;
  /**
   * Ask before running the action.
   *
   * A plain string keeps the previous call sites working and is shown as the
   * dialog's title. Pass a {@link ConfirmSpec} to add a description, mark the
   * action destructive (`tone: "danger"`), or require the user to type a
   * confirmation string.
   *
   * This used to call `window.confirm()`, whose dialog cannot be styled, gives
   * every action the same weight, and — once the browser offers to suppress it —
   * lets a destructive action run with no confirmation at all.
   */
  confirm?: string | ConfirmSpec;
  /** Toast shown on success. Omit to stay silent. */
  successMessage?: string;
  /** Toast shown on failure, falls back to the caught error's detail. */
  errorMessage?: string;
}

function toSpec(confirm: string | ConfirmSpec): ConfirmSpec {
  return typeof confirm === "string" ? { title: confirm } : confirm;
}

export function ActionButton({
  onAction,
  confirm,
  successMessage,
  errorMessage,
  children,
  disabled,
  ...rest
}: ActionButtonProps) {
  const [pending, setPending] = useState(false);
  const [asking, setAsking] = useState(false);

  const run = async () => {
    setPending(true);
    try {
      await onAction();
      if (successMessage) toastStore.getState().success(successMessage);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toastStore.getState().error(detail ?? errorMessage ?? "Action failed");
    } finally {
      setPending(false);
      setAsking(false);
    }
  };

  const handleClick = () => {
    if (confirm) {
      setAsking(true);
      return;
    }
    void run();
  };

  const spec = confirm ? toSpec(confirm) : null;

  return (
    <>
      <Button {...rest} loading={pending} disabled={disabled} onClick={handleClick}>
        {children}
      </Button>
      {spec && (
        <ConfirmDialog
          {...spec}
          open={asking}
          pending={pending}
          confirmLabel={spec.confirmLabel ?? (spec.tone === "danger" ? "Delete" : "Confirm")}
          onConfirm={() => void run()}
          onCancel={() => setAsking(false)}
        />
      )}
    </>
  );
}
