import { IconTerminal, IconRefresh, IconTrash, IconLock } from "@tabler/icons-react";
import { useWebTerminal } from "../hooks/useWebTerminal";
import { WebTerminal } from "../components/Terminal/WebTerminal";
import { Button, PageHeader } from "../components/ui";

export function TerminalPage() {
  const { status, output, sendInput, clear, reconnect } = useWebTerminal();

  return (
    <div style={{ padding: "var(--space-6)", display: "flex", flexDirection: "column", height: "calc(100vh - 40px)" }}>
      <PageHeader
        title="Web Terminal"
        description="Interactive PTY shell attached to the Ducta workspace environment."
        actions={
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <span
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                padding: "4px 10px",
                borderRadius: 12,
                fontSize: 12,
                fontWeight: 600,
                backgroundColor:
                  status === "connected"
                    ? "rgba(34, 197, 94, 0.15)"
                    : status === "connecting"
                    ? "rgba(234, 179, 8, 0.15)"
                    : "rgba(239, 68, 68, 0.15)",
                color:
                  status === "connected"
                    ? "#22c55e"
                    : status === "connecting"
                    ? "#eab308"
                    : "#ef4444",
              }}
            >
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: "50%",
                  backgroundColor: "currentColor",
                }}
              />
              {status.toUpperCase()}
            </span>
            <Button variant="secondary" size="sm" onClick={clear}>
              <IconTrash size={14} /> Clear
            </Button>
            <Button variant="secondary" size="sm" onClick={reconnect}>
              <IconRefresh size={14} /> Reconnect
            </Button>
          </div>
        }
      />

      {status === "disabled" ? (
        <div
          style={{
            padding: 32,
            textAlign: "center",
            background: "var(--bg-surface)",
            borderRadius: 8,
            border: "1px solid var(--border)",
          }}
        >
          <IconLock size={48} style={{ opacity: 0.4, marginBottom: 12 }} />
          <h3 style={{ margin: "0 0 8px 0" }}>Embedded Web Terminal Disabled</h3>
          <p style={{ color: "var(--text-muted)", maxWidth: 480, margin: "0 auto 16px auto" }}>
            The web terminal grants arbitrary shell access and is disabled by default for security posture.
            To enable it, launch the Ducta UI with the flag:
          </p>
          <code style={{ background: "rgba(0,0,0,0.2)", padding: "6px 12px", borderRadius: 4 }}>
            ducta ui --enable-terminal
          </code>
        </div>
      ) : (
        <div style={{ flex: 1, minHeight: 0 }}>
          <WebTerminal
            output={output}
            status={status}
            onSendInput={sendInput}
            onClear={clear}
          />
        </div>
      )}
    </div>
  );
}

export default TerminalPage;
