import "./Skeleton.css";

/**
 * Content-shaped placeholder for data that is still loading.
 *
 * Most of the app showed a centred "Loading…" string instead. A placeholder
 * that occupies the shape of the eventual content makes the same wait read as
 * faster, and stops the layout jumping when the data lands — which matters here
 * because the slow screens are the table-heavy ones.
 *
 * The shimmer is suppressed under `prefers-reduced-motion`.
 */
export interface SkeletonProps {
  /** Any CSS width: "100%", "8ch", "120px". */
  width?: string;
  height?: string;
  /** `text` rounds to the type's cap height; `block` uses the surface radius. */
  variant?: "text" | "block" | "circle";
  className?: string;
}

export function Skeleton({
  width = "100%",
  height,
  variant = "text",
  className = "",
}: Readonly<SkeletonProps>) {
  return (
    <span
      className={`tui-skeleton tui-skeleton--${variant} ${className}`.trim()}
      style={{ width, ...(height ? { height } : {}) }}
      aria-hidden="true"
    />
  );
}

/**
 * A block of skeleton lines, for a paragraph or a list.
 *
 * The last line is short so the block reads as text rather than as a slab.
 */
export function SkeletonText({ lines = 3, width = "100%" }: Readonly<{ lines?: number; width?: string }>) {
  return (
    <span className="tui-skeleton-stack">
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} width={i === lines - 1 ? "60%" : width} />
      ))}
    </span>
  );
}
