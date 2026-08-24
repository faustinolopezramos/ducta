import { useMemo, useState, type CSSProperties } from "react";
import { Modal } from "../ui/Modal";
import { Button } from "../ui/Button";
import { StatusBadge } from "../ui/StatusBadge";
import { Field } from "../ui/Field";
import "../ui/Input.css"; // .input-field
import { colors } from "../../theme/tokens";
import { useNodes, useWorkspaceConfigs } from "../../api/queries";
import { useSourceStore } from "../../store/workspace";
import { useValidateQualityConfig } from "../../api/qualityApi";
import { FilePickerField } from "./FilePickerField";
import { IconShieldCheck, IconChevronDown, IconChevronRight } from "@tabler/icons-react";

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
 * Validate a node's quality config by picking the node from the workspace —
 * the nodes/global config paths are resolved from the environment's config
 * set automatically. Manual path overrides stay available under "Advanced".
 */
export function ValidateConfigModal({ onClose }: { onClose: () => void }) {
  const activeEnv = useSourceStore((s) => s.activeEnv) ?? "base";
  const { data: nodesData, isLoading: nodesLoading } = useNodes();
  const { data: configs } = useWorkspaceConfigs(activeEnv);
  const validate = useValidateQualityConfig();

  const [nodeName, setNodeName] = useState("");
  const [advanced, setAdvanced] = useState(false);
  const [manualConfigPath, setManualConfigPath] = useState("");
  const [manualGlobalPath, setManualGlobalPath] = useState("");

  const nodeNames = useMemo(
    () => Object.keys(nodesData?.nodes ?? {}).sort(),
    [nodesData]
  );

  const resolvedConfigPath: string =
    (configs?.nodes?.path as string | undefined) ?? "";
  const resolvedGlobalPath: string =
    (configs?.global?.path as string | undefined) ??
    (configs?.global_settings?.path as string | undefined) ??
    "";

  const configPath = advanced && manualConfigPath ? manualConfigPath : resolvedConfigPath;
  const globalPath = advanced && manualGlobalPath ? manualGlobalPath : resolvedGlobalPath;

  const submit = () => {
    validate.mutate({
      node_name: nodeName,
      config_path: configPath,
      global_settings_path: globalPath || undefined,
    });
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
          {configPath
            ? `Using ${configPath} (${activeEnv})`
            : "No nodes config found for this environment — set the path under Advanced."}
        </div>

        <button
          type="button"
          onClick={() => setAdvanced((a) => !a)}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 4,
            background: "none",
            border: "none",
            padding: 0,
            cursor: "pointer",
            fontSize: 11,
            color: colors.textMuted,
          }}
        >
          {advanced ? <IconChevronDown size={12} /> : <IconChevronRight size={12} />}
          Advanced (manual paths)
        </button>

        {advanced && (
          <div style={{ display: "grid", gap: 10 }}>
            <div>
              <label style={label} htmlFor="validate-config-nodes-path">Nodes config file</label>
              <FilePickerField
                id="validate-config-nodes-path"
                value={manualConfigPath}
                onChange={setManualConfigPath}
                placeholder={resolvedConfigPath || "config/nodes.yaml"}
                extensions={[".toml", ".yaml", ".yml", ".json", ".py"]}
              />
            </div>
            <div>
              <label style={label} htmlFor="validate-config-global-path">Global settings file (profile resolution)</label>
              <FilePickerField
                id="validate-config-global-path"
                value={manualGlobalPath}
                onChange={setManualGlobalPath}
                placeholder={resolvedGlobalPath || "config/global.toml"}
                extensions={[".toml", ".yaml", ".yml", ".json", ".py"]}
              />
            </div>
          </div>
        )}

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <Button variant="ghost" size="sm" onClick={onClose}>
            Close
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={submit}
            disabled={validate.isPending || !nodeName || !configPath}
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
