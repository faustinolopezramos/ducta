import { useQuery } from "@tanstack/react-query";
import client from "../client";
import { qk } from "../queryKeys";

/** `GET /auth/me`: who is signed in and what their roles allow. */
export interface CurrentUser {
  id: string;
  username: string;
  email: string;
  roles: string[];
  /** Permission names, or `["*"]` for an admin. */
  permissions: string[];
}

/**
 * The signed-in user. With authentication turned off the server answers with its
 * development admin (`permissions: ["*"]`), so a local UI keeps every action.
 */
export const useCurrentUser = () =>
  useQuery<CurrentUser>({
    queryKey: qk.auth.me(),
    queryFn: () => client.get("/auth/me").then((r) => r.data),
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
