import { useId } from "react";
import { Link } from "react-router-dom";
import { IconDatabase, IconGitBranch, IconHexagon } from "@tabler/icons-react";

export type EntityKind = "dataset" | "node" | "pipeline";

const ICON = { dataset: IconDatabase, node: IconHexagon, pipeline: IconGitBranch };

/**
 * A dataset, node or pipeline named anywhere in the UI: one look, one click
 * to its page, and — on hover or keyboard focus — a card with what it is, so
 * a name in a list can be understood without leaving the list.
 */
export function EntityChip({
  kind,
  name,
  to,
  card,
}: {
  kind: EntityKind;
  name: string;
  to: string;
  /** Facts for the hover card; rows without a value are left out. */
  card?: [label: string, value: string | null | undefined][];
}) {
  const id = useId();
  const Icon = ICON[kind];
  const rows = (card ?? []).filter(([, v]) => v != null && v !== "");
  return (
    <span className="entity-chip" data-kind={kind}>
      <Link to={to} className="entity-chip__link" aria-describedby={rows.length ? id : undefined}>
        <Icon size={13} aria-hidden="true" />
        <span className="entity-chip__name">{name}</span>
      </Link>
      {rows.length > 0 && (
        <span role="tooltip" id={id} className="entity-chip__card">
          <span className="entity-chip__kind">{kind}</span>
          {rows.map(([label, value]) => (
            <span key={label} className="entity-chip__row">
              <span className="entity-chip__label">{label}</span> {value}
            </span>
          ))}
        </span>
      )}
    </span>
  );
}
