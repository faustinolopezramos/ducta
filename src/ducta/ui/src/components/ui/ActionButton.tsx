import { useState } from "react";
import { Button, type ButtonProps } from "./Button";
import { toastStore } from "../../hooks/useModalStack";

export interface ActionButtonProps extends Omit<ButtonProps, "onClick" | "loading"> {
  /** Performs the action; throw (or reject) on failure. */
  onAction: () => Promise<unknown> | void;
  /** If set, shows a native confirm() prompt before running the action. */
  confirm?: string;
  /** Toast shown on success. Omit to stay silent. */
  successMessage?: string;
  /** Toast shown on failure, falls back to the caught error's detail. */
  errorMessage?: string;
}

/**
 * Row-action button: wraps `Button` with confirm-before-run, a local pending
 * spinner, and a toast on success/failure — the pattern repeated across
 * Quality/Ingestion/MLOps action rows.
 */
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

  const handleClick = async () => {
    if (confirm && !window.confirm(confirm)) return;
    setPending(true);
    try {
      await onAction();
      if (successMessage) toastStore.getState().success(successMessage);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data
        ?.detail;
      toastStore.getState().error(detail ?? errorMessage ?? "Action failed");
    } finally {
      setPending(false);
    }
  };

  return (
    <Button {...rest} loading={pending} disabled={disabled} onClick={handleClick}>
      {children}
    </Button>
  );
}
