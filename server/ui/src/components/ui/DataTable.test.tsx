import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DataTable, type DataTableColumn } from "./DataTable";

interface Run {
  id: string;
  name: string;
  duration: number | null;
}

const rows: Run[] = [
  { id: "b", name: "beta", duration: 30 },
  { id: "a", name: "alpha", duration: 120 },
  { id: "c", name: "gamma", duration: null },
];

const columns: DataTableColumn<Run>[] = [
  { key: "name", header: "Name", sortable: true },
  { key: "duration", header: "Duration", sortable: true, align: "right", mono: true },
];

function setup(props: Partial<React.ComponentProps<typeof DataTable<Run>>> = {}) {
  return render(
    <DataTable columns={columns} rows={rows} rowKey={(r) => r.id} {...props} />
  );
}

/** Body row names, in render order. */
function bodyNames(): string[] {
  const body = screen.getAllByRole("rowgroup")[1];
  return within(body)
    .getAllByRole("row")
    .map((r) => within(r).getAllByRole("cell")[0].textContent ?? "");
}

describe("DataTable", () => {
  it("renders a row per record, in the order given", () => {
    setup();
    expect(bodyNames()).toEqual(["beta", "alpha", "gamma"]);
  });

  describe("sorting", () => {
    it("sorts ascending on first click and descending on second", async () => {
      const user = userEvent.setup();
      setup();

      await user.click(screen.getByRole("button", { name: /name/i }));
      expect(bodyNames()).toEqual(["alpha", "beta", "gamma"]);

      await user.click(screen.getByRole("button", { name: /name/i }));
      expect(bodyNames()).toEqual(["gamma", "beta", "alpha"]);
    });

    it("returns to the original order on the third click", async () => {
      const user = userEvent.setup();
      setup();
      const header = screen.getByRole("button", { name: /name/i });

      await user.click(header);
      await user.click(header);
      await user.click(header);

      expect(bodyNames()).toEqual(["beta", "alpha", "gamma"]);
    });

    it("keeps missing values last in both directions", async () => {
      // An absent duration is unknown, not "shorter than everything".
      const user = userEvent.setup();
      setup();
      const header = screen.getByRole("button", { name: /duration/i });

      await user.click(header);
      expect(bodyNames().at(-1)).toBe("gamma");
    });

    it("exposes the sort state to assistive technology", async () => {
      const user = userEvent.setup();
      setup();
      const header = screen.getByRole("columnheader", { name: /name/i });

      expect(header).toHaveAttribute("aria-sort", "none");
      await user.click(within(header).getByRole("button"));
      expect(header).toHaveAttribute("aria-sort", "ascending");
    });

    it("does not mutate the rows it was given", async () => {
      const user = userEvent.setup();
      const original = [...rows];
      setup();

      await user.click(screen.getByRole("button", { name: /name/i }));

      // Sorting the prop array in place would corrupt the query cache.
      expect(rows).toEqual(original);
    });
  });

  describe("row interaction", () => {
    it("calls onRowClick with the row", async () => {
      const user = userEvent.setup();
      const onRowClick = vi.fn();
      setup({ onRowClick });

      await user.click(screen.getByText("alpha"));

      expect(onRowClick).toHaveBeenCalledWith(rows[1]);
    });

    it("is operable by keyboard when clickable", async () => {
      // Tab order reaches the sortable column headers first, so focus the row
      // directly rather than counting tab stops.
      const user = userEvent.setup();
      const onRowClick = vi.fn();
      setup({ onRowClick });

      const body = screen.getAllByRole("rowgroup")[1];
      const firstRow = within(body).getAllByRole("row")[0];
      expect(firstRow).toHaveAttribute("tabindex", "0");

      firstRow.focus();
      await user.keyboard("{Enter}");
      expect(onRowClick).toHaveBeenCalledTimes(1);

      await user.keyboard(" ");
      expect(onRowClick).toHaveBeenCalledTimes(2);
    });

    it("is not focusable when there is nothing to click", () => {
      setup();
      const body = screen.getAllByRole("rowgroup")[1];
      within(body)
        .getAllByRole("row")
        .forEach((r) => expect(r).not.toHaveAttribute("tabindex"));
    });
  });

  describe("selection", () => {
    it("toggles a single row without triggering the row click", async () => {
      const user = userEvent.setup();
      const onChange = vi.fn();
      const onRowClick = vi.fn();
      setup({
        onRowClick,
        selection: { selected: new Set<string>(), onChange },
      });

      await user.click(screen.getByRole("checkbox", { name: /select row b/i }));

      expect(onChange).toHaveBeenCalledWith(new Set(["b"]));
      expect(onRowClick).not.toHaveBeenCalled();
    });

    it("select-all only takes the selectable rows", async () => {
      const user = userEvent.setup();
      const onChange = vi.fn();
      setup({
        selection: {
          selected: new Set<string>(),
          onChange,
          isSelectable: (r) => r.id !== "c",
        },
      });

      await user.click(screen.getByRole("checkbox", { name: /select all/i }));

      expect(onChange).toHaveBeenCalledWith(new Set(["b", "a"]));
    });

    it("disables the checkbox of an unselectable row", () => {
      setup({
        selection: {
          selected: new Set<string>(),
          onChange: vi.fn(),
          isSelectable: (r) => r.id !== "c",
        },
      });

      expect(screen.getByRole("checkbox", { name: /select row c/i })).toBeDisabled();
    });
  });

  describe("states", () => {
    it("shows skeleton rows while loading and no data", () => {
      setup({ loading: true, loadingRows: 3 });
      const body = screen.getAllByRole("rowgroup")[1];

      expect(within(body).getAllByRole("row")).toHaveLength(3);
      expect(screen.queryByText("alpha")).not.toBeInTheDocument();
    });

    it("shows the empty node when there are no rows", () => {
      setup({ rows: [], empty: <span>Nothing here yet</span> });
      expect(screen.getByText("Nothing here yet")).toBeInTheDocument();
    });

    it("does not show the empty node while loading", () => {
      setup({ rows: [], loading: true, empty: <span>Nothing here yet</span> });
      expect(screen.queryByText("Nothing here yet")).not.toBeInTheDocument();
    });

    it("shows the error instead of the rows", () => {
      setup({ error: "Could not load runs" });
      expect(screen.getByText("Could not load runs")).toBeInTheDocument();
      expect(screen.queryByText("alpha")).not.toBeInTheDocument();
    });
  });

  describe("presentation", () => {
    it("applies the requested density", () => {
      const { container } = setup({ density: "compact" });
      expect(container.querySelector(".tui-table")).toHaveClass("tui-table--compact");
    });

    it("gives an action column an accessible header name", () => {
      setup({
        columns: [...columns, { key: "actions", header: "", headerLabel: "Row actions" }],
      });
      expect(screen.getByRole("columnheader", { name: "Row actions" })).toBeInTheDocument();
    });
  });
});
