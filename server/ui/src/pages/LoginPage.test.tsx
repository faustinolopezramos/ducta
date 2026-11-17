import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LoginPage } from "./LoginPage";
import { useAuthStore } from "../store/auth";

let authEnabled = true;
const post = vi.fn((url: string) =>
  url === "/auth/refresh" && !authEnabled
    ? Promise.resolve({ data: { access_token: "h.e30.s", user: { id: "dev-admin", username: "dev-admin" } } })
    : Promise.reject(new Error("401")),
);
vi.mock("../api/client", () => ({
  default: {
    get: (url: string) =>
      url === "/auth/config" ? Promise.resolve({ data: { auth_enabled: authEnabled } }) : Promise.reject(new Error(url)),
    post: (url: string) => post(url),
  },
}));

function renderLogin() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={["/login"]}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/" element={<p>the app</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("LoginPage", () => {
  beforeEach(() => {
    useAuthStore.setState({ token: null, user: null });
    post.mockClear();
  });

  it("asks for credentials when the server has authentication on", async () => {
    authEnabled = true;
    renderLogin();
    expect(await screen.findByRole("button", { name: /sign in/i })).toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
  });

  it("goes straight in when the server runs without authentication", async () => {
    authEnabled = false;
    renderLogin();
    expect(await screen.findByText("the app")).toBeInTheDocument();
    await waitFor(() => expect(useAuthStore.getState().user?.id).toBe("dev-admin"));
  });
});
