import { useState, type FormEvent } from "react";
import { Button } from "../ui";
import { ConnectorField } from "./ConnectorField";

interface AzureConnectPayload {
  type: "azure";
  token: string;
  org: string;
  project: string;
  repo: string;
  branch: string;
}

interface AzureConnectorProps {
  onConnect: (payload: AzureConnectPayload) => void;
  isPending: boolean;
}

// ─────────────────────────────────────────────
// AzureConnector — Azure DevOps repository form
//
// Props:
//   onConnect(payload)  — called on submit with
//                         { type, token, org, project, repo, branch }
//   isPending           — disables submit while mutation is in flight
// ─────────────────────────────────────────────

export function AzureConnector({ onConnect, isPending }: AzureConnectorProps) {
  const [form, setForm] = useState({
    token:   "",
    org:     "",
    project: "",
    repo:    "",
    branch:  "main",
  });

  const set = (key: keyof typeof form) => (v: string) =>
    setForm((p) => ({ ...p, [key]: v }));

  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    onConnect({ type: "azure", ...form });
  };

  return (
    <form onSubmit={handleSubmit}>
      <ConnectorField
        label="Personal Access Token"
        type="password"
        value={form.token}
        onChange={set("token")}
        placeholder="Azure PAT"
        required
      />
      <ConnectorField
        label="Organization URL"
        value={form.org}
        onChange={set("org")}
        placeholder="https://dev.azure.com/my-org"
        required
      />
      <ConnectorField
        label="Project"
        value={form.project}
        onChange={set("project")}
        placeholder="my-project"
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
          {isPending ? "Connecting…" : "Connect Azure →"}
        </Button>
      </div>
    </form>
  );
}
