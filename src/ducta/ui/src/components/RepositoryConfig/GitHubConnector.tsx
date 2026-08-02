import { useState, type FormEvent } from "react";
import { Button } from "../ui";
import { ConnectorField } from "./ConnectorField";

interface GitHubConnectPayload {
  type: "github";
  token: string;
  org: string;
  repo: string;
  branch: string;
}

interface GitHubConnectorProps {
  onConnect: (payload: GitHubConnectPayload) => void;
  isPending: boolean;
}

// ─────────────────────────────────────────────
// GitHubConnector — GitHub repository form
//
// Props:
//   onConnect(payload)  — called on submit with { type, token, org, repo, branch }
//   isPending           — disables submit while mutation is in flight
// ─────────────────────────────────────────────

export function GitHubConnector({ onConnect, isPending }: GitHubConnectorProps) {
  const [form, setForm] = useState({
    token:  "",
    org:    "",
    repo:   "",
    branch: "main",
  });

  const set = (key: keyof typeof form) => (v: string) =>
    setForm((p) => ({ ...p, [key]: v }));

  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    onConnect({ type: "github", ...form });
  };

  return (
    <form onSubmit={handleSubmit}>
      <ConnectorField
        label="Personal Access Token"
        type="password"
        value={form.token}
        onChange={set("token")}
        placeholder="ghp_…"
        required
      />
      <ConnectorField
        label="Organization / Username"
        value={form.org}
        onChange={set("org")}
        placeholder="my-org"
        required
      />
      <ConnectorField
        label="Repository name"
        value={form.repo}
        onChange={set("repo")}
        placeholder="ducta-workspace"
        required
      />
      <ConnectorField
        label="Branch"
        value={form.branch}
        onChange={set("branch")}
        placeholder="main"
      />
      <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 4 }}>
        <Button variant="ghost" type="submit" size="sm" disabled={isPending}>
          {isPending ? "Connecting…" : "Connect GitHub →"}
        </Button>
      </div>
    </form>
  );
}
