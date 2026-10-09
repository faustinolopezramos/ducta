/**
 * A setting's value and where it comes from. Set here: shown plainly.
 * Inherited: dimmer, with its origin. Overridden by an environment: ⚑.
 */
/** "pipeline defaults" → "pipeline": the column already says what it is. */
export function shortSource(source: string): string {
  return source.replace(/ defaults?$/, "");
}

export function InheritedValue({
  value,
  source,
  overridden = false,
  showSource = true,
}: {
  value: unknown;
  source: string;
  overridden?: boolean;
  /** Off where the origin repeats a column already labelled. */
  showSource?: boolean;
}) {
  const own = source === "node";
  const text = value == null ? "—" : typeof value === "object" ? JSON.stringify(value) : String(value);
  return (
    <span className={`inherited-value${own ? " is-own" : ""}${overridden ? " is-overridden" : ""}`} title={`From: ${source}`}>
      {overridden && <span className="inherited-value__flag" aria-label="overridden by this environment">⚑ </span>}
      <span className="inherited-value__v">{text}</span>
      {!own && showSource && <span className="inherited-value__source">{shortSource(source)}</span>}
    </span>
  );
}
