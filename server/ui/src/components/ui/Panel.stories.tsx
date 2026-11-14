import type { Meta, StoryObj } from "@storybook/react";
import { Panel } from "./Panel";
import { Button } from "./Button";
import { StatusBadge } from "./StatusBadge";

const meta = {
  title: "Redesign/Panel",
  component: Panel,
  parameters: { layout: "padded" },
  tags: ["autodocs"],
  argTypes: {
    elevation: { control: "select", options: ["flat", "raised"] },
    flush: { control: "boolean" },
  },
} satisfies Meta<typeof Panel>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Basic: Story = {
  args: {
    title: "Configuración",
    description: "Parámetros del pipeline para el entorno seleccionado.",
    children: <p style={{ color: "var(--text-muted)", margin: 0 }}>Contenido del panel…</p>,
  },
};

export const WithActions: Story = {
  args: {
    title: "daily_etl",
    actions: (
      <>
        <StatusBadge status="success" />
        <Button size="sm" variant="secondary">
          Editar
        </Button>
      </>
    ),
    children: <p style={{ color: "var(--text-muted)", margin: 0 }}>3 nodos · última ejecución hace 2 h</p>,
  },
};

export const Raised: Story = {
  args: {
    title: "Panel elevado",
    elevation: "raised",
    children: <p style={{ color: "var(--text-muted)", margin: 0 }}>Usa sombra en vez de solo borde.</p>,
  },
};
