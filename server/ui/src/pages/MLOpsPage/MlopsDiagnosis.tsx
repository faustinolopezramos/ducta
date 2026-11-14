import type { ComponentType } from "react";
import { colors, styles } from "../../theme/tokens";
import { EmptyState } from "../../components/ui/EmptyState";
import { DataTable, type DataTableColumn } from "../../components/ui/DataTable";
import { formatDate } from "../../utils/formatDate";
import type { MlopsStatus, UnregisteredModel } from "../../api/mlopsApi";

const COLUMNS: DataTableColumn<UnregisteredModel>[] = [
  { key: "name", header: "Model", sortable: true, sortValue: (m) => m.name, cell: (m) => m.name },
  { key: "versions", header: "Versions", align: "right", mono: true, cell: (m) => m.versions },
  {
    key: "updated_at",
    header: "Last written",
    cell: (m) => formatDate(m.updated_at),
  },
  {
    key: "latest",
    header: "Latest file",
    mono: true,
    cell: (m) => <span title={m.latest ?? undefined}>{m.latest?.split("/").slice(-3).join("/") ?? "—"}</span>,
  },
];

/** Table of models that were trained and saved but never registered. */
export function UnregisteredModelsTable({ models }: Readonly<{ models: UnregisteredModel[] }>) {
  if (models.length === 0) return null;
  return (
    <div style={{ marginTop: 24 }}>
      <h3
        style={{
          ...styles.fontSans,
          fontSize: "var(--text-xs)",
          fontWeight: 600,
          color: colors.textMuted,
          textTransform: "uppercase",
          letterSpacing: "0.06em",
          margin: "0 0 4px",
        }}
      >
        Saved without tracking ({models.length})
      </h3>
      <p style={{ ...styles.fontSans, fontSize: "var(--text-sm)", color: colors.textMuted, margin: "0 0 8px" }}>
        These were found as plain files in the storage path. They can still be served, but have no
        stage, metrics or run history.
      </p>
      <DataTable<UnregisteredModel>
        density="compact"
        columns={COLUMNS}
        rows={models}
        rowKey={(m) => m.name}
      />
    </div>
  );
}

/**
 * The empty state of an MLOps view, saying *why* it is empty instead of a generic
 * "nothing yet": MLOps off in this environment, or on but never run, with the
 * plain-file models that do exist listed underneath.
 */
export function MlopsEmptyState({
  status,
  env,
  what,
  icon,
}: Readonly<{
  status?: MlopsStatus;
  env?: string;
  what: "experiments" | "models";
  icon: ComponentType<any>;
}>) {
  const envLabel = env ? `'${env}'` : "this environment";
  const unregistered = status?.unregistered_models ?? [];
  const noun = what === "experiments" ? "experiments" : "registered models";

  let title = `No ${noun} yet`;
  let description =
    what === "experiments"
      ? "Run this pipeline with mlops_enabled: true and its runs, parameters and metrics appear here."
      : "Run this pipeline with mlops_enabled: true and persist_model registers each trained model here.";

  if (status && !status.mlops_enabled) {
    title = `MLOps tracking is off in ${envLabel}`;
    description =
      "Runs here train and save models but write no experiments or registry entries. " +
      "Pick an environment with mlops_enabled: true, or turn it on for this one.";
  } else if (status && !status.tracking_present && !status.registry_present && unregistered.length > 0) {
    title = `Nothing tracked in ${envLabel} yet`;
    description =
      `MLOps is on in ${envLabel}, but the models found here were saved by runs that did not ` +
      `track — for example runs in an environment with MLOps off. The next run in ${envLabel} will appear here.`;
  }

  return (
    <>
      <EmptyState icon={icon} title={title} description={description} size="sm" />
      <UnregisteredModelsTable models={unregistered} />
    </>
  );
}
