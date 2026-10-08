import { useCurrentUser } from "../api/queries/auth";

/** Whether `permissions` grant `permission` (`"*"` grants everything). */
export function hasPermission(permissions: readonly string[] | undefined, permission: string): boolean {
  if (!permissions) return false;
  return permissions.includes("*") || permissions.includes(permission);
}

/**
 * What the signed-in user may do. `can(p)` is `false` until the user has loaded, so
 * a write action is never offered to someone who turns out not to have it; the
 * server still refuses with 403 regardless (this only keeps the UI honest).
 */
export function usePermissions() {
  const { data, isLoading } = useCurrentUser();
  return {
    isLoading,
    can: (permission: string) => hasPermission(data?.permissions, permission),
  };
}

/** Shorthand for one permission. */
export function usePermission(permission: string): boolean {
  return usePermissions().can(permission);
}

/** Tooltip text for an action the user may not take. */
export const requiresPermission = (permission: string) =>
  `Requires the '${permission}' permission`;
