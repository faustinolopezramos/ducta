import { useState } from "react";
import { colors, styles } from "../../theme/tokens";
import { ICONS } from "../icons";
import { useRepositoryConnect, apiErrorMessage, type RepositoryConnectPayload } from "../../api/mutations";
import { useToastStack } from "../../hooks/useModalStack";
import { GitHubConnector } from "./GitHubConnector";
import { AzureConnector } from "./AzureConnector";
import { AWSConnector } from "./AWSConnector";

const TYPES = [
  { value: "local",  label: "Local (no remote)", icon: ICONS.FOLDER },
  { value: "github", label: "GitHub",             icon: ICONS.CONNECTIONS },
  { value: "azure",  label: "Azure DevOps",       icon: ICONS.CONNECTIONS },
  { value: "aws",    label: "AWS CodeCommit",     icon: ICONS.CONNECTIONS },
];

const TYPE_ACCENT = {
  local:  { color: colors.textMuted,  bg: colors.surface,  border: colors.border },
  github: { color: colors.green,      bg: colors.greenA15, border: colors.greenA30 },
  azure:  { color: colors.blue,       bg: colors.blueA15,  border: colors.blueA30 },
  aws:    { color: colors.amber,      bg: colors.amberA15, border: colors.amberA30 },
};

export function RepositorySelector() {
  const { show } = useToastStack();
  const [type, setType] = useState("github");

  const { mutate: connect, isPending } = useRepositoryConnect();

  const handleConnect = (payload: RepositoryConnectPayload) => {
    connect(payload, {
      onSuccess: (data) => {
        show(
          `Connected to ${data.type}${data.remote_url ? ` — ${data.remote_url}` : ""}`,
          "success"
        );
      },
      onError: (e) => {
        show(apiErrorMessage(e, "Connection failed"), "error");
      },
    });
  };

  const handleLocalConnect = () => {
    connect({ type: "local" }, {
      onSuccess: () => show("Using local git workspace", "success"),
      onError:   (e) => show(apiErrorMessage(e, "Failed"), "error"),
    });
  };

  return (
    <div
      style={{
        background: colors.surface,
        border: `1px solid ${colors.border}`,
        borderRadius: 10,
        overflow: "hidden",
      }}
    >
      {/* Type selector */}
      <div
        style={{
          padding: "16px 16px 0",
          borderBottom: `1px solid ${colors.border}`,
          paddingBottom: 16,
        }}
      >
        <p
          style={{
            ...styles.fontSans,
            fontSize: 11,
            color: colors.textMuted,
            textTransform: "uppercase",
            letterSpacing: "0.06em",
            margin: "0 0 10px",
          }}
        >
          Repository type
        </p>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {TYPES.map((t) => {
            const accent = TYPE_ACCENT[t.value as keyof typeof TYPE_ACCENT];
            const active  = type === t.value;
            return (
              <button
                key={t.value}
                type="button"
                onClick={() => setType(t.value)}
                style={{
                  ...styles.fontSans,
                  fontSize: 12,
                  padding: "5px 14px",
                  background: active ? accent.bg    : colors.bg,
                  border:     `1px solid ${active ? accent.border : colors.border}`,
                  borderRadius: 6,
                  color:      active ? accent.color : colors.textMuted,
                  cursor:     "pointer",
                  transition: "all 0.12s",
                  fontWeight: active ? 600 : 400,
                }}
              >
                {t.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Connector form */}
      <div style={{ padding: "16px 16px 20px" }}>
        {type === "github" && (
          <GitHubConnector onConnect={handleConnect} isPending={isPending} />
        )}
        {type === "azure" && (
          <AzureConnector onConnect={handleConnect} isPending={isPending} />
        )}
        {type === "aws" && (
          <AWSConnector onConnect={handleConnect} isPending={isPending} />
        )}
        {type === "local" && (
          <div>
            <p
              style={{
                ...styles.fontSans,
                fontSize: 13,
                color: colors.textMuted,
                margin: "0 0 14px",
                lineHeight: 1.5,
              }}
            >
              Local mode uses the workspace directory as a git repository
              with no remote. Push and Pull will be disabled.
            </p>
            <div style={{ display: "flex", justifyContent: "flex-end" }}>
              <button
                type="button"
                onClick={handleLocalConnect}
                disabled={isPending}
                style={{
                  ...styles.fontSans,
                  fontSize: 13,
                  padding: "7px 16px",
                  background: colors.accentBg,
                  border: `1px solid ${colors.accentA30}`,
                  borderRadius: 6,
                  color: colors.accent,
                  cursor: isPending ? "not-allowed" : "pointer",
                  opacity: isPending ? 0.6 : 1,
                  fontWeight: 500,
                }}
              >
                {isPending ? "Saving…" : "Use local →"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
