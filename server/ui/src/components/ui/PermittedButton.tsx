import { Button, type ButtonProps } from "./Button";
import { requiresPermission, usePermission } from "../../hooks/usePermission";

export interface PermittedButtonProps extends ButtonProps {
  /** The permission the action needs; without it the button is disabled and says why. */
  permission: string;
}

/**
 * A {@link Button} for an action that needs a permission. It stays visible so the user
 * knows the action exists, disabled with a tooltip naming the permission it needs.
 * The server enforces the same permission; this keeps the UI from offering a 403.
 */
export function PermittedButton({ permission, disabled, title, ...rest }: PermittedButtonProps) {
  const allowed = usePermission(permission);
  return (
    <Button
      {...rest}
      disabled={disabled || !allowed}
      title={allowed ? title : requiresPermission(permission)}
    />
  );
}
