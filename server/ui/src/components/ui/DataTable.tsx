import { Fragment, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { IconChevronDown, IconChevronUp, IconSelector } from "@tabler/icons-react";
import { Skeleton } from "./Skeleton";
import { cx } from "../../utils/classNames";
import "./DataTable.css";
import { useUIStore } from "../../store/uiStore";

/**
 * The one table in the app.
 *
 * The three screens a Ducta operator actually lives in — execution history,
 * experiments, model registry — were each a hand-rolled `<table>` with its own
 * inline styles. They disagreed on header weight, on padding, on whether the
 * header even had a rule under it, and none of them could sort, keep the header
 * in view while scrolling, or show a loading state inside the table. Anything
 * added to one had to be added twice more, so in practice it was added once.
 *
 * Columns are declared, not laid out by hand; the component owns sorting,
 * selection, the scroll container and the empty/loading/error states.
 */
export interface DataTableColumn<T> {
  key: string;
  header: ReactNode;
  /** Defaults to `row[key]`. */
  cell?: (row: T) => ReactNode;
  /** Any CSS width — "120px", "1fr", "auto". Applied via <col>. */
  width?: string;
  align?: "left" | "right" | "center";
  /** Enables client-side sorting on this column. */
  sortable?: boolean;
  /** Value to sort on. Defaults to `row[key]`. */
  sortValue?: (row: T) => string | number | null | undefined;
  /** Render the cell in the monospace face — ids, durations, counts. */
  mono?: boolean;
  /** Accessible label when `header` is an icon or empty (e.g. an action column). */
  headerLabel?: string;
}

export interface DataTableSelection<T> {
  /** Rows that cannot be selected render a disabled checkbox. */
  isSelectable?: (row: T) => boolean;
  selected: ReadonlySet<string>;
  onChange: (next: Set<string>) => void;
}

export interface DataTableProps<T> {
  columns: DataTableColumn<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  /** `comfortable` for full-page tables, `compact` for tables nested in cards. */
  density?: "comfortable" | "compact";
  stickyHeader?: boolean;
  loading?: boolean;
  error?: ReactNode;
  /** Shown when there are no rows and nothing is loading. */
  empty?: ReactNode;
  onRowClick?: (row: T) => void;
  isRowSelected?: (row: T) => boolean;
  selection?: DataTableSelection<T>;
  /** Minimum width before the container starts scrolling horizontally. */
  minWidth?: number;
  /** Rows of skeleton to render while loading. */
  loadingRows?: number;
  caption?: string;
  /** Extra class(es) for a row's <tr> — e.g. a left-accent rail for a failed
   *  or running row. Returning undefined/"" leaves the row unstyled. */
  rowClassName?: (row: T) => string | undefined;
  /** Renders an expanded detail region in a full-width row directly under a
   *  given row — a sweep's member runs, an inline error preview, etc. Only
   *  the row matching `expandedRowKey` gets one. */
  renderRowDetail?: (row: T) => ReactNode;
  expandedRowKey?: string | null;
}

type SortState = { key: string; dir: "asc" | "desc" } | null;

function defaultValue<T>(row: T, key: string): unknown {
  return (row as Record<string, unknown>)[key];
}

function compare(a: unknown, b: unknown): number {
  // Nulls sort last regardless of direction — an absent duration is not
  // "smaller than" every other duration, it is simply unknown.
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  density: densityProp,
  stickyHeader = false,
  loading = false,
  error,
  empty,
  onRowClick,
  isRowSelected,
  selection,
  minWidth,
  loadingRows = 5,
  caption,
  rowClassName,
  renderRowDetail,
  expandedRowKey = null,
}: Readonly<DataTableProps<T>>) {
  // A table follows the app's density unless it asks for one.
  const appDensity = useUIStore((st) => st.density);
  const density = densityProp ?? appDensity;
  const [sort, setSort] = useState<SortState>(null);

  const sorted = useMemo(() => {
    if (!sort) return rows;
    const column = columns.find((c) => c.key === sort.key);
    if (!column) return rows;
    const read = column.sortValue ?? ((row: T) => defaultValue(row, column.key) as string | number);
    // Copy: sorting the prop array in place would mutate the query cache.
    const next = [...rows].sort((a, b) => compare(read(a), read(b)));
    return sort.dir === "asc" ? next : next.reverse();
  }, [rows, sort, columns]);

  const toggleSort = (key: string) =>
    setSort((current) => {
      if (current?.key !== key) return { key, dir: "asc" };
      if (current.dir === "asc") return { key, dir: "desc" };
      return null; // third click clears — back to the server's order
    });

  const selectableRows = selection
    ? sorted.filter((r) => selection.isSelectable?.(r) ?? true)
    : [];
  const allSelected =
    selectableRows.length > 0 && selectableRows.every((r) => selection!.selected.has(rowKey(r)));

  const toggleAll = () => {
    if (!selection) return;
    const next = new Set(selection.selected);
    if (allSelected) selectableRows.forEach((r) => next.delete(rowKey(r)));
    else selectableRows.forEach((r) => next.add(rowKey(r)));
    selection.onChange(next);
  };

  const toggleOne = (id: string) => {
    if (!selection) return;
    const next = new Set(selection.selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    selection.onChange(next);
  };

  const totalColumns = columns.length + (selection ? 1 : 0);

  return (
    <div className={`tui-table-scroll${stickyHeader ? " tui-table-scroll--sticky" : ""}`}>
      <table
        className={`tui-table tui-table--${density}`}
        style={minWidth ? { minWidth } : undefined}
      >
        {caption && <caption className="tui-table__caption">{caption}</caption>}
        <colgroup>
          {selection && <col style={{ width: 36 }} />}
          {columns.map((c) => (
            <col key={c.key} style={c.width ? { width: c.width } : undefined} />
          ))}
        </colgroup>

        <thead>
          <tr>
            {selection && (
              <th scope="col" className="tui-table__th tui-table__th--select">
                <input
                  type="checkbox"
                  checked={allSelected}
                  disabled={selectableRows.length === 0}
                  onChange={toggleAll}
                  aria-label={allSelected ? "Deselect all rows" : "Select all rows"}
                />
              </th>
            )}
            {columns.map((column) => {
              const active = sort?.key === column.key;
              const ariaSort = active ? (sort.dir === "asc" ? "ascending" : "descending") : "none";
              return (
                <th
                  key={column.key}
                  scope="col"
                  className={`tui-table__th tui-table__th--${column.align ?? "left"}`}
                  aria-sort={column.sortable ? ariaSort : undefined}
                >
                  {column.sortable ? (
                    <button
                      type="button"
                      className={`tui-table__sort${active ? " is-active" : ""}`}
                      onClick={() => toggleSort(column.key)}
                    >
                      <span>{column.header}</span>
                      {active ? (
                        sort.dir === "asc" ? (
                          <IconChevronUp size={13} />
                        ) : (
                          <IconChevronDown size={13} />
                        )
                      ) : (
                        <IconSelector size={13} className="tui-table__sort-hint" />
                      )}
                    </button>
                  ) : (
                    <span className={column.headerLabel ? "sr-only" : undefined}>
                      {column.headerLabel ?? column.header}
                    </span>
                  )}
                </th>
              );
            })}
          </tr>
        </thead>

        <tbody>
          {loading &&
            Array.from({ length: loadingRows }, (_, i) => (
              <tr key={`skeleton-${i}`} className="tui-table__row tui-table__row--skeleton">
                {Array.from({ length: totalColumns }, (_, c) => (
                  <td key={c} className="tui-table__td">
                    <Skeleton width={c === 0 ? "60%" : "80%"} />
                  </td>
                ))}
              </tr>
            ))}

          {!loading && error && (
            <tr>
              <td colSpan={totalColumns} className="tui-table__message tui-table__message--error">
                {error}
              </td>
            </tr>
          )}

          {!loading && !error && sorted.length === 0 && empty && (
            <tr>
              <td colSpan={totalColumns} className="tui-table__message">
                {empty}
              </td>
            </tr>
          )}

          {!loading &&
            !error &&
            sorted.map((row) => {
              const id = rowKey(row);
              const clickable = Boolean(onRowClick);
              const selectable = selection?.isSelectable?.(row) ?? true;
              const detail = renderRowDetail && expandedRowKey === id ? renderRowDetail(row) : null;
              return (
                <Fragment key={id}>
                <tr
                  className={cx(
                    "tui-table__row",
                    clickable && "tui-table__row--clickable",
                    isRowSelected?.(row) && "is-selected",
                    rowClassName?.(row),
                  )}
                  onClick={clickable ? () => onRowClick!(row) : undefined}
                  onKeyDown={
                    clickable
                      ? (e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            onRowClick!(row);
                          }
                        }
                      : undefined
                  }
                  tabIndex={clickable ? 0 : undefined}
                  aria-selected={isRowSelected ? isRowSelected(row) : undefined}
                >
                  {selection && (
                    <td
                      className="tui-table__td tui-table__td--select"
                      // The checkbox is its own control; clicking it must not
                      // also trigger the row's navigation.
                      onClick={(e) => e.stopPropagation()}
                    >
                      <input
                        type="checkbox"
                        checked={selection.selected.has(id)}
                        disabled={!selectable}
                        onChange={() => toggleOne(id)}
                        aria-label={`Select row ${id}`}
                      />
                    </td>
                  )}
                  {columns.map((column) => (
                    <td
                      key={column.key}
                      className={cx(
                        "tui-table__td",
                        `tui-table__td--${column.align ?? "left"}`,
                        column.mono && "tui-table__td--mono",
                      )}
                    >
                      {column.cell ? column.cell(row) : (defaultValue(row, column.key) as ReactNode)}
                    </td>
                  ))}
                </tr>
                {detail && (
                  <tr className="tui-table__row tui-table__row--detail">
                    <td colSpan={totalColumns} className="tui-table__td tui-table__td--detail">
                      {detail}
                    </td>
                  </tr>
                )}
                </Fragment>
              );
            })}
        </tbody>
      </table>
    </div>
  );
}
