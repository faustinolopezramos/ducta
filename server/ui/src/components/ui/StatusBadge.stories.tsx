import type { Meta, StoryObj } from "@storybook/react";
import { StatusBadge, type Status } from "./StatusBadge";

const meta = {
  title: "Redesign/StatusBadge",
  component: StatusBadge,
  parameters: { layout: "centered" },
  tags: ["autodocs"],
  argTypes: {
    status: {
      control: "select",
      options: ["idle", "pending", "running", "success", "warning", "failed", "cancelled"],
    },
    size: { control: "select", options: ["sm", "md"] },
    variant: { control: "select", options: ["solid", "subtle", "dot"] },
  },
} satisfies Meta<typeof StatusBadge>;

export default meta;
type Story = StoryObj<typeof meta>;

const ALL: Status[] = ["idle", "pending", "running", "success", "warning", "failed", "cancelled"];

export const Running: Story = { args: { status: "running" } };

export const AllStatuses: Story = {
  args: { status: "idle" },
  render: () => (
    <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
      {ALL.map((s) => (
        <StatusBadge key={s} status={s} />
      ))}
    </div>
  ),
};

export const Variants: Story = {
  args: { status: "idle" },
  render: () => (
    <div style={{ display: "grid", gap: 12 }}>
      {(["subtle", "solid", "dot"] as const).map((v) => (
        <div key={v} style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          {ALL.map((s) => (
            <StatusBadge key={s} status={s} variant={v} />
          ))}
        </div>
      ))}
    </div>
  ),
};

/** Backend aliases (active → running, error → failed) normalize automatically. */
export const Aliases: Story = {
  args: { status: "idle" },
  render: () => (
    <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
      <StatusBadge status="active" />
      <StatusBadge status="error" />
      <StatusBadge status="queued" />
      <StatusBadge status="unknown-state" />
    </div>
  ),
};
