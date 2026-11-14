import type { Meta, StoryObj } from "@storybook/react";

/**
 * Living documentation of the unified token foundation (theme/tokens.css).
 * Everything below reads CSS custom properties directly, so it always reflects
 * the real theme — light or dark.
 */
const meta = {
  title: "Redesign/Foundations/Tokens",
  parameters: { layout: "padded" },
} satisfies Meta;

export default meta;
type Story = StoryObj<typeof meta>;

const Row = ({ label, children }: { label: string; children: React.ReactNode }) => (
  <div style={{ display: "grid", gridTemplateColumns: "160px 1fr", gap: 16, alignItems: "center", marginBottom: 10 }}>
    <code style={{ color: "var(--text-muted)", fontSize: 12 }}>{label}</code>
    <div>{children}</div>
  </div>
);

const Section = ({ title, children }: { title: string; children: React.ReactNode }) => (
  <section style={{ marginBottom: 40 }}>
    <h3 style={{ color: "var(--text)", fontSize: "var(--text-lg)", marginBottom: 16 }}>{title}</h3>
    {children}
  </section>
);

const SPACES = ["1", "2", "3", "4", "5", "6", "8", "10", "12"];
const TYPES = ["xs", "sm", "base", "lg", "xl", "2xl", "3xl"];
const PALETTE = ["primary", "success", "warning", "danger", "blue", "green", "amber", "red", "purple"];
const STATUSES = ["idle", "pending", "running", "success", "warning", "failed", "cancelled"];

export const Foundations: Story = {
  render: () => (
    <div style={{ maxWidth: 760, fontFamily: "var(--font-sans)" }}>
      <Section title="Spacing (4-pt grid)">
        {SPACES.map((s) => (
          <Row key={s} label={`--space-${s}`}>
            <div style={{ height: 14, width: `var(--space-${s})`, background: "var(--primary)", borderRadius: 3 }} />
          </Row>
        ))}
      </Section>

      <Section title="Type scale">
        {TYPES.map((t) => (
          <Row key={t} label={`--text-${t}`}>
            <span style={{ fontSize: `var(--text-${t})`, color: "var(--text)" }}>Pipeline daily_etl</span>
          </Row>
        ))}
      </Section>

      <Section title="Palette">
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          {PALETTE.map((c) => (
            <div key={c} style={{ textAlign: "center" }}>
              <div style={{ width: 56, height: 56, borderRadius: "var(--radius-md)", background: `var(--${c})`, border: "1px solid var(--border)" }} />
              <code style={{ fontSize: 11, color: "var(--text-muted)" }}>{c}</code>
            </div>
          ))}
        </div>
      </Section>

      <Section title="Status tokens (fg / bg / border)">
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {STATUSES.map((s) => (
            <div
              key={s}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 8,
                alignSelf: "flex-start",
                padding: "4px 12px",
                borderRadius: "var(--radius-pill)",
                color: `var(--status-${s}-fg)`,
                background: `var(--status-${s}-bg)`,
                border: `1px solid var(--status-${s}-border)`,
                fontSize: "var(--text-sm)",
                fontWeight: 500,
              }}
            >
              <span style={{ width: 8, height: 8, borderRadius: 999, background: `var(--status-${s}-fg)` }} />
              {s}
            </div>
          ))}
        </div>
      </Section>

      <Section title="Radii & elevation">
        <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
          {["--radius-sm", "--radius-md", "--radius", "--radius-lg", "--radius-pill"].map((r) => (
            <div key={r} style={{ width: 72, height: 48, borderRadius: `var(${r})`, background: "var(--surface)", border: "1px solid var(--border)", display: "grid", placeItems: "center" }}>
              <code style={{ fontSize: 10, color: "var(--text-muted)" }}>{r.replace("--radius", "r")}</code>
            </div>
          ))}
          {["--shadow-sm", "--shadow-md", "--shadow-lg", "--shadow-xl"].map((sh) => (
            <div key={sh} style={{ width: 72, height: 48, borderRadius: "var(--radius-md)", background: "var(--surface-elevated)", boxShadow: `var(${sh})` }} />
          ))}
        </div>
      </Section>
    </div>
  ),
};
