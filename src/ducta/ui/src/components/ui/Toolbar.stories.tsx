import type { Meta, StoryObj } from "@storybook/react";
import { IconPlayerPlay, IconReload } from "@tabler/icons-react";
import { Toolbar } from "./Toolbar";
import { Button } from "./Button";
import { StatusBadge } from "./StatusBadge";
import { Panel } from "./Panel";

const meta = {
  title: "Redesign/Toolbar",
  component: Toolbar,
  parameters: { layout: "padded" },
  tags: ["autodocs"],
  argTypes: { bordered: { control: "boolean" } },
} satisfies Meta<typeof Toolbar>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Basic: Story = {
  args: {
    "aria-label": "Acciones de pipeline",
    bordered: true,
    children: (
      <>
        <Button variant="secondary" size="sm" leftIcon={<IconReload />}>
          Validar
        </Button>
        <Button variant="primary" size="sm" leftIcon={<IconPlayerPlay />}>
          Ejecutar
        </Button>
      </>
    ),
    end: <StatusBadge status="idle" />,
  },
};

/**
 * The task-centric action bar from the redesign brief: Validar → Ejecutar with
 * live status, composed from Panel + Toolbar + Button + StatusBadge.
 */
export const PipelineActionBar: Story = {
  render: () => (
    <Panel
      flush
      aria-label="Pipeline daily_etl"
      title="daily_etl"
      actions={<StatusBadge status="running" />}
    >
      <Toolbar
        aria-label="Acciones de ejecución"
        bordered
        end={
          <span style={{ color: "var(--text-muted)", fontSize: "var(--text-sm)" }}>
            entorno: <strong style={{ color: "var(--text)" }}>dev</strong>
          </span>
        }
      >
        <Button variant="secondary" leftIcon={<IconReload />}>
          Validar
        </Button>
        <Button variant="primary" leftIcon={<IconPlayerPlay />}>
          Ejecutar
        </Button>
      </Toolbar>
    </Panel>
  ),
};
