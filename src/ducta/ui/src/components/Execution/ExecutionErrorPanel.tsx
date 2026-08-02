import { IconAlertTriangle, IconX, IconChevronDown } from "@tabler/icons-react";
import { Button } from "../ui";
import { useExecutionErrors, type ExecutionErrorDetail } from "../../api/queries";

const CATEGORY_LABELS: Record<string, string> = {
  temporary: "Temporary",
  permanent: "Permanent",
  resource: "Resource",
  configuration: "Configuration",
  timeout: "Timeout",
  cancelled: "Cancelled",
  unknown: "Unknown",
};

const STRATEGY_LABELS: Record<string, string> = {
  retry: "Retry",
  skip_node: "Skip node",
  fallback: "Use fallback",
  abort: "Abort",
  manual: "Manual intervention",
};

/** Category → (fg, bg) from the semantic status tokens, never color alone. */
function categoryColors(category: string): { fg: string; bg: string } {
  switch (category) {
    case "permanent":
    case "configuration":
      return { fg: "var(--status-failed-fg)", bg: "var(--status-failed-bg)" };
    case "temporary":
    case "resource":
    case "timeout":
      return { fg: "var(--status-warning-fg)", bg: "var(--status-warning-bg)" };
    default:
      return { fg: "var(--status-pending-fg)", bg: "var(--status-pending-bg)" };
  }
}

function CategoryBadge({ category }: { category: string }) {
  const { fg, bg } = categoryColors(category);
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "1px 8px",
        borderRadius: "var(--radius-pill)",
        background: bg,
        border: `1px solid color-mix(in srgb, ${fg} 32%, transparent)`,
        color: fg,
        fontSize: "var(--text-xs)",
        fontWeight: "var(--weight-semibold)",
        textTransform: "uppercase",
        letterSpacing: "0.04em",
        fontFamily: "var(--font-mono)",
      }}
    >
      {CATEGORY_LABELS[category] ?? category}
    </span>
  );
}

function ErrorBlock({ error, index }: { error: ExecutionErrorDetail; index: number }) {
  const { fg, bg } = categoryColors(error.category);
  const tracebackLines = error.traceback ? error.traceback.trim().split("\n").length : 0;
  return (
    <div
      style={{
        border: "1px solid var(--status-failed-border)",
        borderRadius: "var(--radius-sm)",
        overflow: "hidden",
        marginTop: index === 0 ? 0 : "var(--space-2)",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "var(--space-2)",
          padding: "var(--space-2) var(--space-3)",
          background: bg,
          flexWrap: "wrap",
        }}
      >
        <CategoryBadge category={error.category} />
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: "var(--text-xs)",
            color: "var(--text)",
            fontWeight: "var(--weight-semibold)",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            maxWidth: "55%",
          }}
        >
          {error.error_type}
          {error.node_id ? ` · ${error.node_id}` : ""}
        </span>
        {error.attempt > 1 && (
          <span
            style={{
              fontSize: "var(--text-xs)",
              color: "var(--text-muted)",
              fontFamily: "var(--font-mono)",
            }}
          >
            attempt {error.attempt}
          </span>
        )}
      </div>

      <div style={{ padding: "var(--space-2) var(--space-3)" }}>
        <p
          style={{
            margin: "0 0 var(--space-1)",
            fontSize: "var(--text-sm)",
            color: "var(--status-failed-fg)",
            lineHeight: 1.45,
            wordBreak: "break-word",
          }}
        >
          {error.message}
        </p>

        {error.recovery_plan && (
          <p
            style={{
              margin: "0 0 var(--space-2)",
              fontSize: "var(--text-xs)",
              color: "var(--text-muted)",
            }}
          >
            <span style={{ fontWeight: "var(--weight-semibold)", color: fg }}>
              {STRATEGY_LABELS[error.recovery_plan.primary] ?? error.recovery_plan.primary}
              {error.recovery_plan.retry_delay
                ? ` in ${error.recovery_plan.retry_delay}s`
                : ""}
            </span>
            {error.recovery_plan.notes ? ` — ${error.recovery_plan.notes}` : ""}
          </p>
        )}

        {error.traceback && (
          <details>
            <summary
              style={{
                cursor: "pointer",
                display: "inline-flex",
                alignItems: "center",
                gap: 4,
                fontSize: "var(--text-xs)",
                color: "var(--text-muted)",
                fontWeight: "var(--weight-medium)",
              }}
            >
              <IconChevronDown size={12} aria-hidden />
              Full traceback ({tracebackLines} line{tracebackLines !== 1 ? "s" : ""})
            </summary>
            <pre
              style={{
                margin: "var(--space-2) 0 0",
                fontFamily: "var(--font-mono)",
                fontSize: "var(--text-xs)",
                lineHeight: 1.5,
                color: "var(--text)",
                background: "var(--bg)",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius-sm)",
                padding: "var(--space-2) var(--space-3)",
                maxHeight: 260,
                overflowY: "auto",
                whiteSpace: "pre",
                wordBreak: "normal",
              }}
            >
              {error.traceback}
            </pre>
          </details>
        )}
      </div>
    </div>
  );
}

export function ExecutionErrorPanel({
  errorMsg,
  onDismiss,
  executionId,
}: {
  errorMsg: string;
  onDismiss: () => void;
  /** When provided, the panel enriches the message with categorized details
   * (type, category, recovery suggestion, full traceback) from the API. */
  executionId?: string | null;
}) {
  const { data: errorData, isLoading } = useExecutionErrors(executionId);

  const errors: ExecutionErrorDetail[] = errorData?.errors ?? [];
  const showDetails = !isLoading && errors.length > 0;

  return (
    <div
      role="alert"
      style={{
        position: "absolute",
        top: "calc(100% + 8px)",
        left: 0,
        right: 0,
        zIndex: 100,
        padding: "var(--space-3) var(--space-4)",
        backgroundColor: "var(--status-failed-bg)",
        border: "1px solid var(--status-failed-border)",
        borderRadius: "var(--radius)",
        boxShadow: "var(--shadow-md)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)", marginBottom: "var(--space-2)" }}>
        <span
          style={{
            color: "var(--status-failed-fg)",
            fontSize: "var(--text-sm)",
            fontWeight: "var(--weight-semibold)",
            display: "inline-flex",
            alignItems: "center",
            gap: "var(--space-1)",
          }}
        >
          <IconAlertTriangle size={15} aria-hidden /> Execution failed
          {showDetails && errorData!.error_count > 1 && (
            <span style={{ fontWeight: "var(--weight-regular)", color: "var(--text-muted)" }}>
              · {errorData!.error_count} error{errorData!.error_count !== 1 ? "s" : ""}
            </span>
          )}
        </span>
        <Button
          variant="ghost"
          size="sm"
          iconOnly
          onClick={onDismiss}
          aria-label="Dismiss error"
          title="Dismiss error"
          style={{ marginLeft: "auto" }}
          leftIcon={<IconX size={15} />}
        />
      </div>

      {showDetails ? (
        errors.map((err, i) => <ErrorBlock key={`${err.timestamp}-${i}`} error={err} index={i} />)
      ) : (
        <pre
          style={{
            margin: 0,
            fontFamily: "var(--font-mono)",
            fontSize: "var(--text-xs)",
            color: "var(--status-failed-fg)",
            background: "var(--bg)",
            border: "1px solid var(--status-failed-border)",
            borderRadius: "var(--radius-sm)",
            padding: "var(--space-2) var(--space-3)",
            maxHeight: 160,
            overflowY: "auto",
            whiteSpace: "pre-wrap",
            wordWrap: "break-word",
          }}
        >
          {isLoading ? "Loading error details…" : errorMsg}
        </pre>
      )}
    </div>
  );
}
