import { colors } from "../../theme/tokens";

export function HighlightedText({
  text,
  query,
  renderer = (t) => <>{t}</>,
}: {
  text: string;
  query: string;
  renderer?: (t: string) => React.ReactNode;
}) {
  if (!query) return <>{renderer(text)}</>;
  const lower = text.toLowerCase();
  const q     = query.toLowerCase();
  const parts: React.ReactNode[] = [];
  let cursor = 0;
  let idx: number;
  while ((idx = lower.indexOf(q, cursor)) !== -1) {
    if (idx > cursor) parts.push(renderer(text.slice(cursor, idx)));
    parts.push(
      <mark
        key={idx}
        style={{ background: colors.amberA30, color: colors.text, borderRadius: 2, padding: "0 1px" }}
      >
        {renderer(text.slice(idx, idx + query.length))}
      </mark>
    );
    cursor = idx + query.length;
  }
  if (cursor < text.length) parts.push(renderer(text.slice(cursor)));
  return <>{parts}</>;
}
