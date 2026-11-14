import type { Meta, StoryObj } from "@storybook/react";
import { Field } from "./Field";

const meta = {
  title: "Redesign/Field",
  component: Field,
  parameters: { layout: "padded" },
  tags: ["autodocs"],
} satisfies Meta<typeof Field>;

export default meta;
type Story = StoryObj<typeof meta>;

const inputStyle: React.CSSProperties = {
  height: 36,
  padding: "0 12px",
  borderRadius: "var(--radius-md)",
  border: "1px solid var(--border)",
  background: "var(--surface-elevated)",
  color: "var(--text)",
  font: "inherit",
  width: "100%",
};

export const WithHelp: Story = {
  args: {
    label: "Nombre del pipeline",
    help: "Solo letras, números y guiones.",
    children: <input style={inputStyle} placeholder="daily_etl" />,
  },
};

export const WithError: Story = {
  args: {
    label: "Nombre del pipeline",
    required: true,
    error: "Este campo es obligatorio.",
    children: <input style={{ ...inputStyle, borderColor: "var(--danger)" }} />,
  },
};

export const Inline: Story = {
  args: {
    label: "Entorno",
    inline: true,
    children: (
      <select style={inputStyle}>
        <option>dev</option>
        <option>staging</option>
        <option>prod</option>
      </select>
    ),
  },
};

/** The wrapper wires aria-describedby + aria-invalid onto whatever control you pass. */
export const Accessibility: Story = {
  args: { label: "Demo", children: <input /> },
  render: () => (
    <div style={{ display: "grid", gap: 20, maxWidth: 420 }}>
      <Field label="Con ayuda" help="aria-describedby apunta al texto de ayuda.">
        <input style={inputStyle} />
      </Field>
      <Field label="Con error" required error="aria-invalid=true + role=alert.">
        <input style={{ ...inputStyle, borderColor: "var(--danger)" }} />
      </Field>
    </div>
  ),
};
