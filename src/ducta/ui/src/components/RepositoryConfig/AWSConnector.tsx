import { useState, type FormEvent } from "react";
import { Button } from "../ui";
import { ConnectorField } from "./ConnectorField";

interface AWSConnectPayload {
  type: "aws";
  region: string;
  repo: string;
  aws_https_username: string;
  aws_https_password: string;
  branch: string;
}

interface AWSConnectorProps {
  onConnect: (payload: AWSConnectPayload) => void;
  isPending: boolean;
}

// ─────────────────────────────────────────────
// AWSConnector — AWS CodeCommit repository form
//
// Props:
//   onConnect(payload)  — called on submit with
//                         { type, region, repo, aws_https_username,
//                           aws_https_password, branch }
//   isPending           — disables submit while mutation is in flight
// ─────────────────────────────────────────────

export function AWSConnector({ onConnect, isPending }: AWSConnectorProps) {
  const [form, setForm] = useState({
    region:              "",
    repo:                "",
    aws_https_username:  "",
    aws_https_password:  "",
    branch:              "main",
  });

  const set = (key: keyof typeof form) => (v: string) =>
    setForm((p) => ({ ...p, [key]: v }));

  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    onConnect({ type: "aws", ...form });
  };

  return (
    <form onSubmit={handleSubmit}>
      <ConnectorField
        label="Region"
        value={form.region}
        onChange={set("region")}
        placeholder="us-east-1"
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
        label="HTTPS Git username (IAM)"
        value={form.aws_https_username}
        onChange={set("aws_https_username")}
        placeholder="IAM HTTPS credential username"
      />
      <ConnectorField
        label="HTTPS Git password (IAM)"
        type="password"
        value={form.aws_https_password}
        onChange={set("aws_https_password")}
        placeholder="IAM HTTPS credential password"
      />
      <ConnectorField
        label="Branch"
        value={form.branch}
        onChange={set("branch")}
        placeholder="main"
      />
      <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 4 }}>
        <Button variant="ghost" type="submit" size="sm" disabled={isPending}>
          {isPending ? "Connecting…" : "Connect AWS →"}
        </Button>
      </div>
    </form>
  );
}
