import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

/** A router at a project page, and a query cache filled with what the story shows. */
export function Shell({ children, data = [], path = "/p/demo" }: { children: ReactNode; data?: [unknown[], unknown][]; path?: string }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity, enabled: true } } });
  for (const [key, value] of data) client.setQueryData(key, value);
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>{children}</MemoryRouter>
    </QueryClientProvider>
  );
}
