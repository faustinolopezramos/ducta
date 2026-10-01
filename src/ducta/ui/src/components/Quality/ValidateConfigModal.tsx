import { useMemo, useState, type CSSProperties } from "react";
import { Modal } from "../ui/Modal";
import { Button } from "../ui/Button";
import { StatusBadge } from "../ui/StatusBadge";
import { Field } from "../ui/Field";
import "../ui/Input.css"; // .input-field
import { colors } from "../../theme/tokens";
import { useNodes } from "../../api/queries";
import { useSourceStore } from "../../store/workspace";
import { useValidateQualityConfig } from "../../api/qualityApi";
import { IconShieldCheck } from "@tabler/icons-react";

// Section headings for lists (Errors/Warnings), not form-field labels — kept
// distinct from `Field` on purpose.
const label: CSSProperties = {
  display: "block",
  fontSize: 11,
  fontWeight: 600,
  color: colors.textMuted,
  textTransform: "uppercase",
  letterSpacing: "0.04em",
  marginBottom: 4,
};

/**
 * Validate a node's quality config by picking the node from the workspace.
 * The server reads the node's project as the active environment sees it, so
 * profiles resolve against that environment's settings.
 */
export function ValidateConfigModal({ onClose }: { onClose: () => void }) {
  const activeEnv = useSourceStore((s) => s.activeEnv) ?? "base";
  const { data: nodesData, isLoading: nodesLoading } = useNodes();
  const validate = useValidateQualityConfig();

  const [nodeName, setNodeName] = useState("");

  const nodeNames = useMemo(
    () => Object.keys(nodesData?.nodes ?? {}).sort(),
    [nodesData]
  );

  const submit = () => {
    validate.mutate({ node_name: nodeName, env: activeEnv });
  };

  return (
    <Modal title="Validate node quality config" onClose={onClose} width={560}>
      <div style={{ display: "grid", gap: 14 }}>
        <Field label="Node">
          <select
            className="input-field"
            value={nodeName}
            onChange={(e) => setNodeName(e.target.value)}
            disabled={nodesLoading}
          >
            <option value="">{nodesLoading ? "Loading nodes…" : "Select a node…"}</option>
            {nodeNames.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </Field>

        <div style={{ fontSize: 11, color: colors.textMuted, fontFamily: "var(--font-mono)" }}>
          {`Checks the node as the ${activeEnv} environment configures it`}
        </div>

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <Button variant="ghost" size="sm" onClick={onClose}>
            Close
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={submit}
            disabled={validate.isPending || !nodeName}
            leftIcon={<IconShieldCheck size={15} />}
          >
            {validate.isPending ? "Validating…" : "Validate"}
          </Button>
        </div>

        {validate.data && (
          <div style={{ borderTop: `1px solid ${colors.border}`, paddingTop: 12 }}>
            <StatusBadge
              status={validate.data.valid ? "success" : "failed"}
              label={validate.data.valid ? "Valid" : "Invalid"}
            />
            {validate.data.errors.length > 0 && (
              <div style={{ marginTop: 10 }}>
                <span style={label}>Errors</span>
                <ul style={{ margin: "4px 0 0", paddingLeft: 18, fontSize: 12, color: colors.danger }}>
                  {validate.data.errors.map((e, i) => (
                    <li key={i}>{e}</li>
                  ))}
                </ul>
              </div>
            )}
            {validate.data.warnings.length > 0 && (
              <div style={{ marginTop: 10 }}>
                <span style={label}>Warnings</span>
                <ul style={{ margin: "4px 0 0", paddingLeft: 18, fontSize: 12, color: colors.warning }}>
                  {validate.data.warnings.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>
    </Modal>
  );
}
