import { IconRefresh, IconTrash, IconLock } from "@tabler/icons-react";
import { useWebTerminal } from "../hooks/useWebTerminal";
import type { TerminalStatus } from "../hooks/useWebTerminal";
import { WebTerminal } from "../components/Terminal/WebTerminal";
import { Button, PageHeader, StatusBadge, EmptyState, type Status } from "../components/ui";

// TerminalStatus isn't an execution Status, but it maps cleanly onto one for
// display: StatusBadge already carries the icon + text + color semantics
// (WCAG 1.4.1) this badge used to hardcode by hand.
const TERMINAL_STATUS_MAP: Record<TerminalStatus, Status> = {
  connecting: "pending",
  connected: "success",
  disconnected: "failed",
  disabled: "idle",
  unsupported: "failed",
};

export function TerminalPage() {
  const { status, output, sendInput, clear, reconnect } = useWebTerminal();

  return (
    <div style={{ padding: "var(--space-6)", display: "flex", flexDirection: "column", height: "calc(100vh - 40px)" }}>
      <PageHeader
        title="Web Terminal"
        description="Interactive PTY shell attached to the Ducta workspace environment."
        actions={
          status === "disabled" ? undefined : (
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <StatusBadge status={TERMINAL_STATUS_MAP[status]} label={status.toUpperCase()} />
              <Button variant="secondary" size="sm" onClick={clear}>
                <IconTrash size={14} /> Clear
              </Button>
              <Button variant="secondary" size="sm" onClick={reconnect}>
                <IconRefresh size={14} /> Reconnect
              </Button>
            </div>
          )
        }
      />

      {status === "disabled" ? (
        <EmptyState
          icon={IconLock}
          title="Embedded Web Terminal Disabled"
          description="The web terminal grants arbitrary shell access and is disabled by default for security posture. To enable it, launch the Ducta UI with the flag below."
          action={
            <code style={{ background: "rgba(0,0,0,0.2)", padding: "6px 12px", borderRadius: 4 }}>
              ducta ui --enable-terminal
            </code>
          }
        />
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
