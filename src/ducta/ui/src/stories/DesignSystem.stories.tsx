import type { Meta, StoryObj } from "@storybook/react";

const meta = {
  title: "Design System/Colors",
  parameters: {
    layout: "fullscreen",
  },
} satisfies Meta<any>;

export default meta;
type Story = StoryObj<any>;

/**
 * Color palette for the Ducta UI
 * Modern indigo/teal/cyan design system
 */
export const ColorPalette: Story = {
  render: () => (
    <div style={{ padding: 40, background: "var(--bg)" }}>
      <h1 style={{ color: "var(--text)", marginBottom: 30 }}>
        Ducta Design System - Color Palette
      </h1>

      {/* Primary Colors */}
      <section style={{ marginBottom: 40 }}>
        <h2 style={{ color: "var(--text)", fontSize: 20, marginBottom: 20 }}>
          Primary Colors
        </h2>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 16 }}>
          <ColorSwatch name="Accent (Indigo)" variable="--accent" />
          <ColorSwatch name="Accent Dim" variable="--accent-dim" />
          <ColorSwatch name="Accent BG" variable="--accent-bg" />
        </div>
      </section>

      {/* Success Colors */}
      <section style={{ marginBottom: 40 }}>
        <h2 style={{ color: "var(--text)", fontSize: 20, marginBottom: 20 }}>
          Status Colors
        </h2>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 16 }}>
          <ColorSwatch name="Green (Success)" variable="--green" />
          <ColorSwatch name="Blue (Info)" variable="--blue" />
          <ColorSwatch name="Red (Error)" variable="--red" />
          <ColorSwatch name="Amber (Warning)" variable="--amber" />
          <ColorSwatch name="Purple" variable="--purple" />
        </div>
      </section>

      {/* Neutral Colors */}
      <section style={{ marginBottom: 40 }}>
        <h2 style={{ color: "var(--text)", fontSize: 20, marginBottom: 20 }}>
          Neutral Colors
        </h2>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 16 }}>
          <ColorSwatch name="Background" variable="--bg" />
          <ColorSwatch name="Surface" variable="--surface" />
          <ColorSwatch name="Surface Hover" variable="--surface-hover" />
          <ColorSwatch name="Border" variable="--border" />
          <ColorSwatch name="Border Hover" variable="--border-hover" />
          <ColorSwatch name="Text" variable="--text" />
          <ColorSwatch name="Text Muted" variable="--text-muted" />
          <ColorSwatch name="Text Dim" variable="--text-dim" />
        </div>
      </section>
    </div>
  ),
};

/**
 * Typography styles for the design system
 */
export const Typography: Story = {
  render: () => (
    <div style={{ padding: 40, background: "var(--bg)" }}>
      <h1 style={{ color: "var(--text)", marginBottom: 30 }}>
        Typography
      </h1>

      <section style={{ marginBottom: 40 }}>
        <h2 style={{ color: "var(--text-muted)", fontSize: 16, marginBottom: 20 }}>
          Headings
        </h2>
        <h1 style={{ color: "var(--text)", margin: "0 0 16px", fontSize: 32 }}>
          H1 - Large heading
        </h1>
        <h2 style={{ color: "var(--text)", margin: "0 0 16px", fontSize: 26 }}>
          H2 - Medium heading
        </h2>
        <h3 style={{ color: "var(--text)", margin: "0 0 16px", fontSize: 22 }}>
          H3 - Small heading
        </h3>
      </section>

      <section style={{ marginBottom: 40 }}>
        <h2 style={{ color: "var(--text-muted)", fontSize: 16, marginBottom: 20 }}>
          Body Text
        </h2>
        <p style={{ color: "var(--text)", margin: "0 0 12px", fontSize: 14 }}>
          This is regular body text - used for descriptions and content
        </p>
        <p style={{ color: "var(--text-muted)", margin: "0 0 12px", fontSize: 13 }}>
          This is muted text - used for secondary information
        </p>
        <p style={{ color: "var(--text-dim)", margin: "0 0 12px", fontSize: 12 }}>
          This is dim text - used for tertiary information and hints
        </p>
      </section>

      <section>
        <h2 style={{ color: "var(--text-muted)", fontSize: 16, marginBottom: 20 }}>
          Monospace (Code)
        </h2>
        <code
          style={{
            fontFamily: "var(--font-mono)",
            color: "var(--accent)",
            background: "var(--accent-bg)",
            padding: "4px 8px",
            borderRadius: 4,
            fontSize: 13,
          }}
        >
          my.pipeline.name
        </code>
      </section>
    </div>
  ),
};

/**
 * Spacing scale
 */
export const Spacing: Story = {
  render: () => (
    <div style={{ padding: 40, background: "var(--bg)" }}>
      <h1 style={{ color: "var(--text)", marginBottom: 30 }}>
        Spacing Scale
      </h1>

      <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
        {[8, 12, 16, 24, 32, 48, 64].map((size) => (
          <div key={size} style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span style={{ color: "var(--text-dim)", minWidth: 40 }}>
              {size}px
            </span>
            <div
              style={{
                width: size,
                height: size,
                background: "var(--accent)",
                borderRadius: 4,
              }}
            />
          </div>
        ))}
      </div>
    </div>
  ),
};

// Helper component
function ColorSwatch({ name, variable }: { name: string; variable: string }) {
  const color = getComputedStyle(document.documentElement).getPropertyValue(variable).trim();

  return (
    <div
      style={{
        borderRadius: 8,
        border: "1px solid var(--border)",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          background: `var(${variable})`,
          height: 60,
        }}
      />
      <div style={{ padding: 12 }}>
        <div style={{ color: "var(--text)", fontSize: 13, fontWeight: 500 }}>
          {name}
        </div>
        <div style={{ color: "var(--text-dim)", fontSize: 11, fontFamily: "var(--font-mono)" }}>
          {variable}
        </div>
        <div style={{ color: "var(--text-muted)", fontSize: 11, fontFamily: "var(--font-mono)" }}>
          {color}
        </div>
      </div>
    </div>
  );
}
