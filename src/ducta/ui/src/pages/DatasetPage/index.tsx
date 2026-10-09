import { Link, useParams } from "react-router-dom";
import { IconDatabaseOff } from "@tabler/icons-react";
import { useProjectDatasets, type ProjectDataset } from "../../api/queries";
import { useQualitySummary } from "../../api/qualityApi";
import { EmptyState, EntityChip, PageContainer, PageHeader, Skeleton, Sparkline } from "../../components/ui";
import { KeyValues } from "../../components/Pipeline/Focus/parts";
import { DataPreview } from "../../components/Pipeline/Focus/DataPreview";
import { useSourceStore } from "../../store/workspace";
import { datasetLineage } from "../../utils/datasetLineage";
import { routes } from "../../utils/routes";
import "./DatasetPage.css";

const text = (v: unknown) => (v == null ? null : Array.isArray(v) ? v.join(", ") : String(v));

/** Facts for a dataset's hover card. */
export function datasetCard(d: ProjectDataset | undefined): [string, string | null | undefined][] {
  if (!d) return [];
  return [
    ["Format", d.format],
    ["Layer", d.layer],
    ["Owner", text(d.metadata?.owner)],
    ["Written by", d.producers.map((p) => p.node).join(", ") || "— a source"],
  ];
}

/**
 * A dataset's own page: what it is and who answers for it, who writes and
 * reads it, where its data comes from and what a change to it would reach —
 * across every pipeline of the project — a look at its rows, and how its
 * quality has been trending.
 */
export function DatasetPage() {
  const { projectId = "", dataset = "" } = useParams<{ projectId: string; dataset: string }>();
  const activeEnv = useSourceStore((s) => s.activeEnv) || "base";
  const env = activeEnv === "base" ? "dev" : activeEnv;
  const { data, isLoading } = useProjectDatasets(projectId);
  const { data: quality } = useQualitySummary(env, undefined, projectId);
  const entry = data?.datasets.find((d) => d.name === dataset);
  const byName = new Map((data?.datasets ?? []).map((d) => [d.name, d]));
  const meta = entry?.metadata ?? {};
  const pii = Array.isArray(meta.pii) ? (meta.pii as string[]) : [];
  const tags = Array.isArray(meta.tags) ? (meta.tags as string[]) : [];
  const trend = (quality ?? []).find((q) => q.dataset === dataset);

  const chip = (name: string) => (
    <EntityChip key={name} kind="dataset" name={name} to={routes.dataset(projectId, name)} card={datasetCard(byName.get(name))} />
  );

  return (
    <PageContainer>
      <PageHeader
        title={dataset}
        description={entry?.description ?? "Dataset"}
        backTo={routes.project(projectId)}
        backLabel="Project"
      />
      {isLoading ? (
        <Skeleton variant="block" height="160px" />
      ) : !entry ? (
        <EmptyState
          icon={IconDatabaseOff}
          title="Not in this project"
          description={`No node reads or writes “${dataset}”, and the catalog does not declare it.`}
        />
      ) : (
        <>
          {(pii.length > 0 || tags.length > 0 || meta.owner != null || meta.sla != null) && (
            <p className="dataset-page__badges">
              {meta.owner != null && <span className="dataset-page__badge">owner {text(meta.owner)}</span>}
              {meta.sla != null && <span className="dataset-page__badge">SLA {text(meta.sla)}</span>}
              {meta.criticality != null && <span className="dataset-page__badge">{text(meta.criticality)} criticality</span>}
              {pii.length > 0 && (
                <span className="dataset-page__badge is-pii" title={`Personal data in: ${pii.join(", ")}`}>
                  PII · {pii.length} column{pii.length === 1 ? "" : "s"}
                </span>
              )}
              {tags.map((t) => <span key={t} className="dataset-page__badge is-tag">#{t}</span>)}
              {typeof meta.docs === "string" && <a className="dataset-page__badge" href={meta.docs} target="_blank" rel="noreferrer">docs ↗</a>}
            </p>
          )}

          <div className="dataset-page">
            <section className="dataset-page__card" aria-labelledby="ds-def">
              <h2 id="ds-def" className="dataset-page__h">Definition</h2>
              <KeyValues
                rows={[
                  { label: "Layer", value: entry.layer ?? null, absent: "—" },
                  { label: "Format", value: entry.format ?? null },
                  { label: "Path", value: entry.path ?? null, plain: true },
                  { label: "Write mode", value: entry.write_mode ?? null, absent: "—" },
                  { label: "Declared in", value: entry.declared_in.join(", ") || null, plain: true },
                  ...(pii.length ? [{ label: "PII columns", value: pii.join(", "), plain: true }] : []),
                ]}
              />
              {trend && trend.trend.length > 0 && (
                <div className="dataset-page__quality">
                  <span className="dataset-page__meta">Quality score, last {trend.trend.length} runs in {env}</span>
                  <Sparkline
                    label={`Quality score trend of ${dataset}`}
                    points={trend.trend.map((s) => ({ seconds: s ?? 0, status: s != null && s >= 1 ? "success" : "failed" }))}
                    width={160}
                  />
                  <Link to={routes.section(projectId, "quality")} className="dataset-page__meta">all checks →</Link>
                </div>
              )}
            </section>
            <section className="dataset-page__card" aria-labelledby="ds-prod">
              <h2 id="ds-prod" className="dataset-page__h">Written by</h2>
              <EndpointList projectId={projectId} endpoints={entry.producers} empty="No node writes it — it is a source." />
            </section>
            <section className="dataset-page__card" aria-labelledby="ds-cons">
              <h2 id="ds-cons" className="dataset-page__h">Read by</h2>
              <EndpointList projectId={projectId} endpoints={entry.consumers} empty="No node reads it." />
            </section>
          </div>

          <Lineage datasets={data!.datasets} name={dataset} chip={chip} />

          <section className="dataset-page__section" aria-labelledby="ds-preview">
            <h2 id="ds-preview" className="dataset-page__h">Data in {env}</h2>
            <DataPreview projectId={projectId} inputs={[]} outputs={[dataset]} env={env} />
          </section>
        </>
      )}
    </PageContainer>
  );
}

function Lineage({ datasets, name, chip }: { datasets: ProjectDataset[]; name: string; chip: (n: string) => React.ReactNode }) {
  const lineage = datasetLineage(datasets, name, 3);
  const { impact } = lineage;
  return (
    <section className="dataset-page__section" aria-labelledby="ds-lineage">
      <h2 id="ds-lineage" className="dataset-page__h">Lineage, across pipelines</h2>
      <p className="dataset-page__impact" role="note">
        {impact.nodes.length === 0
          ? "Nothing reads from it downstream — a change here reaches no other dataset."
          : `A change here reaches ${impact.datasets.length} dataset${impact.datasets.length === 1 ? "" : "s"} through ${impact.nodes.length} node${impact.nodes.length === 1 ? "" : "s"} in ${impact.pipelines.length} pipeline${impact.pipelines.length === 1 ? "" : "s"}: ${impact.pipelines.join(", ")}.`}
      </p>
      <div className="dataset-lineage">
        <LineageSide label="Comes from" levels={[...lineage.upstream].reverse()} chip={chip} empty="A source — nothing upstream." />
        <div className="dataset-lineage__self" aria-current="true">{name}</div>
        <LineageSide label="Feeds" levels={lineage.downstream} chip={chip} empty="Nothing downstream." />
      </div>
    </section>
  );
}

function LineageSide({
  label,
  levels,
  chip,
  empty,
}: {
  label: string;
  levels: { hop: number; datasets: string[] }[];
  chip: (n: string) => React.ReactNode;
  empty: string;
}) {
  return (
    <div className="dataset-lineage__side" aria-label={label}>
      {levels.length === 0 ? (
        <p className="dataset-page__empty">{empty}</p>
      ) : (
        levels.map((l) => (
          <div key={l.hop} className="dataset-lineage__level">
            <span className="dataset-lineage__hop">{l.hop === 1 ? "direct" : `${l.hop} hops`}</span>
            <div className="dataset-lineage__chips">{l.datasets.map(chip)}</div>
          </div>
        ))
      )}
    </div>
  );
}

function EndpointList({
  projectId,
  endpoints,
  empty,
}: {
  projectId: string;
  endpoints: { node: string; pipeline?: string | null }[];
  empty: string;
}) {
  if (endpoints.length === 0) return <p className="dataset-page__empty">{empty}</p>;
  return (
    <ul className="dataset-page__list">
      {endpoints.map((e) => (
        <li key={`${e.pipeline}/${e.node}`}>
          {e.pipeline ? (
            <EntityChip kind="node" name={e.node} to={routes.node(projectId, e.pipeline, e.node)} card={[["Pipeline", e.pipeline]]} />
          ) : (
            <span className="dataset-page__mono">{e.node}</span>
          )}
        </li>
      ))}
    </ul>
  );
}
