import { colors, styles } from "../../theme/tokens";
import { useQueueStatus } from "../../api/queries";

export function QueueIndicator() {
  const { data } = useQueueStatus();
  if (!data) return null;
  const { running, queued, max_concurrent } = data;
  if (running === 0 && queued === 0) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      aria-label={`${running} of ${max_concurrent} executions running${queued > 0 ? `, ${queued} queued` : ""}`}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 8,
        padding: "4px 10px",
        borderRadius: 6,
        background: colors.surface,
        border: `1px solid ${colors.border}`,
        ...styles.fontMono,
        fontSize: 11,
        color: colors.textMuted,
      }}
    >
      <span style={{ color: running > 0 ? colors.accent : colors.textMuted }}>
        {running}/{max_concurrent} running
      </span>
      {queued > 0 && (
        <>
          <span style={{ color: colors.border }}>·</span>
          <span style={{ color: colors.amber }}>{queued} queued</span>
        </>
      )}
    </div>
  );
}
