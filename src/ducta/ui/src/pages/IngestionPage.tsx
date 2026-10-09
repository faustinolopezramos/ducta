import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { colors } from "../theme/tokens";
import { PageHeader } from "../components/ui/PageHeader";
import { PageContainer } from "../components/ui/PageContainer";
import type { SectionHeader } from "../components/App/SectionTabs";
import { Button } from "../components/ui/Button";
import { ActionButton } from "../components/ui/ActionButton";
import { EmptyState } from "../components/ui/EmptyState";
import { Panel } from "../components/ui/Panel";
import { Skeleton } from "../components/ui/Skeleton";
import {
  useConnections,
  useDeleteConnection,
  useRetestConnection,
  useConnectionUsage,
  type ConnectionInfo,
} from "../api/ingestionApi";
import { ConnectionModal } from "../components/Ingestion/ConnectionModal";
import { UseInPipelineModal } from "../components/Ingestion/UseInPipelineModal";
import { toastStore } from "../hooks/useModalStack";
import {
  IconPlus,
  IconTrash,
  IconRefresh,
  IconHistory,
  IconChevronDown,
  IconChevronRight,
  IconPencil,
  IconTopologyStar3,
  IconDatabaseImport,
  IconAlertTriangle,
  IconCircleCheck,
  IconCircleX,
} from "@tabler/icons-react";
import { routes } from "../utils/routes";

interface TestState {
  ok: boolean;
  at: number;
}

function TestChip({ state }: { state?: TestState }) {
  if (!state) return null;
  const color = state.ok ? "var(--success)" : "var(--danger)";
  const Icon = state.ok ? IconCircleCheck : IconCircleX;
  return (
    <span
      title={`Last test ${state.ok ? "succeeded" : "failed"} at ${new Date(state.at).toLocaleTimeString()}`}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "1px 7px",
        borderRadius: 4,
        fontSize: 10,
        fontWeight: 600,
        background: `color-mix(in srgb, ${color} 14%, transparent)`,
        color,
        textTransform: "uppercase",
        letterSpacing: "0.04em",
      }}
    >
      <Icon size={11} />
      {state.ok ? "OK" : "Failed"}
    </span>
  );
}

function ConnectionUsagePanel({ name }: { name: string }) {
  const navigate = useNavigate();
  const usage = useConnectionUsage(name, true);

  if (usage.isLoading) {
    return (
      <div style={{ marginTop: 6 }}>
        <Skeleton variant="text" width="70%" />
      </div>
    );
  }
  if (!usage.data || usage.data.pipelines.length === 0) {
    return (
      <p style={{ fontSize: 11, color: colors.textMuted, margin: "6px 0 0" }}>
        No pipeline node source was found referencing this connection name.
      </p>
    );
  }
  if (usage.data.executions.length === 0) {
    return (
      <p style={{ fontSize: 11, color: colors.textMuted, margin: "6px 0 0" }}>
        Referenced by pipeline(s) {usage.data.pipelines.join(", ")}, but no executions recorded yet.
      </p>
    );
  }
  return (
    <div style={{ marginTop: 6, display: "grid", gap: 4 }}>
      {usage.data.executions.map((e) => (
        <button
          key={e.execution_id}
          onClick={() =>
            e.project_id && navigate(routes.pipeline(e.project_id, e.pipeline_name))
          }
          style={{
            display: "flex",
            justifyContent: "space-between",
            gap: 8,
            background: "none",
            border: "none",
            padding: "2px 0",
            cursor: e.project_id ? "pointer" : "default",
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            color: colors.textMuted,
            textAlign: "left",
          }}
        >
          <span>{e.pipeline_name}</span>
          <span>{e.status}</span>
        </button>
      ))}
    </div>
  );
}

function ConnectionRow({
  connection,
  testState,
  onTested,
  onEdit,
  onUseInPipeline,
}: {
  connection: ConnectionInfo;
  testState?: TestState;
  onTested: (name: string, ok: boolean) => void;
  onEdit: () => void;
  onUseInPipeline: () => void;
}) {
  const del = useDeleteConnection();
  const retest = useRetestConnection();
  const [expanded, setExpanded] = useState(false);

  return (
    <div style={{ padding: "10px 0", borderTop: `1px solid ${colors.border}` }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 13, color: colors.text, fontWeight: 600 }}>{connection.name}</span>
            <TestChip state={testState} />
          </div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: colors.textMuted }}>
            {connection.type} · {connection.host}:{connection.port} · {connection.database}
            {connection.description ? ` — ${connection.description}` : ""}
          </div>
        </div>
        <div style={{ display: "flex", gap: 4, flexShrink: 0 }}>
          <Button
            variant="secondary"
            size="sm"
            onClick={onUseInPipeline}
            leftIcon={<IconTopologyStar3 size={14} />}
            title="Create a declarative ingestion node from this connection"
          >
            Use in pipeline
          </Button>
          <ActionButton
            variant="ghost"
            size="sm"
            leftIcon={<IconRefresh size={14} />}
            onAction={async () => {
              const r = await retest.mutateAsync(connection.name);
              onTested(connection.name, r.ok);
              toastStore.getState().show(r.message, r.ok ? "success" : "info");
            }}
            errorMessage="Retest failed"
          >
            Retest
          </ActionButton>
          <Button variant="ghost" size="sm" onClick={onEdit} leftIcon={<IconPencil size={14} />}>
            Edit
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setExpanded((v) => !v)}
            leftIcon={expanded ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />}
          >
            <IconHistory size={13} style={{ marginRight: 4 }} />
            Executions
          </Button>
          <ActionButton
            variant="ghost"
            size="sm"
            leftIcon={<IconTrash size={14} />}
            confirm={{
              title: `Delete connection ${connection.name}?`,
              description:
                "Any ingestion node referencing it will fail until the connection is recreated with the same name.",
              tone: "danger",
              confirmLabel: "Delete connection",
            }}
            onAction={() => del.mutateAsync(connection.name)}
            successMessage="Connection deleted"
            errorMessage="Could not delete connection"
          >
            Delete
          </ActionButton>
        </div>
      </div>
      {expanded && <ConnectionUsagePanel name={connection.name} />}
    </div>
  );
}

export default function IngestionPage({ header }: { header?: SectionHeader } = {}) {
  const { data, isLoading, isError, refetch } = useConnections();
  const connections = data?.connections ?? [];
  const [modal, setModal] = useState<
    | { kind: "create" }
    | { kind: "edit"; connection: ConnectionInfo }
    | { kind: "use"; connection: ConnectionInfo }
    | null
  >(null);
  const [testStates, setTestStates] = useState<Record<string, TestState>>({});

  const recordTest = (name: string, ok: boolean) =>
    setTestStates((s) => ({ ...s, [name]: { ok, at: Date.now() } }));

  return (
    <PageContainer>
      <PageHeader
        title={header?.title ?? "Connections"}
        description={header?.description ?? "The databases your ingestion nodes read from."}
        tabs={header?.tabs}
        actions={
          <Button
            variant="primary"
            size="sm"
            onClick={() => setModal({ kind: "create" })}
            leftIcon={<IconPlus size={15} />}
          >
            New connection
          </Button>
        }
      />

      <Panel>

        {isLoading && (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <Skeleton variant="block" height="48px" />
            <Skeleton variant="block" height="48px" />
          </div>
        )}

        {/* A failed fetch must not read as "you have nothing configured yet" —
            it used to fall straight through to the empty state below. */}
        {!isLoading && isError && (
          <EmptyState
            icon={IconAlertTriangle}
            title="Couldn't load connections"
            description="Check that the API is reachable and try again."
            action={
              <Button variant="ghost" size="sm" onClick={() => refetch()}>
                Refresh
              </Button>
            }
          />
        )}

        {!isLoading && !isError && connections.length === 0 && (
          <EmptyState
            icon={IconDatabaseImport}
            title="No connections yet"
            description="Register a database connection, then create declarative ingestion nodes from it — no Python needed."
            action={
              <Button variant="ghost" size="sm" onClick={() => setModal({ kind: "create" })}>
                <IconPlus size={14} /> Add your first connection
              </Button>
            }
          />
        )}

        {connections.map((c) => (
          <ConnectionRow
            key={c.name}
            connection={c}
            testState={testStates[c.name]}
            onTested={recordTest}
            onEdit={() => setModal({ kind: "edit", connection: c })}
            onUseInPipeline={() => setModal({ kind: "use", connection: c })}
          />
        ))}
      </Panel>

      {modal?.kind === "create" && (
        <ConnectionModal
          onClose={() => setModal(null)}
          onSaved={(r) => {
            if (r.tested && r.ok != null) recordTest(r.name, r.ok);
          }}
        />
      )}
      {modal?.kind === "edit" && (
        <ConnectionModal
          existing={modal.connection}
          onClose={() => setModal(null)}
          onSaved={(r) => {
            if (r.tested && r.ok != null) recordTest(r.name, r.ok);
          }}
        />
      )}
      {modal?.kind === "use" && (
        <UseInPipelineModal connectionName={modal.connection.name} onClose={() => setModal(null)} />
      )}
    </PageContainer>
  );
}
