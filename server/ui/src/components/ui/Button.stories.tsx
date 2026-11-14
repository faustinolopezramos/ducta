import type { Meta, StoryObj } from "@storybook/react";
import { IconPlayerPlay, IconReload, IconTrash } from "@tabler/icons-react";
import { Button } from "./Button";

const meta = {
  title: "Redesign/Button",
  component: Button,
  parameters: { layout: "centered" },
  tags: ["autodocs"],
  argTypes: {
    variant: { control: "select", options: ["primary", "secondary", "ghost", "danger"] },
    size: { control: "select", options: ["sm", "md", "lg"] },
    loading: { control: "boolean" },
    disabled: { control: "boolean" },
    fullWidth: { control: "boolean" },
    children: { control: "text" },
  },
} satisfies Meta<typeof Button>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Primary: Story = { args: { variant: "primary", children: "Ejecutar pipeline" } };
export const Secondary: Story = { args: { variant: "secondary", children: "Validar" } };
export const Ghost: Story = { args: { variant: "ghost", children: "Cancelar" } };
export const Danger: Story = { args: { variant: "danger", children: "Eliminar" } };

export const WithIcons: Story = {
  args: { variant: "primary", children: "Ejecutar", leftIcon: <IconPlayerPlay /> },
};

export const Loading: Story = {
  args: { variant: "primary", children: "Ejecutando…", loading: true },
};

export const Variants: Story = {
  render: () => (
    <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
      <Button variant="primary" leftIcon={<IconPlayerPlay />}>
        Ejecutar
      </Button>
      <Button variant="secondary" leftIcon={<IconReload />}>
        Validar
      </Button>
      <Button variant="ghost">Cancelar</Button>
      <Button variant="danger" leftIcon={<IconTrash />}>
        Eliminar
      </Button>
    </div>
  ),
};

export const Sizes: Story = {
  render: () => (
    <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
      <Button size="sm">Small</Button>
      <Button size="md">Medium</Button>
      <Button size="lg">Large</Button>
    </div>
  ),
};

export const States: Story = {
  render: () => (
    <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
      <Button variant="primary">Normal</Button>
      <Button variant="primary" loading>
        Loading
      </Button>
      <Button variant="primary" disabled>
        Disabled
      </Button>
    </div>
  ),
};
