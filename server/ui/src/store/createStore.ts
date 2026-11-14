import { devtools } from "zustand/middleware";

const isDev = import.meta.env.DEV;

/**
 * Wrap a Zustand store creator with the `devtools` middleware in development
 * only, so production builds don't pay for the Redux DevTools bridge. Single
 * implementation of the `(isDev ? devtools(creator, { name }) : creator)`
 * line that used to be copy-pasted into every store file.
 */
export function withDevtools<T>(creator: T, name: string): T {
  return (isDev ? devtools(creator as any, { name }) : creator) as T;
}
