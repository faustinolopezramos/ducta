import { colors, styles } from "../../theme/tokens";
import { Button } from "../ui";
import { Skeleton } from "../ui/Skeleton";
import { ICONS } from "../icons";
import { useRepository } from "../../api/queries";
import { useRepositoryPush, useRepositoryPull, apiErrorMessage } from "../../api/mutations";
import { useToastStack } from "../../hooks/useModalStack";


const TYPE_META = {
  local:  { label: "Local",  color: colors.textMuted,  bg: colors.surface },
  github: { label: "GitHub", color: colors.green,      bg: colors.greenA12 },
  azure:  { label: "Azure",  color: colors.blue,       bg: colors.blueA12 },
  aws:    { label: "AWS",    color: colors.amber,      bg: colors.amberA15 },
};

type RepositoryType = keyof typeof TYPE_META;

function TypeBadge({ type }: { type?: string | null }) {
  const safeType: RepositoryType =
    type && type in TYPE_META ? (type as RepositoryType) : "local";
  const meta = TYPE_META[safeType];
  return (
    <span
      style={{
        ...styles.fontMono,
        fontSize: 10,
        padding: "2px 8px",
        background: meta.bg,
        color: meta.color,
        border: `1px solid ${meta.color}33`,
        borderRadius: 4,
        userSelect: "none",
      }}
    >
      {meta.label}
    </span>
  );
}

function ConnectedDot({ connected }: { connected: any }) {
  return (
    <span
      style={{
        width: 8,
        height: 8,
        borderRadius: "50%",
        background: connected ? colors.green : colors.red,
        display: "inline-block",
        flexShrink: 0,
      }}
      title={connected ? "Connected" : "Unreachable"}
    />
  );
}

export function RepositoryStatus() {
  const { show } = useToastStack();

  const {
    data: repo,
    isLoading,
    isError,
    refetch,
  } = useRepository();

  const { mutate: push, isPending: pushing } = useRepositoryPush();
  const { mutate: pull, isPending: pulling } = useRepositoryPull();

  const handlePush = () => {
    push(
      { branch: repo?.branch ?? "main" },
      {
        onSuccess: (data: any) => show(data.message ?? "Pushed successfully", "success"),
        onError:   (e)         => show(apiErrorMessage(e, "Push failed"), "error"),
      }
    );
  };

  const handlePull = () => {
    pull(
      { branch: repo?.branch ?? "main" },
      {
        onSuccess: (data: any) => show(data.message ?? "Pulled successfully", "success"),
        onError:   (e)         => show(apiErrorMessage(e, "Pull failed"), "error"),
      }
    );
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
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          padding: "12px 16px",
          borderBottom: `1px solid ${colors.border}`,
          gap: 10,
        }}
      >
        <span
          style={{
            ...styles.fontSans,
            fontSize: 13,
            fontWeight: 600,
            color: colors.text,
            flex: 1,
          }}
        >
          {ICONS.CONNECTIONS} Remote repository
        </span>
        <Button variant="ghost" size="sm" onClick={() => refetch()}>
          ↻
        </Button>
      </div>

      {/* Body */}
      <div style={{ padding: "14px 16px" }}>
        {isLoading && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <Skeleton variant="text" width="70%" />
            <Skeleton variant="text" width="50%" />
          </div>
        )}
        {isError && (
          <div style={{ ...styles.fontSans, fontSize: 12, color: colors.red }}>
            Failed to load repository info.
          </div>
        )}
        {repo && (
          <>
            {/* Meta row */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                marginBottom: 12,
                flexWrap: "wrap",
              }}
            >
              <TypeBadge type={repo.type} />
              <ConnectedDot connected={repo.connected} />
              <span style={{ ...styles.fontSans, fontSize: 12, color: colors.textMuted }}>
                {repo.connected ? "Connected" : "Unreachable"}
              </span>
            </div>

            {/* Remote URL */}
            {repo.remote_url && repo.remote_url !== "local" && (
              <div
                style={{
                  ...styles.fontMono,
                  fontSize: 11,
                  color: colors.textMuted,
                  marginBottom: 8,
                  overflowX: "auto",
                  whiteSpace: "nowrap",
                  padding: "5px 8px",
                  background: colors.bg,
                  border: `1px solid ${colors.border}`,
                  borderRadius: 5,
                }}
                title={repo.remote_url}
              >
                {repo.remote_url}
              </div>
            )}

            {/* Branch */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                marginBottom: 16,
              }}
            >
              <span style={{ ...styles.fontSans, fontSize: 11, color: colors.textMuted }}>
                Branch:
              </span>
              <span
                style={{
                  ...styles.fontMono,
                  fontSize: 11,
                  padding: "2px 7px",
                  background: colors.accentBg,
                  color: colors.accent,
                  border: `1px solid ${colors.accentA20}`,
                  borderRadius: 4,
                }}
              >
                {repo.branch}
              </span>
            </div>

            {/* Push / Pull — only for non-local */}
            {repo.type !== "local" && (
              <div style={{ display: "flex", gap: 8 }}>
                <Button variant="ghost"
                  size="sm"
                  onClick={handlePush}
                  disabled={pushing || pulling || !repo.connected}
                  title={`Push to ${repo.branch}`}
                >
                  {ICONS.EXPORT} {pushing ? "Pushing…" : "Push"}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={handlePull}
                  disabled={pushing || pulling || !repo.connected}
                  title={`Pull from ${repo.branch}`}
                >
                  {ICONS.IMPORT} {pulling ? "Pulling…" : "Pull"}
                </Button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
