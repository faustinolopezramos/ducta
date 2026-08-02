import React, { useState } from "react";
import { Modal } from "../ui/Modal";
import { Button } from "../ui/Button";
import { colors } from "../../theme/tokens";
import { toastStore } from "../../hooks/useModalStack";
import {
  useCreateConnection,
  useTestConnection,
  type ConnectionCreateVars,
  type ConnectionInfo,
} from "../../api/ingestionApi";
import { IconPlugConnected, IconDeviceFloppy } from "@tabler/icons-react";

export const DB_TYPES = ["postgresql", "mysql", "mariadb", "sqlserver", "oracle", "snowflake"] as const;
export const DEFAULT_PORTS: Record<string, number> = {
  postgresql: 5432,
  mysql: 3306,
  mariadb: 3306,
  sqlserver: 1433,
  oracle: 1521,
  snowflake: 443,
};

const label: React.CSSProperties = {
  display: "block",
  fontSize: 11,
  fontWeight: 600,
  color: colors.textMuted,
  textTransform: "uppercase",
  letterSpacing: "0.04em",
  marginBottom: 4,
};

const input: React.CSSProperties = {
  width: "100%",
  padding: "6px 8px",
  borderRadius: 6,
  border: `1px solid ${colors.border}`,
  background: colors.bg,
  color: colors.text,
  fontFamily: "var(--font-mono)",
  fontSize: 12,
  outline: "none",
};

const emptyForm: ConnectionCreateVars = {
  name: "",
  type: "postgresql",
  host: "localhost",
  port: 5432,
  database: "",
  username: "",
  password: "",
  description: "",
  overwrite: false,
};

/**
 * Create or edit a database connection. Editing prefills everything except
 * the password (credentials are write-only: stored in the workspace .env and
 * never returned by the API) and saves with overwrite.
 */
export function ConnectionModal({
  existing,
  onClose,
  onSaved,
}: {
  /** When set, the modal edits this connection instead of creating one. */
  existing?: ConnectionInfo;
  onClose: () => void;
  onSaved?: (result: { name: string; tested: boolean; ok?: boolean }) => void;
}) {
  const editing = Boolean(existing);
  const [form, setForm] = useState<ConnectionCreateVars>(
    existing
      ? {
          ...emptyForm,
          name: existing.name,
          type: existing.type ?? "postgresql",
          host: existing.host ?? "localhost",
          port: existing.port ?? DEFAULT_PORTS[existing.type ?? "postgresql"] ?? 5432,
          database: existing.database ?? "",
          description: existing.description ?? "",
          overwrite: true,
        }
      : emptyForm
  );
  const [lastTest, setLastTest] = useState<{ ok: boolean } | null>(null);
  const create = useCreateConnection();
  const test = useTestConnection();

  const set = <K extends keyof ConnectionCreateVars>(k: K, v: ConnectionCreateVars[K]) =>
    setForm((f) => ({ ...f, [k]: v }));

  const onTypeChange = (t: string) =>
    setForm((f) => ({ ...f, type: t, port: DEFAULT_PORTS[t] ?? f.port }));

  const doTest = () =>
    test.mutate(
      {
        type: form.type,
        host: form.host,
        port: form.port,
        database: form.database,
        username: form.username,
        password: form.password,
      },
      {
        onSuccess: (r) => {
          setLastTest({ ok: r.ok });
          toastStore.getState().show(r.message, r.ok ? "success" : "info");
        },
      }
    );

  const doSave = () => {
    if (!form.name || !form.database || !form.username || !form.password) {
      toastStore.getState().show("Name, database, username and password are required", "error");
      return;
    }
    create.mutate(form, {
      onSuccess: () => {
        toastStore.getState().show(`Connection '${form.name}' saved`, "success");
        onSaved?.({ name: form.name, tested: lastTest != null, ok: lastTest?.ok });
        onClose();
      },
    });
  };

  const [step, setStep] = useState<1 | 2>(1);

  return (
    <Modal title={editing ? `Edit connection · ${existing!.name}` : "New connection"} onClose={onClose} width={600}>
      {/* Stepper Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          marginBottom: 16,
          padding: "8px 12px",
          background: "var(--surface)",
          border: "1px solid var(--border)",
          borderRadius: 6,
          fontSize: 12,
          fontWeight: 600,
        }}
      >
        <div
          onClick={() => setStep(1)}
          style={{
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            gap: 6,
            color: step === 1 ? "var(--primary)" : "var(--text-muted)",
          }}
        >
          <span
            style={{
              width: 18,
              height: 18,
              borderRadius: "50%",
              background: step === 1 ? "var(--primary)" : "var(--border)",
              color: "#fff",
              display: "grid",
              placeItems: "center",
              fontSize: 10,
            }}
          >
            1
          </span>
          1. Connection & Credentials
        </div>
        <span style={{ color: "var(--border)" }}>→</span>
        <div
          onClick={() => setStep(2)}
          style={{
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            gap: 6,
            color: step === 2 ? "var(--primary)" : "var(--text-muted)",
          }}
        >
          <span
            style={{
              width: 18,
              height: 18,
              borderRadius: "50%",
              background: step === 2 ? "var(--primary)" : "var(--border)",
              color: "#fff",
              display: "grid",
              placeItems: "center",
              fontSize: 10,
            }}
          >
            2
          </span>
          2. Test & Save
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <div>
          <span style={label}>Name</span>
          <input
            style={{ ...input, opacity: editing ? 0.6 : 1 }}
            value={form.name}
            onChange={(e) => set("name", e.target.value)}
            placeholder="sales_db"
            disabled={editing}
          />
        </div>
        <div>
          <span style={label}>Type</span>
          <select style={input} value={form.type} onChange={(e) => onTypeChange(e.target.value)}>
            {DB_TYPES.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </div>
        <div>
          <span style={label}>Host</span>
          <input style={input} value={form.host} onChange={(e) => set("host", e.target.value)} />
        </div>
        <div>
          <span style={label}>Port</span>
          <input style={input} type="number" value={form.port} onChange={(e) => set("port", Number(e.target.value))} />
        </div>
        <div>
          <span style={label}>Database</span>
          <input style={input} value={form.database} onChange={(e) => set("database", e.target.value)} />
        </div>
        <div>
          <span style={label}>Username</span>
          <input style={input} value={form.username} onChange={(e) => set("username", e.target.value)} />
        </div>
        <div>
          <span style={label}>{editing ? "Password (re-enter to save)" : "Password"}</span>
          <input style={input} type="password" value={form.password} onChange={(e) => set("password", e.target.value)} />
        </div>
        <div>
          <span style={label}>Description (optional)</span>
          <input style={input} value={form.description ?? ""} onChange={(e) => set("description", e.target.value)} />
        </div>
      </div>
      <p style={{ fontSize: 11, color: colors.textMuted, marginTop: 12 }}>
        Credentials are written to the workspace <code>.env</code> (force-added to{" "}
        <code>.gitignore</code>) and never returned by the API.
      </p>
      <div style={{ display: "flex", gap: 8, marginTop: 8, justifyContent: "flex-end" }}>
        <Button variant="ghost" size="sm" onClick={onClose}>
          Cancel
        </Button>
        <Button
          variant="secondary"
          size="sm"
          onClick={doTest}
          disabled={test.isPending || !form.database || !form.username || !form.password}
          leftIcon={<IconPlugConnected size={15} />}
        >
          {test.isPending ? "Testing…" : "Test"}
        </Button>
        <Button
          variant="primary"
          size="sm"
          onClick={doSave}
          disabled={create.isPending}
          leftIcon={<IconDeviceFloppy size={15} />}
        >
          {create.isPending ? "Saving…" : editing ? "Save changes" : "Save connection"}
        </Button>
      </div>
    </Modal>
  );
}
