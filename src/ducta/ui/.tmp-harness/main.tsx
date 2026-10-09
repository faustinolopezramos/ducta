// Test harness only: seeds a session (auth is off on the test server) and opens ?to=.
import { createRoot } from "react-dom/client";
import { useAuthStore } from "../src/store/auth";
import { useGitConfigStore } from "../src/store/gitConfig";
import "../src/index.css";

const to = new URLSearchParams(location.search).get("to") ?? "/projects";
const ws = new URLSearchParams(location.search).get("ws") ?? import.meta.env.VITE_HARNESS_WORKSPACE;
if (ws) localStorage.setItem("ducta:selected-source", ws);
useGitConfigStore.getState().markSkipped();
const payload = btoa(JSON.stringify({ sub: "dev-admin", exp: Math.floor(Date.now() / 1000) + 3600 }));
useAuthStore.getState().login({ token: "h." + payload + ".s", user: { id: "dev-admin", username: "dev-admin", roles: ["admin"] } as never });
history.replaceState(null, "", to);
const { default: App } = await import("../src/App");
createRoot(document.getElementById("root")!).render(<App />);
