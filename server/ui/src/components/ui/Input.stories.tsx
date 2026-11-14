import type { Meta, StoryObj } from "@storybook/react";
import { Input } from "./Input";

const meta = {
  title: "Components/Input",
  component: Input,
  parameters: {
    layout: "centered",
  },
  tags: ["autodocs"],
  argTypes: {
    label: {
      control: { type: "text" },
      description: "Input label",
    },
    placeholder: {
      control: { type: "text" },
      description: "Placeholder text",
    },
    value: {
      control: { type: "text" },
      description: "Input value",
    },
    error: {
      control: { type: "boolean" },
      description: "Error state",
    },
    helperText: {
      control: { type: "text" },
      description: "Helper or error text",
    },
    mono: {
      control: { type: "boolean" },
      description: "Use monospace font",
    },
    disabled: {
      control: { type: "boolean" },
      description: "Disable input",
    },
  },
} satisfies Meta<typeof Input>;

export default meta;
type Story = StoryObj<typeof meta>;

/**
 * Basic input
 */
export const Basic: Story = {
  args: {
    label: "Enter text",
    placeholder: "Type something...",
    value: "",
    onChange: () => {},
  },
};

/**
 * Input with value
 */
export const WithValue: Story = {
  args: {
    label: "Name",
    value: "John Doe",
    onChange: () => {},
  },
};

/**
 * Error state
 */
export const Error: Story = {
  args: {
    label: "Email",
    placeholder: "user@example.com",
    value: "",
    error: true,
    helperText: "Invalid email address",
    onChange: () => {},
  },
};

/**
 * Monospace input (for code/identifiers)
 */
export const Monospace: Story = {
  args: {
    label: "Pipeline name",
    placeholder: "my.pipeline",
    value: "",
    mono: true,
    onChange: () => {},
  },
};

/**
 * Disabled input
 */
export const Disabled: Story = {
  args: {
    label: "Read-only",
    value: "Cannot edit",
    disabled: true,
    onChange: () => {},
  },
};

/**
 * Input showcase
 */
export const Showcase: Story = {
  args: {
    label: "Preview",
    value: "",
    onChange: () => {},
  },
  render: () => (
    <div style={{ display: "flex", flexDirection: "column", gap: 24, width: 400 }}>
      <Input label="Regular input" placeholder="Enter text..." value="" onChange={() => {}} />
      <Input label="With error" placeholder="Invalid" value="" onChange={() => {}} error helperText="This field is required" />
      <Input label="Monospace" placeholder="my.identifier" value="" onChange={() => {}} mono />
      <Input label="Disabled" value="Read-only" onChange={() => {}} disabled />
    </div>
  ),
};
