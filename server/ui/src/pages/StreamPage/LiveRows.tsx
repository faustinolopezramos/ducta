import { memo, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { IconPlayerPause, IconPlayerPlay, IconTableOff } from "@tabler/icons-react";
import type { StreamRows } from "../../api/queries/streamRows";
import { SegmentedControl } from "../../components/ui/SegmentedControl";
import { agoText } from "../../utils/streaming";
import { formatCell, rowKeys, type Cell } from "./rowFormat";

const LIMITS = [25, 50, 100] as const;
export type RowLimit = (typeof LIMITS)[number];

type Column = { name: string; type?: string };

/** Arrow/pandas types that hold numbers: their header aligns right, over its figures. */
const NUMERIC = /^(u?int\d*|float\d*|double|decimal|halffloat)/i;

/**
 * The grid itself. Memoised: the page re-renders on every status poll (every 5 s), and the
 * rows only change when a batch lands — so the cells are formatted once per read, not once per
 * poll. `rows`, `columns` and `fresh` keep their identity between reads (react-query shares
 * unchanged data), which is what lets this skip.
 */
const RowsTable = memo(function RowsTable({
  rows,
  columns,
  fresh,
}: {
  rows: Record<string, unknown>[];
  columns: Column[];
  fresh: ReadonlySet<string>;
}) {
  const keys = useMemo(() => rowKeys(rows), [rows]);
  const cells = useMemo<Cell[][]>(() => rows.map((row) => columns.map((c) => formatCell(row[c.name]))), [rows, columns]);
  const numeric = useMemo(() => columns.map((c) => !!c.type && NUMERIC.test(c.type)), [columns]);
  return (
    <div className="live-rows__scroll">
      <table className="live-rows__table">
        <thead>
          <tr>
            {columns.map((c, j) => (
              <th key={c.name} scope="col" className={numeric[j] ? "is-num" : undefined} title={c.type ? `${c.name}: ${c.type}` : c.name}>
                {c.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {cells.map((row, i) => (
            <tr key={keys[i]} className={fresh.has(keys[i]) ? "is-new" : undefined}>
              {row.map((cell, j) => (
                <td key={columns[j].name} className={`is-${cell.kind}${numeric[j] ? " is-right" : ""}`} title={cell.text.length > 40 ? cell.text : undefined}>
                  {cell.text}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
});

const NO_ROWS: ReadonlySet<string> = new Set();

/**
 * The data a stream node is landing, newest first: the end of its sink, re-read when a batch
 * lands. Rows that arrived since the last read are marked for a moment and counted ("+12 new"),
 * so the eye finds what is new without anything jumping; Pause freezes the table to read it and
 * says how many batches landed meanwhile. The node picker (`tabs`) sits on top: it says whose
 * data this is. A sink that has no files to read (kafka, console) or nothing yet says so
 * instead of an empty grid.
 */
export function LiveRows({
  node,
  data,
  updatedAt,
  loading,
  live,
  paused,
  onPausedChange,
  limit,
  onLimitChange,
  tabs,
  pendingBatches = 0,
}: {
  node: string;
  data?: StreamRows;
  /** When `data` was read: the clock "last write 2 s ago" counts from (no clock read in render). */
  updatedAt: number;
  loading: boolean;
  /** The stream is running (so the table refreshes). */
  live: boolean;
  paused: boolean;
  onPausedChange: (paused: boolean) => void;
  limit: RowLimit;
  onLimitChange: (limit: RowLimit) => void;
  /** The node picker, drawn as the panel's top edge. */
  tabs?: ReactNode;
  /** Batches the node landed since the table was paused. */
  pendingBatches?: number;
}) {
  const rows = data?.available ? data.rows : undefined;
  const [fresh, setFresh] = useState<ReadonlySet<string>>(NO_ROWS);
  const known = useRef<Set<string> | null>(null);
  useEffect(() => {
    if (!rows) return;
    const keys = rowKeys(rows);
    const before = known.current;
    known.current = new Set(keys);
    // The first read is not "new": only what arrives after it is.
    setFresh(before ? new Set(keys.filter((k) => !before.has(k))) : NO_ROWS);
  }, [rows]);

  const declared = data?.columns;
  const columns = useMemo<Column[]>(
    () => (declared?.length ? declared : rows?.[0] ? Object.keys(rows[0]).map((name) => ({ name })) : []),
    [declared, rows],
  );
  const state = !live ? "stopped" : paused ? "paused" : "live";

  return (
    <section className="live-rows" aria-label={`Live data of ${node}`}>
      <h2 className="sr-only">Live data</h2>
      <div className="live-rows__bar">
        {tabs}
        <span className="live-rows__tools">
          {state === "live" && fresh.size > 0 && (
            <span className="live-rows__new" key={updatedAt}>
              +{fresh.size} new
            </span>
          )}
          {state === "paused" && pendingBatches > 0 && (
            <span className="live-rows__pending" role="status">
              {pendingBatches} new {pendingBatches === 1 ? "batch" : "batches"} since paused
            </span>
          )}
          {live && (
            <button
              type="button"
              className="live-rows__pause"
              aria-pressed={paused}
              onClick={() => onPausedChange(!paused)}
              title={paused ? "Resume refreshing" : "Freeze the table to read it"}
            >
              {paused ? <IconPlayerPlay size={13} stroke={1.8} aria-hidden="true" /> : <IconPlayerPause size={13} stroke={1.8} aria-hidden="true" />}
              {paused ? "Resume" : "Pause"}
            </button>
          )}
          <SegmentedControl<`${RowLimit}`>
            aria-label="Rows shown"
            options={LIMITS.map((n) => ({ value: `${n}` as `${RowLimit}`, label: `${n}` }))}
            value={`${limit}`}
            onChange={(v) => onLimitChange(Number(v) as RowLimit)}
          />
        </span>
      </div>

      <div className="live-rows__sink">
        <span className="live-rows__where" title={data?.sink ?? undefined}>
          <b>{node}</b>
          {data?.sink && <> → {data.sink}</>}
        </span>
        <span className={`live-rows__state live-rows__state--${state}`}>
          <span className={`stream-dot${state === "live" ? " stream-dot--live" : ""}`} aria-hidden="true" />
          {state === "live" ? "Live" : state === "paused" ? "Paused" : "Stopped"}
        </span>
      </div>

      {loading && !data ? (
        <div className="live-rows__empty" role="status">
          <span className="stream-skel" /> Reading what {node} has written…
        </div>
      ) : data && !data.available ? (
        <div className="live-rows__empty" role="status">
          <IconTableOff size={18} stroke={1.6} aria-hidden="true" />
          <span>{data.reason ?? "There is nothing to show for this node."}</span>
        </div>
      ) : rows && rows.length === 0 ? (
        <div className="live-rows__empty" role="status">
          Nothing written yet — rows appear here as the node lands them.
        </div>
      ) : (
        rows && <RowsTable rows={rows} columns={columns} fresh={fresh} />
      )}

      {data?.available && (
        <footer className="live-rows__foot">
          {data.total_rows != null && <>{data.total_rows.toLocaleString("en")} rows in the sink · </>}
          {data.newest_at && updatedAt > 0 && <>last write {agoText(data.newest_at, updatedAt) || "—"} · </>}
          newest first
        </footer>
      )}
    </section>
  );
}
