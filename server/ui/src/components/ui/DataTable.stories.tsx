import type { Meta, StoryObj } from "@storybook/react";
import { DataTable } from "./DataTable";
import { EmptyState } from "./EmptyState";
import { StatusBadge } from "./StatusBadge";

interface Run {
  id: string;
  pipeline: string;
  status: string;
  duration: number | null;
}

const rows: Run[] = [
  { id: "3f9a2c11", pipeline: "sales_daily", status: "success", duration: 42.1 },
  { id: "9b1e77d0", pipeline: "sales_daily", status: "failed", duration: 8.4 },
  { id: "c4d5e6f7", pipeline: "customer_360", status: "running", duration: null },
  { id: "aa10bb20", pipeline: "churn_training", status: "success", duration: 613.7 },
];

const columns = [
  { key: "status", header: "Status", sortable: true, cell: (r: Run) => <StatusBadge status={r.status} size="sm" /> },
  { key: "pipeline", header: "Pipeline", sortable: true },
  { key: "id", header: "ID", mono: true },
  {
    key: "duration",
    header: "Duration",
    sortable: true,
    align: "right" as const,
    mono: true,
    cell: (r: Run) => (r.duration == null ? "—" : `${r.duration.toFixed(1)}s`),
  },
];

const meta: Meta<typeof DataTable<Run>> = {
  title: "UI/DataTable",
  component: DataTable,
  parameters: {
    docs: {
      description: {
        component:
          "The shared table. Replaced three hand-rolled `<table>` implementations that " +
          "disagreed on padding, header weight and borders, and none of which could sort, " +
          "keep the header in view, or show a loading state inside the table.",
      },
    },
  },
};
export default meta;

type Story = StoryObj<typeof DataTable<Run>>;

export const Default: Story = {
  args: { columns, rows, rowKey: (r: Run) => r.id },
};

export const Compact: Story = {
  name: "Compact (nested in a card)",
  args: { columns, rows, rowKey: (r: Run) => r.id, density: "compact" },
};

export const Clickable: Story = {
  args: {
    columns,
    rows,
    rowKey: (r: Run) => r.id,
    onRowClick: (r: Run) => console.log("row", r.id),
    isRowSelected: (r: Run) => r.id === "9b1e77d0",
  },
};

export const WithSelection: Story = {
  name: "Selection (bulk actions)",
  args: {
    columns,
    rows,
    rowKey: (r: Run) => r.id,
    selection: {
      selected: new Set(["c4d5e6f7"]),
      onChange: () => {},
      // Only a running execution can be cancelled — the rest are disabled.
      isSelectable: (r: Run) => r.status === "running",
    },
  },
};

export const Loading: Story = {
  args: { columns, rows: [], rowKey: (r: Run) => r.id, loading: true },
};

export const Empty: Story = {
  args: {
    columns,
    rows: [],
    rowKey: (r: Run) => r.id,
    empty: <EmptyState title="No runs yet" description="Run a pipeline to see results here." />,
  },
};

export const ErrorState: Story = {
  name: "Error",
  args: { columns, rows: [], rowKey: (r: Run) => r.id, error: "Failed to load runs." },
};
